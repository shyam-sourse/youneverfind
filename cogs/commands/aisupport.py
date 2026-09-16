# ╔══════════════════════════════════════════════════════════════════╗
# ║   AI Support  ──  FAQ auto-answer + ticket/channel summaries     ║
# ╚══════════════════════════════════════════════════════════════════╝
"""A support-channel assistant.

* Staff store answers in a per-server FAQ. A matching question is answered
  instantly from the FAQ (no AI call at all).
* When nothing matches locally, the AI answers using the FAQ as context —
  but only for real questions, with a per-user cooldown, a per-minute budget
  and a response cache, so the key pool is never hammered.
* ``aisupport summarize`` condenses a ticket/channel into a short report.
"""

import re
import time
import hashlib
from collections import deque, OrderedDict

import discord
from discord.ext import commands

from utils.emoji import ZAI, TICK, CROSS, WARNING, INFO, ENABLE, DISABLE, PIN
from utils.ai_staff_core import db, is_staff, ai_text

COLOR = 0xFF0000
AI_MODEL = "llama-3.1-8b-instant"   # cheap model for support answers

ANSWER_SYSTEM = (
    "You are a helpful Discord server support assistant. Answer the user's "
    "question using the server FAQ when it is relevant. Be concise (max 120 "
    "words), friendly and accurate. If the FAQ does not cover it, say you are "
    "not sure and suggest opening a ticket. Never invent server rules."
)
SUMMARY_SYSTEM = (
    "You are a Discord support analyst. Summarise the conversation transcript "
    "for a staff member: the user's problem, what was already tried, the "
    "current status, and the next action. Max 150 words, plain text."
)

STOP = {
    "the", "and", "for", "you", "your", "with", "this", "that", "are", "was",
    "how", "can", "does", "did", "what", "when", "where", "who", "why", "the",
    "a", "an", "to", "of", "in", "on", "is", "it", "my", "me", "i", "do",
}

QUESTION_HINTS = re.compile(
    r"^(how|what|when|where|who|why|can|could|do|does|is|are|will|would|"
    r"should|help|pls|please)\b", re.IGNORECASE)


def _tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in STOP}


def _looks_like_question(content):
    content = content.strip()
    if len(content) < 12:
        return False
    if content.endswith("?"):
        return True
    return bool(QUESTION_HINTS.match(content))


