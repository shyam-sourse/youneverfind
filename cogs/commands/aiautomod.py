# ╔══════════════════════════════════════════════════════════════════╗
# ║   AI AutoMod  ──  Groq powered smart moderation                  ║
# ╚══════════════════════════════════════════════════════════════════╝

import os
import re
import time
import random
import hashlib
import asyncio
from collections import deque, OrderedDict
from datetime import timedelta

import discord
from discord.ext import commands

from utils.emoji import ZAI, TICK, CROSS, WARNING, INFO, ENABLE, DISABLE
from utils.ai_staff_core import (db, now, is_staff, ai_json, COLOR)
from utils.groq_keys import key_manager

SENSITIVITY = {
    "low": 8,       # only very severe content
    "medium": 6,
    "high": 4,      # flags borderline content too
}

# ── cost control ────────────────────────────────────────────────────
# The old automod called the 70B chat model for EVERY message with a 900
# token budget. That is what drained the daily quota. Now:
#   * a cheap/fast model does classification
#   * a tiny token budget is used (the answer is a small JSON object)
#   * obvious chatter is skipped locally and the rest is sampled
#   * identical messages are served from a cache
#   * a hard per-minute budget caps total calls
AUTOMOD_MODEL = os.getenv("AI_AUTOMOD_MODEL", "llama-3.1-8b-instant")
AUTOMOD_MAX_TOKENS = 150
MAX_CALLS_PER_MINUTE = int(os.getenv("AI_AUTOMOD_MAX_PER_MIN", "20"))
USER_COOLDOWN = 8           # seconds between checks for the same user
CACHE_TTL = 60 * 60 * 6     # reuse a verdict for 6 hours
CACHE_MAX = 800

# Local pre-filter: matching messages always go to the AI; ordinary chatter
# is only sampled so we do not pay for every "lol" and "good morning".
SUSPECT = re.compile(
    r"(\bkys\b|kill\s+your\s*self|\bkill\s+you\b|\bi\s+will\s+kill\b|"
    r"\bdoxx?\b|\bswat\b|"
    r"\bnigg\w*|\bfag\w*|\bretard\w*|\brape\w*|\bpedo\w*|\bmolest\w*|"
    r"free\s+nitro|steam\s+gift|discord\.gift|claim\s+your|airdrop|"
    r"double\s+your|crypto\s+giveaway|invest\s+now|dm\s+me\s+to|"
    r"click\s+here|bit\.ly|tinyurl|t\.me/|onlyfans|\bnsfw\b|\bporn\w*|"
    r"\bnude\w*|sex\s+chat|sell\s+account|buy\s+followers|"
    r"\bhack(?:ed|ing)?\b)",
    re.IGNORECASE,
)
INVITE = re.compile(r"(discord\.gg/|discord(?:app)?\.com/invite/)", re.IGNORECASE)
LINK = re.compile(r"https?://|www\.", re.IGNORECASE)
REPEAT = re.compile(r"(.)\1{6,}")

#: fraction of "normal" messages that are still sent to the AI
SAMPLE_RATE = {"low": 0.05, "medium": 0.12, "high": 0.25}

SYSTEM = (
    "You are a Discord auto-moderation classifier. Judge ONE message. "
    "Return JSON: {\"flag\": true/false, \"category\": \"toxicity|harassment|hate|"
    "nsfw|scam|spam|self_harm|threat|advertising|none\", \"severity\": 1-10, "
    "\"reason\": \"one short sentence\"}. Be fair: casual banter, mild slang and "
    "gaming talk are NOT violations."
)


def _suspicious_signals(content: str) -> bool:
    """Cheap local check for messages that clearly deserve an AI look."""
    if SUSPECT.search(content):
        return True
    if INVITE.search(content):
        return True
    mentions = content.count("<@") + content.count("@everyone") + content.count("@here")
    if mentions >= 5:
        return True
    if len(content) >= 60 and content.count("http") >= 2:
        return True
    letters = [c for c in content if c.isalpha()]
    if len(letters) >= 15 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        return True
    if REPEAT.search(content):
        return True
    return False


