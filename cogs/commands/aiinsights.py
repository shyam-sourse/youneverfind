# ╔══════════════════════════════════════════════════════════════════╗
# ║   AI Insights  ──  server analytics + weekly AI digest           ║
# ╚══════════════════════════════════════════════════════════════════╝
"""Tracks lightweight server metrics locally (no AI calls) and turns them
into an AI written digest on demand or once a week.

Only two operations ever spend an API call per invocation: ``digest`` and the
weekly auto-post, so this feature is essentially free for the key pool.
"""

from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks

from utils.emoji import ZAI, TICK, CROSS, WARNING, INFO, ENABLE, DISABLE
from utils.ai_staff_core import db, today, ai_text

COLOR = 0xFF0000

INSIGHT_SYSTEM = (
    "You are a Discord community analyst. Given raw server metrics, write a "
    "short weekly digest (max 180 words): headline, 2-3 observations and 2 "
    "concrete recommendations. Plain text, no markdown headers."
)


class AIInsights(commands.Cog):
    """Server activity metrics with an AI weekly digest."""

    def __init__(self, bot):
        self.bot = bot
        self.db = db()
        if not self.weekly_digest.is_running():
            self.weekly_digest.start()

    def cog_unload(self):
        self.weekly_digest.cancel()

    @staticmethod
    def help_custom():
        return (ZAI, "AI Insights", "AI written server analytics digest.")

    def embed(self, title, description):
        return discord.Embed(title=title, description=description, color=COLOR)

    # ----------------------------- metrics ----------------------------
    @staticmethod
    def _since(days):
        return (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    def _totals(self, guild_id, days):
        since = self._since(days)
        total = self.db.execute(
            "SELECT COALESCE(SUM(messages),0) FROM ai_insight_activity "
            "WHERE guild_id=? AND day>=?", (str(guild_id), since)).fetchone()[0]
        active_days = self.db.execute(
            "SELECT COUNT(DISTINCT day) FROM ai_insight_activity "
            "WHERE guild_id=? AND day>=?", (str(guild_id), since)).fetchone()[0]
        joins, leaves = self.db.execute(
            "SELECT COALESCE(SUM(joins),0), COALESCE(SUM(leaves),0) "
            "FROM ai_insight_members WHERE guild_id=? AND day>=?",
            (str(guild_id), since)).fetchone()
        return total, active_days, joins, leaves

    def _top_channels(self, guild_id, days, limit=8):
        return self.db.execute(
            "SELECT channel_id, SUM(messages) FROM ai_insight_activity "
            "WHERE guild_id=? AND day>=? GROUP BY channel_id "
            "ORDER BY SUM(messages) DESC LIMIT ?",
            (str(guild_id), self._since(days), limit)).fetchall()

    async def _digest_text(self, guild, days):
        total, active_days, joins, leaves = self._totals(guild.id, days)
        channels = self._top_channels(guild.id, days)
        lines = []
        for channel_id, messages in channels:
            channel = guild.get_channel(int(channel_id))
            name = channel.mention if channel else f"#{channel_id}"
            lines.append(f"- {name}: {messages} messages")
        metrics = (
            f"Server: {guild.name}\n"
            f"Members: {guild.member_count}\n"
            f"Period: last {days} days\n"
            f"Total messages: {total}\n"
            f"Days with activity: {active_days}\n"
            f"Joins: {joins} • Leaves: {leaves}\n"
            f"Top channels:\n" + ("\n".join(lines) or "- none"))
        return await ai_text(metrics, INSIGHT_SYSTEM, max_tokens=550)

    # ----------------------------- commands ---------------------------
    @commands.group(name="aiinsights", aliases=["serverai", "aiinsight"],
                    invoke_without_command=True,
                    help="AI powered server analytics and weekly digest.")
    @commands.guild_only()
    async def aiinsights(self, ctx):
        total, active_days, joins, leaves = self._totals(ctx.guild.id, 7)
        p = ctx.clean_prefix
        await ctx.send(embed=self.embed(
            f"{ZAI} AI Insights",
            f"**Last 7 days**\n"
            f"Messages `{total}` • Active days `{active_days}`\n"
            f"Joins `{joins}` • Leaves `{leaves}`\n\n"
            f"`{p}aiinsights digest [days]` — AI written report\n"
            f"`{p}aiinsights channels [days]` — busiest channels\n"
            f"`{p}aiinsights growth [days]` — joins / leaves\n"
            f"`{p}aiinsights auto #channel [weekday]` — weekly digest\n"
            f"`{p}aiinsights auto off` • `status`"))

    @aiinsights.command(name="digest", aliases=["report"],
                        help="Generate an AI digest of recent activity.")
    @commands.has_permissions(manage_guild=True)
    async def digest(self, ctx, days: int = 7):
        days = max(1, min(days, 90))
        async with ctx.typing():
            text = await self._digest_text(ctx.guild, days)
        await ctx.send(embed=self.embed(
            f"{ZAI} Server Digest — last {days} days", text))

    @aiinsights.command(name="channels", help="Show the busiest channels.")
    @commands.guild_only()
    async def channels(self, ctx, days: int = 7):
        rows = self._top_channels(ctx.guild.id, max(1, min(days, 90)), 10)
        if not rows:
            return await ctx.send(embed=self.embed(
                f"{INFO} No Data", "No message activity recorded yet."))
        lines = []
        for i, (channel_id, messages) in enumerate(rows, 1):
            channel = ctx.guild.get_channel(int(channel_id))
            name = channel.mention if channel else f"`{channel_id}`"
            lines.append(f"`#{i}` {name} — **{messages}** messages")
        await ctx.send(embed=self.embed(
            f"{ZAI} Busiest Channels ({days}d)", "\n".join(lines)))

    @aiinsights.command(name="growth", help="Show member joins and leaves.")
    @commands.guild_only()
    async def growth(self, ctx, days: int = 7):
        days = max(1, min(days, 90))
        total, active_days, joins, leaves = self._totals(ctx.guild.id, days)
        net = joins - leaves
        await ctx.send(embed=self.embed(
            f"{ZAI} Member Growth ({days}d)",
            f"**Joins:** `{joins}`\n**Leaves:** `{leaves}`\n"
            f"**Net:** `{net:+d}`\n**Current members:** `{ctx.guild.member_count}`"))

    @aiinsights.command(name="auto",
                        help="Post a weekly digest in a channel. Usage: auto #channel [0-6]")
    @commands.has_permissions(manage_guild=True)
    async def auto(self, ctx, target: str, weekday: int = 0):
        if target.lower() in ("off", "disable", "none"):
            self.db.execute(
                "UPDATE ai_insight_cfg SET channel=NULL WHERE guild_id=?",
                (str(ctx.guild.id),))
            self.db.commit()
            return await ctx.send(embed=self.embed(
                f"{CROSS} Auto Digest Off",
                "The weekly digest will no longer be posted automatically."))

        match = discord.utils.get(ctx.guild.text_channels, mention=target) or \
            discord.utils.get(ctx.guild.text_channels, name=target.lstrip("#"))
        if not match:
            return await ctx.send(embed=self.embed(
                f"{WARNING} Channel Not Found",
                "Mention a channel or use its name."))
        weekday = max(0, min(weekday, 6))
        self.db.execute(
            "INSERT OR IGNORE INTO ai_insight_cfg (guild_id) VALUES (?)",
            (str(ctx.guild.id),))
        self.db.execute(
            "UPDATE ai_insight_cfg SET channel=?, weekday=? WHERE guild_id=?",
            (str(match.id), weekday, str(ctx.guild.id)))
        self.db.commit()
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                 "Saturday", "Sunday"]
        await ctx.send(embed=self.embed(
            f"{TICK} Weekly Digest Scheduled",
            f"An AI digest will be posted in {match.mention} every "
            f"**{names[weekday]}**."))

    @aiinsights.command(name="status", help="Show auto-digest configuration.")
    @commands.guild_only()
    async def status(self, ctx):
        row = self.db.execute(
            "SELECT channel, weekday, last_post FROM ai_insight_cfg "
            "WHERE guild_id=?", (str(ctx.guild.id),)).fetchone()
        if not row or not row[0]:
            return await ctx.send(embed=self.embed(
                f"{DISABLE} Auto Digest Off",
                f"Enable it with `{ctx.clean_prefix}aiinsights auto #channel`."))
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                 "Saturday", "Sunday"]
        await ctx.send(embed=self.embed(
            f"{ENABLE} Auto Digest On",
            f"Channel: <#{row[0]}>\nDay: **{names[row[1] or 0]}**\n"
            f"Last posted: `{row[2] or 'never'}`"))

    # --------------------------- weekly task --------------------------
    @tasks.loop(hours=6)
    async def weekly_digest(self):
        await self.bot.wait_until_ready()
        now_utc = datetime.utcnow()
        day = now_utc.strftime("%Y-%m-%d")
        weekday = now_utc.weekday()
        rows = self.db.execute(
            "SELECT guild_id, channel, weekday, last_post FROM ai_insight_cfg "
            "WHERE channel IS NOT NULL").fetchall()
        for guild_id, channel_id, wd, last_post in rows:
            if (wd if wd is not None else 0) != weekday or last_post == day:
                continue
            guild = self.bot.get_guild(int(guild_id))
            channel = guild.get_channel(int(channel_id)) if guild else None
            if not channel:
                continue
            try:
                text = await self._digest_text(guild, 7)
                await channel.send(embed=self.embed(
                    f"{ZAI} Weekly Server Digest", text))
            except Exception:
                continue
            self.db.execute(
                "UPDATE ai_insight_cfg SET last_post=? WHERE guild_id=?",
                (day, guild_id))
            self.db.commit()

    @weekly_digest.before_loop
    async def _before_weekly(self):
        await self.bot.wait_until_ready()

    # ----------------------------- listeners --------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        self.db.execute(
            "INSERT OR IGNORE INTO ai_insight_activity (guild_id, day, channel_id) "
            "VALUES (?,?,?)",
            (str(message.guild.id), today(), str(message.channel.id)))
        self.db.execute(
            "UPDATE ai_insight_activity SET messages=messages+1 "
            "WHERE guild_id=? AND day=? AND channel_id=?",
            (str(message.guild.id), today(), str(message.channel.id)))
        self.db.commit()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if not member.guild:
            return
        self.db.execute(
            "INSERT OR IGNORE INTO ai_insight_members (guild_id, day) VALUES (?,?)",
            (str(member.guild.id), today()))
        self.db.execute(
            "UPDATE ai_insight_members SET joins=joins+1 WHERE guild_id=? AND day=?",
            (str(member.guild.id), today()))
        self.db.commit()

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not member.guild:
            return
        self.db.execute(
            "INSERT OR IGNORE INTO ai_insight_members (guild_id, day) VALUES (?,?)",
            (str(member.guild.id), today()))
        self.db.execute(
            "UPDATE ai_insight_members SET leaves=leaves+1 WHERE guild_id=? AND day=?",
            (str(member.guild.id), today()))
        self.db.commit()


async def setup(bot):
    await bot.add_cog(AIInsights(bot))