class AISupport(commands.Cog):
    """FAQ-powered support assistant with an AI fallback."""

    def __init__(self, bot):
        self.bot = bot
        self.db = db()
        self._cooldown = {}
        self._calls = deque()
        self._cache = OrderedDict()
        self._max_per_minute = 12

    @staticmethod
    def help_custom():
        return (ZAI, "AI Support", "FAQ auto-answers + ticket summaries.")

    def embed(self, title, description):
        return discord.Embed(title=title, description=description, color=COLOR)

    # ----------------------------- config -----------------------------
    def cfg(self, guild_id):
        row = self.db.execute(
            "SELECT enabled, channel FROM ai_support WHERE guild_id=?",
            (str(guild_id),)).fetchone()
        if not row:
            return {"enabled": 0, "channel": None}
        return {"enabled": row[0], "channel": row[1]}

    def set_cfg(self, guild_id, **fields):
        self.db.execute("INSERT OR IGNORE INTO ai_support (guild_id) VALUES (?)",
                        (str(guild_id),))
        for key, value in fields.items():
            self.db.execute(
                f"UPDATE ai_support SET {key}=? WHERE guild_id=?",
                (value, str(guild_id)))
        self.db.commit()

    def faq_rows(self, guild_id):
        return self.db.execute(
            "SELECT id, question, answer, keywords FROM ai_faq "
            "WHERE guild_id=? ORDER BY id", (str(guild_id),)).fetchall()

    # ------------------------ local FAQ matching ----------------------
    def match_faq(self, guild_id, content):
        qt = _tokens(content)
        if len(qt) < 2:
            return None
        best, best_score = None, 0
        for _id, question, answer, keywords in self.faq_rows(guild_id):
            kt = _tokens(question) | set(
                (keywords or "").lower().split(","))
            kt.discard("")
            score = len(qt & kt)
            if score > best_score:
                best, best_score = answer, score
        if best and best_score >= 2:
            return best
        return None

    # --------------------------- budgets ------------------------------
    def _allow_call(self):
        cutoff = time.time() - 60
        while self._calls and self._calls[0] < cutoff:
            self._calls.popleft()
        if len(self._calls) >= self._max_per_minute:
            return False
        self._calls.append(time.time())
        return True

    def _cache_get(self, digest):
        entry = self._cache.get(digest)
        if not entry:
            return None
        ts, answer = entry
        if time.time() - ts > 6 * 3600:
            self._cache.pop(digest, None)
            return None
        self._cache.move_to_end(digest)
        return answer

    def _cache_put(self, digest, answer):
        self._cache[digest] = (time.time(), answer)
        self._cache.move_to_end(digest)
        while len(self._cache) > 500:
            self._cache.popitem(last=False)

    # ----------------------------- commands ---------------------------
    @commands.group(name="aisupport", aliases=["supportai", "ahelp"],
                    invoke_without_command=True,
                    help="AI support assistant — FAQ auto-answers and summaries.")
    @commands.guild_only()
    async def aisupport(self, ctx):
        cfg = self.cfg(ctx.guild.id)
        state = f"{ENABLE} Enabled" if cfg["enabled"] else f"{DISABLE} Disabled"
        channel = f"<#{cfg['channel']}>" if cfg["channel"] else "Not set"
        count = len(self.faq_rows(ctx.guild.id))
        p = ctx.clean_prefix
        await ctx.send(embed=self.embed(
            f"{ZAI} AI Support Assistant",
            f"**Status:** {state}\n**Channel:** {channel}\n"
            f"**FAQ entries:** `{count}`\n\n"
            f"`{p}aisupport enable #channel` • `disable`\n"
            f"`{p}aisupport faq add question | answer`\n"
            f"`{p}aisupport faq list` • `faq remove <id>`\n"
            f"`{p}aisupport ask <question>` — test an answer\n"
            f"`{p}aisupport summarize [#channel]` — summarize recent chat"))

    @aisupport.command(name="enable", help="Turn the assistant on in a channel.")
    @commands.has_permissions(manage_guild=True)
    async def enable(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        self.set_cfg(ctx.guild.id, enabled=1, channel=str(channel.id))
        await ctx.send(embed=self.embed(
            f"{TICK} AI Support Enabled",
            f"Questions in {channel.mention} will be answered from the FAQ, "
            f"with an AI fallback."))

    @aisupport.command(name="disable", help="Turn the assistant off.")
    @commands.has_permissions(manage_guild=True)
    async def disable(self, ctx):
        self.set_cfg(ctx.guild.id, enabled=0)
        await ctx.send(embed=self.embed(f"{CROSS} AI Support Disabled",
                                        "Auto answers stopped."))

    @aisupport.group(name="faq", invoke_without_command=True,
                     help="Manage this server's FAQ entries.")
    @commands.guild_only()
    async def faq(self, ctx):
        rows = self.faq_rows(ctx.guild.id)
        if not rows:
            return await ctx.send(embed=self.embed(
                f"{INFO} Empty FAQ",
                f"Add one: `{ctx.clean_prefix}aisupport faq add How do I verify? | "
                f"Go to #verify and click the button.`"))
        body = "\n".join(f"`#{r[0]}` **{r[1][:60]}**" for r in rows[:25])
        await ctx.send(embed=self.embed(f"{PIN} FAQ Entries ({len(rows)})", body))

    @faq.command(name="add", help="Add a FAQ entry: question | answer")
    @commands.has_permissions(manage_guild=True)
    async def faq_add(self, ctx, *, text: str):
        if "|" not in text:
            return await ctx.send(embed=self.embed(
                f"{WARNING} Wrong Format",
                "Use `question | answer`, e.g. `How do I verify? | Click the "
                "button in #verify.`"))
        question, answer = (part.strip() for part in text.split("|", 1))
        if not question or not answer:
            return await ctx.send(embed=self.embed(
                f"{WARNING} Wrong Format", "Both question and answer are required."))
        keywords = ",".join(sorted(_tokens(question))[:12])
        cur = self.db.execute(
            "INSERT INTO ai_faq (guild_id, question, answer, keywords) "
            "VALUES (?,?,?,?)",
            (str(ctx.guild.id), question[:300], answer[:1500], keywords))
        self.db.commit()
        await ctx.send(embed=self.embed(
            f"{TICK} FAQ Added `#{cur.lastrowid}`", f"**{question}**\n{answer[:400]}"))

    @faq.command(name="remove", aliases=["del", "delete"],
                 help="Remove a FAQ entry by id.")
    @commands.has_permissions(manage_guild=True)
    async def faq_remove(self, ctx, entry_id: int):
        cur = self.db.execute("DELETE FROM ai_faq WHERE guild_id=? AND id=?",
                              (str(ctx.guild.id), entry_id))
        self.db.commit()
        if cur.rowcount:
            await ctx.send(embed=self.embed(f"{TICK} FAQ Removed",
                                            f"Entry `#{entry_id}` deleted."))
        else:
            await ctx.send(embed=self.embed(f"{CROSS} Not Found",
                                            f"No FAQ entry with id `{entry_id}`."))

    @aisupport.command(name="ask", help="Test what the assistant would answer.")
    @commands.has_permissions(manage_messages=True)
    async def ask(self, ctx, *, question: str):
        answer = self.match_faq(ctx.guild.id, question)
        source = "FAQ"
        if not answer:
            async with ctx.typing():
                answer = await self._ai_answer(ctx.guild.id, question)
            source = "AI"
        if not answer:
            return await ctx.send(embed=self.embed(
                f"{WARNING} No Answer", "Nothing matched and the AI is unavailable."))
        await ctx.send(embed=self.embed(
            f"{ZAI} Support Answer ({source})", answer))

    @aisupport.command(name="summarize", aliases=["summary"],
                       help="Summarize the recent messages of a channel/ticket.")
    @commands.has_permissions(manage_messages=True)
    async def summarize(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        lines = []
        async for msg in channel.history(limit=60, oldest_first=True):
            if msg.author.bot or not msg.content:
                continue
            lines.append(f"{msg.author.display_name}: {msg.content[:300]}")
        if not lines:
            return await ctx.send(embed=self.embed(
                f"{INFO} Nothing to Summarize", "That channel has no recent text."))
        async with ctx.typing():
            text = await ai_text(
                f"Channel: #{channel.name}\nTranscript:\n" + "\n".join(lines[-60:]),
                SUMMARY_SYSTEM, max_tokens=500)
        await ctx.send(embed=self.embed(f"{ZAI} Ticket Summary — #{channel.name}", text))

    # --------------------------- AI answer ----------------------------
    async def _ai_answer(self, guild_id, question):
        digest = hashlib.sha256(question.lower().encode("utf-8", "ignore")).hexdigest()
        cached = self._cache_get(digest)
        if cached:
            return cached
        if not self._allow_call():
            return None
        faq = self.faq_rows(guild_id)[:20]
        context = "\n".join(f"Q: {q}\nA: {a}" for _i, q, a, _k in faq) or "No FAQ entries."
        answer = await ai_text(
            f"Server FAQ:\n{context}\n\nUser question: {question[:800]}",
            ANSWER_SYSTEM, max_tokens=350, model=AI_MODEL)
        if answer:
            self._cache_put(digest, answer)
        return answer

    # ----------------------------- listener ---------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or not message.content:
            return
        cfg = self.cfg(message.guild.id)
        if not cfg["enabled"] or cfg["channel"] != str(message.channel.id):
            return
        if is_staff(message.author):
            return
        content = message.content.strip()
        if not _looks_like_question(content):
            return

        key = (message.guild.id, message.author.id)
        if time.time() - self._cooldown.get(key, 0) < 20:
            return
        self._cooldown[key] = time.time()

        local = self.match_faq(message.guild.id, content)
        if local:
            answer = local
        else:
            async with message.channel.typing():
                answer = await self._ai_answer(message.guild.id, content)
        if not answer:
            return
        try:
            await message.reply(f"{ZAI} {answer}",
                                mention_author=True,
                                allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(AISupport(bot))