class AIAutoMod(commands.Cog):
    """AI powered automod that understands context, not just word lists."""

    def __init__(self, bot):
        self.bot = bot
        self.db = db()
        self._cooldown = {}     # (guild, user) -> timestamp
        self._sem = asyncio.Semaphore(2)
        # cost-control state
        self._cache = OrderedDict()     # content hash -> (ts, verdict)
        self._call_times = deque()      # timestamps of calls in the last minute
        self._counters = {"scanned": 0, "ai_calls": 0, "cache_hits": 0,
                          "skipped": 0, "budget_skips": 0, "flagged": 0}

    # ----------------------- cost-control helpers ---------------------
    def _cache_get(self, digest):
        entry = self._cache.get(digest)
        if not entry:
            return None
        ts, verdict = entry
        if time.time() - ts > CACHE_TTL:
            self._cache.pop(digest, None)
            return None
        self._cache.move_to_end(digest)
        return verdict

    def _cache_put(self, digest, verdict):
        self._cache[digest] = (time.time(), verdict)
        self._cache.move_to_end(digest)
        while len(self._cache) > CACHE_MAX:
            self._cache.popitem(last=False)

    def _allow_call(self):
        cutoff = time.time() - 60
        while self._call_times and self._call_times[0] < cutoff:
            self._call_times.popleft()
        if len(self._call_times) >= MAX_CALLS_PER_MINUTE:
            return False
        self._call_times.append(time.time())
        return True

    def _should_scan(self, content, sensitivity):
        if _suspicious_signals(content):
            return True
        rate = SAMPLE_RATE.get(sensitivity, 0.12)
        return random.random() < rate

    @staticmethod
    def _prune_cooldowns(cooldowns, max_size=5000):
        if len(cooldowns) <= max_size:
            return
        cutoff = time.time() - 300
        for key in [k for k, v in cooldowns.items() if v < cutoff]:
            cooldowns.pop(key, None)


    @staticmethod
    def help_custom():
        return (ZAI, "AI AutoMod", "Groq powered smart message moderation.")

    # ----------------------------- config -----------------------------
    def cfg(self, guild_id):
        row = self.db.execute(
            "SELECT enabled, sensitivity, action, log_channel, ignored "
            "FROM ai_automod WHERE guild_id=?", (str(guild_id),)).fetchone()
        if not row:
            return {"enabled": 0, "sensitivity": "medium", "action": "delete",
                    "log_channel": None, "ignored": ""}
        return {"enabled": row[0], "sensitivity": row[1], "action": row[2],
                "log_channel": row[3], "ignored": row[4] or ""}

    def set_cfg(self, guild_id, **fields):
        self.db.execute(
            "INSERT OR IGNORE INTO ai_automod (guild_id) VALUES (?)",
            (str(guild_id),))
        for key, value in fields.items():
            self.db.execute(
                f"UPDATE ai_automod SET {key}=? WHERE guild_id=?",
                (value, str(guild_id)))
        self.db.commit()

    def embed(self, title, description):
        return discord.Embed(title=title, description=description, color=COLOR)

    # ----------------------------- commands ---------------------------
    @commands.group(name="aiautomod", aliases=["aiam"],
                    invoke_without_command=True,
                    help="AI powered automod — setup and controls.")
    @commands.guild_only()
    async def aiautomod(self, ctx):
        cfg = self.cfg(ctx.guild.id)
        state = f"{ENABLE} Enabled" if cfg["enabled"] else f"{DISABLE} Disabled"
        channel = f"<#{cfg['log_channel']}>" if cfg["log_channel"] else "Not set"
        await ctx.send(embed=self.embed(
            f"{ZAI} AI AutoMod",
            f"**Status:** {state}\n"
            f"**Sensitivity:** `{cfg['sensitivity']}`\n"
            f"**Action:** `{cfg['action']}`\n"
            f"**Log channel:** {channel}\n\n"
            f"`{ctx.clean_prefix}aiautomod enable` • `disable` • "
            f"`sensitivity <low/medium/high>` • `action <delete/warn/timeout>` • "
            f"`log <#channel>` • `ignore <#channel>` • `unignore <#channel>` • "
            f"`test <text>` • `hits` • `stats`"))

    @aiautomod.command(name="enable", help="Turn AI automod on for this server.")
    @commands.has_permissions(manage_guild=True)
    async def enable(self, ctx):
        self.set_cfg(ctx.guild.id, enabled=1)
        await ctx.send(embed=self.embed(f"{TICK} AI AutoMod Enabled",
                                        "Messages are now screened by the AI."))

    @aiautomod.command(name="disable", help="Turn AI automod off for this server.")
    @commands.has_permissions(manage_guild=True)
    async def disable(self, ctx):
        self.set_cfg(ctx.guild.id, enabled=0)
        await ctx.send(embed=self.embed(f"{CROSS} AI AutoMod Disabled",
                                        "AI screening stopped."))

    @aiautomod.command(name="sensitivity",
                       help="Set how strict the AI is: low, medium or high.")
    @commands.has_permissions(manage_guild=True)
    async def sensitivity(self, ctx, level: str):
        level = level.lower()
        if level not in SENSITIVITY:
            return await ctx.send(embed=self.embed(
                f"{WARNING} Invalid Level", "Choose `low`, `medium` or `high`."))
        self.set_cfg(ctx.guild.id, sensitivity=level)
        await ctx.send(embed=self.embed(f"{TICK} Sensitivity Updated",
                                        f"AI automod sensitivity is now `{level}`."))

    @aiautomod.command(name="action",
                       help="What to do on a violation: delete, warn or timeout.")
    @commands.has_permissions(manage_guild=True)
    async def action(self, ctx, mode: str):
        mode = mode.lower()
        if mode not in ("delete", "warn", "timeout"):
            return await ctx.send(embed=self.embed(
                f"{WARNING} Invalid Action", "Choose `delete`, `warn` or `timeout`."))
        self.set_cfg(ctx.guild.id, action=mode)
        await ctx.send(embed=self.embed(f"{TICK} Action Updated",
                                        f"Violations will now be handled with `{mode}`."))

    @aiautomod.command(name="log", help="Set the AI automod log channel.")
    @commands.has_permissions(manage_guild=True)
    async def log(self, ctx, channel: discord.TextChannel):
        self.set_cfg(ctx.guild.id, log_channel=str(channel.id))
        await ctx.send(embed=self.embed(f"{TICK} Log Channel Set",
                                        f"AI automod will log to {channel.mention}."))

    @aiautomod.command(name="ignore", help="Exclude a channel from AI automod.")
    @commands.has_permissions(manage_guild=True)
    async def ignore(self, ctx, channel: discord.TextChannel):
        cfg = self.cfg(ctx.guild.id)
        ids = [i for i in cfg["ignored"].split(",") if i]
        if str(channel.id) not in ids:
            ids.append(str(channel.id))
        self.set_cfg(ctx.guild.id, ignored=",".join(ids))
        await ctx.send(embed=self.embed(f"{TICK} Channel Ignored",
                                        f"{channel.mention} is no longer screened."))

    @aiautomod.command(name="unignore", help="Screen an ignored channel again.")
    @commands.has_permissions(manage_guild=True)
    async def unignore(self, ctx, channel: discord.TextChannel):
        cfg = self.cfg(ctx.guild.id)
        ids = [i for i in cfg["ignored"].split(",") if i and i != str(channel.id)]
        self.set_cfg(ctx.guild.id, ignored=",".join(ids))
        await ctx.send(embed=self.embed(f"{TICK} Channel Restored",
                                        f"{channel.mention} is screened again."))

    @aiautomod.command(name="test", help="Test how the AI would judge some text.")
    @commands.has_permissions(manage_messages=True)
    async def test(self, ctx, *, text: str):
        async with ctx.typing():
            verdict = await ai_json(f"Message: {text[:1200]}", SYSTEM,
                                   retries=0, model=AUTOMOD_MODEL,
                                   max_tokens=AUTOMOD_MAX_TOKENS)
        if not verdict:
            return await ctx.send(embed=self.embed(
                f"{WARNING} AI Unavailable", "The AI could not be reached right now."))
        await ctx.send(embed=self.embed(
            f"{ZAI} AI Verdict",
            f"**Flag:** `{verdict.get('flag')}`\n"
            f"**Category:** `{verdict.get('category', 'none')}`\n"
            f"**Severity:** `{verdict.get('severity', 0)}/10`\n"
            f"**Reason:** {verdict.get('reason', '—')}"))

    @aiautomod.command(name="hits", help="Show the latest AI automod detections.")
    @commands.has_permissions(manage_messages=True)
    async def hits(self, ctx):
        rows = self.db.execute(
            "SELECT user_id, category, severity, reason, created_at FROM ai_automod_hits "
            "WHERE guild_id=? ORDER BY id DESC LIMIT 10",
            (str(ctx.guild.id),)).fetchall()
        if not rows:
            return await ctx.send(embed=self.embed(f"{INFO} No Detections",
                                                   "Nothing has been flagged yet."))
        body = "\n".join(
            f"<@{r[0]}> • `{r[1]}` severity `{r[2]}` — {r[3]}" for r in rows)
        await ctx.send(embed=self.embed(f"{ZAI} Recent AI Detections", body))

    @aiautomod.command(name="stats",
                       help="Show how many AI calls automod is making (cost control).")
    @commands.has_permissions(manage_messages=True)
    async def stats(self, ctx):
        cutoff = time.time() - 60
        recent = len([t for t in self._call_times if t >= cutoff])
        c = self._counters
        ready = sum(1 for r in key_manager.info() if r["state"] == "ready")
        await ctx.send(embed=self.embed(
            f"{ZAI} AI AutoMod — Usage",
            f"**Model:** `{AUTOMOD_MODEL}`\n"
            f"**Calls last minute:** `{recent}/{MAX_CALLS_PER_MINUTE}`\n"
            f"**Cache:** `{len(self._cache)}` verdicts\n"
            f"**Keys ready:** `{ready}` / `{len(key_manager.keys)}`\n\n"
            f"**Screened messages:** `{c['scanned']}`\n"
            f"**AI calls:** `{c['ai_calls']}`\n"
            f"**Cache hits:** `{c['cache_hits']}`\n"
            f"**Skipped locally:** `{c['skipped']}`\n"
            f"**Skipped by budget:** `{c['budget_skips']}`\n"
            f"**Flagged:** `{c['flagged']}`"))

    # ----------------------------- listener ---------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or not message.content:
            return
        if len(message.content) < 4:
            return
        cfg = self.cfg(message.guild.id)
        if not cfg["enabled"]:
            return
        if str(message.channel.id) in (cfg["ignored"] or "").split(","):
            return
        if is_staff(message.author):
            return

        self._counters["scanned"] += 1
        content = message.content.strip()

        # 1. per-user cooldown (cheap, before any expensive work)
        key = (message.guild.id, message.author.id)
        last = self._cooldown.get(key, 0)
        if time.time() - last < USER_COOLDOWN:
            return
        self._cooldown[key] = time.time()
        self._prune_cooldowns(self._cooldown)

        # 2. local pre-filter: skip ordinary chatter, only sample some of it
        if not self._should_scan(content, cfg["sensitivity"]):
            self._counters["skipped"] += 1
            return

        # 3. cache: identical / repeated messages never cost a call
        digest = hashlib.sha256(content.lower().encode("utf-8", "ignore")).hexdigest()
        verdict = self._cache_get(digest)
        if verdict is not None:
            self._counters["cache_hits"] += 1
        else:
            # 4. hard per-minute budget so a raid can never burn every key
            if not self._allow_call():
                self._counters["budget_skips"] += 1
                return
            async with self._sem:
                verdict = await ai_json(
                    f"Message: {content[:1200]}", SYSTEM,
                    retries=0, model=AUTOMOD_MODEL,
                    max_tokens=AUTOMOD_MAX_TOKENS,
                )
            self._counters["ai_calls"] += 1
            if verdict is not None:
                self._cache_put(digest, verdict)

        if not verdict or not verdict.get("flag"):
            return

        try:
            severity = int(verdict.get("severity", 0))
        except (TypeError, ValueError):
            severity = 0
        if severity < SENSITIVITY.get(cfg["sensitivity"], 6):
            return

        self._counters["flagged"] += 1
        category = str(verdict.get("category", "unknown"))
        reason = str(verdict.get("reason", "Violation detected"))[:400]

        self.db.execute(
            "INSERT INTO ai_automod_hits (guild_id, user_id, category, severity, "
            "reason, content, created_at) VALUES (?,?,?,?,?,?,?)",
            (str(message.guild.id), str(message.author.id), category, severity,
             reason, message.content[:500], now()))
        self.db.commit()

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        if cfg["action"] == "warn":
            try:
                await message.channel.send(
                    f"{WARNING} {message.author.mention} — {reason}",
                    delete_after=10)
            except discord.HTTPException:
                pass
        elif cfg["action"] == "timeout":
            minutes = 10 if severity >= 8 else 5
            try:
                await message.author.timeout(timedelta(minutes=minutes),
                                             reason=f"AI AutoMod: {reason}")
            except discord.HTTPException:
                pass

        if cfg["log_channel"]:
            channel = message.guild.get_channel(int(cfg["log_channel"]))
            if channel:
                embed = self.embed(
                    f"{ZAI} AI AutoMod Action",
                    f"**User:** {message.author.mention} (`{message.author.id}`)\n"
                    f"**Channel:** {message.channel.mention}\n"
                    f"**Category:** `{category}` • **Severity:** `{severity}/10`\n"
                    f"**Reason:** {reason}\n"
                    f"**Action:** `{cfg['action']}`\n"
                    f"**Content:** ```{message.content[:400]}```")
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass


async def setup(bot):
    await bot.add_cog(AIAutoMod(bot))
