# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░█░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                     ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 CodeX Devs — All Rights Reserved              ║
# ║                                                                  ║
# ║   discord  ──  https://discord.gg/34thSTQ2Sp                      ║
# ║   youtube  ──  https://youtube.com/@CodeXDevs                   ║
# ║   github   ──  https://github.com/RayExo                        ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝


import os
import time
import sqlite3
import datetime
import discord
from discord.ext import commands, tasks

from utils.cv2 import CV2
from utils.emoji import (
    ARROWRED,
    BLACKCROWN,
    CHANNEL,
    CROSS,
    MESSAGE,
    REDDOT,
    STAR,
    TICK,
    TIMER,
    ZPEOPLE,
)

PERIODS = {
    "daily": ("Daily", "day"),
    "day": ("Daily", "day"),
    "d": ("Daily", "day"),
    "weekly": ("Weekly", "week"),
    "weakly": ("Weekly", "week"),
    "week": ("Weekly", "week"),
    "w": ("Weekly", "week"),
    "monthly": ("Monthly", "month"),
    "month": ("Monthly", "month"),
    "m": ("Monthly", "month"),
    "lifetime": ("Lifetime", "life"),
    "all": ("Lifetime", "life"),
    "alltime": ("Lifetime", "life"),
    "total": ("Lifetime", "life"),
    "l": ("Lifetime", "life"),
}

NO_PINGS = discord.AllowedMentions.none()

RANK_EMOJIS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def period_key(kind, now=None):
    now = now or datetime.datetime.utcnow()
    if kind == "day":
        return now.strftime("%Y-%m-%d")
    if kind == "week":
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"
    if kind == "month":
        return now.strftime("%Y-%m")
    return "lifetime"


def next_reset_text(kind, now=None):
    now = now or datetime.datetime.utcnow()
    if kind == "life":
        return "never"
    if kind == "day":
        nxt = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif kind == "week":
        nxt = (now + datetime.timedelta(days=7 - now.isoweekday() + 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        if now.month == 12:
            nxt = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            nxt = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    delta = nxt - now
    hours = int(delta.total_seconds() // 3600)
    if hours >= 24:
        return f"in {hours // 24}d {hours % 24}h"
    if hours >= 1:
        return f"in {hours} hours"
    return f"in {int(delta.total_seconds() // 60)} minutes"


def fmt_duration(seconds):
    seconds = int(seconds or 0)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


class Leaderboard(commands.Cog):
    """Message + voice leaderboards — per channel, whole server, with a top-1 role."""

    def __init__(self, bot):
        self.bot = bot
        os.makedirs("db", exist_ok=True)
        self.db = sqlite3.connect("db/messages.db", check_same_thread=False)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS message_stats (
                guild_id TEXT,
                channel_id TEXT,
                user_id TEXT,
                period TEXT,
                period_key TEXT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, channel_id, user_id, period, period_key)
            )"""
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_lb ON message_stats (guild_id, channel_id, period, period_key)"
        )
        # ---- voice time (seconds) ----
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS voice_stats (
                guild_id TEXT,
                channel_id TEXT,
                user_id TEXT,
                period TEXT,
                period_key TEXT,
                seconds INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, channel_id, user_id, period, period_key)
            )"""
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_vc ON voice_stats (guild_id, channel_id, period, period_key)"
        )
        # ---- top-1 role config ----
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS lb_top_role (
                guild_id TEXT,
                board TEXT,
                role_id TEXT,
                period TEXT,
                PRIMARY KEY (guild_id, board)
            )"""
        )
        self.db.commit()

        # user_id -> (guild_id, channel_id, last_tick_timestamp)
        self.voice_sessions = {}
        self.flush_voice.start()
        self.update_top_roles.start()

    def cog_unload(self):
        try:
            self.flush_voice.cancel()
            self.update_top_roles.cancel()
        except Exception:
            pass
        try:
            self.db.close()
        except Exception:
            pass

    # ---------------- message tracking ----------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        gid = str(message.guild.id)
        cid = str(message.channel.id)
        uid = str(message.author.id)
        rows = []
        for period in ("day", "week", "month", "life"):
            key = period_key(period)
            rows.append((gid, cid, uid, period, key))
            rows.append((gid, "server", uid, period, key))
        try:
            self.db.executemany(
                """INSERT INTO message_stats (guild_id, channel_id, user_id, period, period_key, count)
                   VALUES (?, ?, ?, ?, ?, 1)
                   ON CONFLICT(guild_id, channel_id, user_id, period, period_key)
                   DO UPDATE SET count = count + 1""",
                rows,
            )
            self.db.commit()
        except Exception:
            pass

    # ---------------- voice tracking ----------------

    def _countable(self, member, state):
        if member.bot or state.channel is None:
            return False
        if member.guild.afk_channel and state.channel.id == member.guild.afk_channel.id:
            return False
        return True

    def add_voice_seconds(self, guild_id, channel_id, user_id, seconds):
        seconds = int(seconds)
        if seconds <= 0:
            return
        rows = []
        for period in ("day", "week", "month", "life"):
            key = period_key(period)
            rows.append((str(guild_id), str(channel_id), str(user_id), period, key, seconds))
            rows.append((str(guild_id), "server", str(user_id), period, key, seconds))
        try:
            self.db.executemany(
                """INSERT INTO voice_stats (guild_id, channel_id, user_id, period, period_key, seconds)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(guild_id, channel_id, user_id, period, period_key)
                   DO UPDATE SET seconds = seconds + excluded.seconds""",
                rows,
            )
            self.db.commit()
        except Exception:
            pass

    def _close_session(self, user_id):
        data = self.voice_sessions.pop(user_id, None)
        if not data:
            return
        gid, cid, since = data
        self.add_voice_seconds(gid, cid, user_id, time.time() - since)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        left = before.channel is not None
        joined = self._countable(member, after)
        if left:
            self._close_session(member.id)
        if joined:
            self.voice_sessions[member.id] = (member.guild.id, after.channel.id, time.time())

    @tasks.loop(minutes=1)
    async def flush_voice(self):
        """Persist ongoing voice time every minute so live sessions show up."""
        now = time.time()
        for uid, (gid, cid, since) in list(self.voice_sessions.items()):
            elapsed = now - since
            if elapsed >= 1:
                self.add_voice_seconds(gid, cid, uid, elapsed)
                self.voice_sessions[uid] = (gid, cid, now)

    @flush_voice.before_loop
    async def _before_flush(self):
        await self.bot.wait_until_ready()
        # pick up members already sitting in voice after a restart
        now = time.time()
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                for member in channel.members:
                    if member.bot:
                        continue
                    if guild.afk_channel and channel.id == guild.afk_channel.id:
                        continue
                    self.voice_sessions[member.id] = (guild.id, channel.id, now)

    # ---------------- queries ----------------

    def top(self, guild_id, scope, period, limit=10):
        cur = self.db.execute(
            """SELECT user_id, count FROM message_stats
               WHERE guild_id = ? AND channel_id = ? AND period = ? AND period_key = ?
               ORDER BY count DESC LIMIT ?""",
            (str(guild_id), scope, period, period_key(period), limit),
        )
        return cur.fetchall()

    def top_voice(self, guild_id, scope, period, limit=10):
        cur = self.db.execute(
            """SELECT user_id, seconds FROM voice_stats
               WHERE guild_id = ? AND channel_id = ? AND period = ? AND period_key = ?
               ORDER BY seconds DESC LIMIT ?""",
            (str(guild_id), scope, period, period_key(period), limit),
        )
        return cur.fetchall()

    def user_total(self, guild_id, scope, period, user_id):
        cur = self.db.execute(
            """SELECT count FROM message_stats
               WHERE guild_id = ? AND channel_id = ? AND period = ? AND period_key = ? AND user_id = ?""",
            (str(guild_id), scope, period, period_key(period), str(user_id)),
        )
        row = cur.fetchone()
        return row[0] if row else 0

    def user_voice_total(self, guild_id, scope, period, user_id):
        cur = self.db.execute(
            """SELECT seconds FROM voice_stats
               WHERE guild_id = ? AND channel_id = ? AND period = ? AND period_key = ? AND user_id = ?""",
            (str(guild_id), scope, period, period_key(period), str(user_id)),
        )
        row = cur.fetchone()
        return row[0] if row else 0

    # ---------------- top-1 role ----------------

    def get_top_role_config(self, guild_id, board=None):
        if board:
            cur = self.db.execute(
                "SELECT board, role_id, period FROM lb_top_role WHERE guild_id = ? AND board = ?",
                (str(guild_id), board),
            )
        else:
            cur = self.db.execute(
                "SELECT board, role_id, period FROM lb_top_role WHERE guild_id = ?",
                (str(guild_id),),
            )
        return cur.fetchall()

    def set_top_role_config(self, guild_id, board, role_id, period):
        self.db.execute(
            """INSERT INTO lb_top_role (guild_id, board, role_id, period)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id, board) DO UPDATE SET role_id = excluded.role_id, period = excluded.period""",
            (str(guild_id), board, str(role_id), period),
        )
        self.db.commit()

    def clear_top_role_config(self, guild_id, board):
        self.db.execute(
            "DELETE FROM lb_top_role WHERE guild_id = ? AND board = ?", (str(guild_id), board)
        )
        self.db.commit()

    async def sync_top_role(self, guild, board, role, period):
        """Give the role to rank #1 and take it off everyone else."""
        if role is None or not guild.me.guild_permissions.manage_roles:
            return None
        if role >= guild.me.top_role:
            return None
        rows = self.top_voice(guild.id, "server", period, 1) if board == "vc" else self.top(guild.id, "server", period, 1)
        winner = guild.get_member(int(rows[0][0])) if rows else None
        for member in list(role.members):
            if winner is None or member.id != winner.id:
                try:
                    await member.remove_roles(role, reason="Leaderboard top-1 changed")
                except Exception:
                    pass
        if winner and role not in winner.roles:
            try:
                await winner.add_roles(role, reason="Leaderboard rank #1")
            except Exception:
                pass
        return winner

    @tasks.loop(minutes=5)
    async def update_top_roles(self):
        for guild in self.bot.guilds:
            for board, role_id, period in self.get_top_role_config(guild.id):
                role = guild.get_role(int(role_id))
                if role is None:
                    continue
                try:
                    await self.sync_top_role(guild, board, role, period)
                except Exception:
                    pass

    @update_top_roles.before_loop
    async def _before_roles(self):
        await self.bot.wait_until_ready()

    # ---------------- rendering ----------------

    async def send_board(self, ctx, scope, period, label, title_place):
        rows = self.top(ctx.guild.id, scope, period)
        if not rows:
            return await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
                f"{MESSAGE} {label} Message Leaderboard",
                f"{CROSS} No messages tracked yet for **{title_place}**.\n"
                f"{ARROWRED} Start chatting — tracking begins from now on."
            ))

        top_id = rows[0][0]
        rankings = []
        for i, (uid, count) in enumerate(rows):
            emoji = RANK_EMOJIS[i] if i < len(RANK_EMOJIS) else f"`{i + 1}.`"
            member = ctx.guild.get_member(int(uid))
            name = member.mention if member else f"<@{uid}>"
            rankings.append(f"{emoji} {name} `|` **{count:,}** messages")

        me = self.user_total(ctx.guild.id, scope, period, ctx.author.id)

        await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
            f"{MESSAGE} {title_place} — {label} Message Leaderboard",
            f"{BLACKCROWN} **Top Active User** `»` <@{top_id}>",
            "**Rankings:**\n" + "\n".join(rankings),
            f"{STAR} **Your Messages:** `{me:,}`\n"
            f"{TIMER} **Next Reset:** {next_reset_text(period)}\n"
            f"{REDDOT} Updates in realtime `|` {label} stats"
        ))

    async def send_voice_board(self, ctx, scope, period, label, title_place):
        rows = self.top_voice(ctx.guild.id, scope, period)
        if not rows:
            return await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
                f"{TIMER} {label} Voice Leaderboard",
                f"{CROSS} No voice time tracked yet for **{title_place}**.\n"
                f"{ARROWRED} Hop into a voice channel — tracking begins from now on."
            ))

        top_id = rows[0][0]
        rankings = []
        for i, (uid, secs) in enumerate(rows):
            emoji = RANK_EMOJIS[i] if i < len(RANK_EMOJIS) else f"`{i + 1}.`"
            member = ctx.guild.get_member(int(uid))
            name = member.mention if member else f"<@{uid}>"
            rankings.append(f"{emoji} {name} `|` **{fmt_duration(secs)}**")

        me = self.user_voice_total(ctx.guild.id, scope, period, ctx.author.id)

        await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
            f"{TIMER} {title_place} — {label} Voice Leaderboard",
            f"{BLACKCROWN} **Top Voice User** `»` <@{top_id}>",
            "**Rankings:**\n" + "\n".join(rankings),
            f"{STAR} **Your Voice Time:** `{fmt_duration(me)}`\n"
            f"{TIMER} **Next Reset:** {next_reset_text(period)}\n"
            f"{REDDOT} Updates every minute `|` {label} stats"
        ))

    async def help_board(self, ctx):
        await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
            f"{MESSAGE} Leaderboard",
            "Track who talks the most — messages and voice time, per channel and server wide.\n\n"
            f"{ARROWRED} **lb daily / weekly / monthly / lifetime** `»` Message leaderboard of this channel\n"
            f"{CHANNEL} **lb daily #channel** `»` Message leaderboard of another channel\n"
            f"{ZPEOPLE} **lb server daily/weekly/monthly/lifetime** `»` Whole server message leaderboard\n"
            f"{STAR} **lb me** `»` Your own message stats",
            f"{TIMER} **Voice Time**\n"
            f"{ARROWRED} **lb vc daily / weekly / monthly / lifetime** `»` Server voice time leaderboard\n"
            f"{CHANNEL} **lb vc channel #voice daily** `»` Voice leaderboard of one voice channel\n"
            f"{STAR} **lb vc me** `»` Your own voice time stats",
            f"{BLACKCROWN} **Top #1 Role** `(admin)`\n"
            f"{ARROWRED} **lb role set @role messages daily** `»` Auto give role to #1 chatter\n"
            f"{ARROWRED} **lb role set @role vc weekly** `»` Auto give role to #1 voice user\n"
            f"{ARROWRED} **lb role show / lb role remove messages|vc** `»` View or disable\n"
            f"{REDDOT} The role moves automatically — the old #1 loses it."
        ))

    # ---------------- commands ----------------

    @commands.group(name="leaderboard", aliases=["lb"], invoke_without_command=True)
    @commands.guild_only()
    async def leaderboard(self, ctx, period: str = None, channel: discord.TextChannel = None):
        if period is None:
            return await self.help_board(ctx)
        key = period.lower()
        if key not in PERIODS:
            return await self.help_board(ctx)
        label, kind = PERIODS[key]
        target = channel or ctx.channel
        await self.send_board(ctx, str(target.id), kind, label, f"#{target.name}")

    @leaderboard.command(name="server", aliases=["guild", "all"])
    @commands.guild_only()
    async def lb_server(self, ctx, period: str = "daily"):
        key = period.lower()
        if key not in PERIODS:
            key = "daily"
        label, kind = PERIODS[key]
        await self.send_board(ctx, "server", kind, label, ctx.guild.name)

    @leaderboard.command(name="channel")
    @commands.guild_only()
    async def lb_channel(self, ctx, channel: discord.TextChannel = None, period: str = "daily"):
        key = period.lower()
        if key not in PERIODS:
            key = "daily"
        label, kind = PERIODS[key]
        target = channel or ctx.channel
        await self.send_board(ctx, str(target.id), kind, label, f"#{target.name}")

    # ---------------- voice commands ----------------

    @leaderboard.group(name="vc", aliases=["voice", "vctime"], invoke_without_command=True)
    @commands.guild_only()
    async def lb_vc(self, ctx, period: str = "daily"):
        key = period.lower()
        if key not in PERIODS:
            key = "daily"
        label, kind = PERIODS[key]
        await self.send_voice_board(ctx, "server", kind, label, ctx.guild.name)

    @lb_vc.command(name="channel")
    @commands.guild_only()
    async def lb_vc_channel(self, ctx, channel: discord.VoiceChannel = None, period: str = "daily"):
        if channel is None:
            if ctx.author.voice and ctx.author.voice.channel:
                channel = ctx.author.voice.channel
            else:
                return await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
                    f"{TIMER} Voice Leaderboard",
                    f"{CROSS} Mention a voice channel or join one first."
                ))
        key = period.lower()
        if key not in PERIODS:
            key = "daily"
        label, kind = PERIODS[key]
        await self.send_voice_board(ctx, str(channel.id), kind, label, f"🔊 {channel.name}")

    @lb_vc.command(name="me", aliases=["stats", "my"])
    @commands.guild_only()
    async def lb_vc_me(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        lines = []
        for kind, label in (("day", "Daily"), ("week", "Weekly"), ("month", "Monthly"), ("life", "Lifetime")):
            sv = self.user_voice_total(ctx.guild.id, "server", kind, member.id)
            lines.append(f"{ARROWRED} **{label}** `»` **{fmt_duration(sv)}**")
        await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
            f"{TIMER} Voice Stats — {member.display_name}",
            "\n".join(lines),
            f"{REDDOT} Live sessions are saved every minute."
        ))

    @lb_vc.command(name="reset")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def lb_vc_reset(self, ctx):
        self.db.execute("DELETE FROM voice_stats WHERE guild_id = ?", (str(ctx.guild.id),))
        self.db.commit()
        await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
            f"{TIMER} Voice Leaderboard Reset",
            f"{TICK} Voice time data cleared for **{ctx.guild.name}**."
        ))

    # ---------------- top-1 role commands ----------------

    @leaderboard.group(name="role", aliases=["toprole"], invoke_without_command=True)
    @commands.guild_only()
    async def lb_role(self, ctx):
        await self.lb_role_show(ctx)

    @lb_role.command(name="set")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def lb_role_set(self, ctx, role: discord.Role, board: str = "messages", period: str = "daily"):
        board = "vc" if board.lower() in ("vc", "voice", "vctime") else "messages"
        key = period.lower()
        if key not in PERIODS:
            key = "daily"
        label, kind = PERIODS[key]

        if role >= ctx.guild.me.top_role:
            return await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
                f"{BLACKCROWN} Top #1 Role",
                f"{CROSS} {role.mention} is above my highest role — move my role higher first."
            ))
        if not ctx.guild.me.guild_permissions.manage_roles:
            return await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
                f"{BLACKCROWN} Top #1 Role",
                f"{CROSS} I need the **Manage Roles** permission."
            ))

        self.set_top_role_config(ctx.guild.id, board, role.id, kind)
        winner = await self.sync_top_role(ctx.guild, board, role, kind)
        board_name = "Voice Time" if board == "vc" else "Messages"
        await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
            f"{BLACKCROWN} Top #1 Role",
            f"{TICK} {role.mention} will be given to the **#1 {board_name}** user `({label})`.",
            f"{STAR} **Current #1** `»` " + (winner.mention if winner else "`nobody yet`") + "\n"
            f"{TIMER} **Re-checked** every 5 minutes\n"
            f"{REDDOT} The previous holder automatically loses the role."
        ))

    @lb_role.command(name="remove", aliases=["unset", "disable"])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def lb_role_remove(self, ctx, board: str = "messages"):
        board = "vc" if board.lower() in ("vc", "voice", "vctime") else "messages"
        self.clear_top_role_config(ctx.guild.id, board)
        await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
            f"{BLACKCROWN} Top #1 Role",
            f"{TICK} Top #1 role disabled for **{'Voice Time' if board == 'vc' else 'Messages'}**."
        ))

    @lb_role.command(name="show", aliases=["config", "status"])
    @commands.guild_only()
    async def lb_role_show(self, ctx):
        rows = self.get_top_role_config(ctx.guild.id)
        if not rows:
            return await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
                f"{BLACKCROWN} Top #1 Role",
                f"{CROSS} No top #1 role configured.\n"
                f"{ARROWRED} `lb role set @role messages daily`\n"
                f"{ARROWRED} `lb role set @role vc weekly`"
            ))
        lines = []
        for board, role_id, period in rows:
            role = ctx.guild.get_role(int(role_id))
            label = next((l for l, k in PERIODS.values() if k == period), "Daily")
            lines.append(
                f"{ARROWRED} **{'Voice Time' if board == 'vc' else 'Messages'}** `({label})` `»` "
                + (role.mention if role else "`deleted role`")
            )
        await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
            f"{BLACKCROWN} Top #1 Role",
            "\n".join(lines),
            f"{TIMER} Re-checked every 5 minutes."
        ))

    # ---------------- misc ----------------

    @leaderboard.command(name="me", aliases=["stats", "my"])
    @commands.guild_only()
    async def lb_me(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        cid = str(ctx.channel.id)
        lines = []
        for kind, label in (("day", "Daily"), ("week", "Weekly"), ("month", "Monthly"), ("life", "Lifetime")):
            ch = self.user_total(ctx.guild.id, cid, kind, member.id)
            sv = self.user_total(ctx.guild.id, "server", kind, member.id)
            lines.append(f"{ARROWRED} **{label}** `»` `#{ctx.channel.name}`: **{ch:,}** `|` Server: **{sv:,}**")
        vc_lines = []
        for kind, label in (("day", "Daily"), ("week", "Weekly"), ("month", "Monthly"), ("life", "Lifetime")):
            sv = self.user_voice_total(ctx.guild.id, "server", kind, member.id)
            vc_lines.append(f"{ARROWRED} **{label}** `»` **{fmt_duration(sv)}**")
        await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
            f"{MESSAGE} Stats — {member.display_name}",
            "**Messages**\n" + "\n".join(lines),
            f"{TIMER} **Voice Time**\n" + "\n".join(vc_lines),
            f"{REDDOT} Channel stats are for `#{ctx.channel.name}`"
        ))

    @leaderboard.command(name="reset")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def lb_reset(self, ctx, scope: str = "channel"):
        scope = scope.lower()
        if scope in ("server", "guild", "all"):
            self.db.execute("DELETE FROM message_stats WHERE guild_id = ?", (str(ctx.guild.id),))
            self.db.execute("DELETE FROM voice_stats WHERE guild_id = ?", (str(ctx.guild.id),))
            place = f"**{ctx.guild.name}** (messages + voice)"
        else:
            self.db.execute(
                "DELETE FROM message_stats WHERE guild_id = ? AND channel_id = ?",
                (str(ctx.guild.id), str(ctx.channel.id)),
            )
            place = f"`#{ctx.channel.name}`"
        self.db.commit()
        await ctx.send(allowed_mentions=NO_PINGS, view=CV2(
            f"{MESSAGE} Leaderboard Reset",
            f"{ARROWRED} Leaderboard data cleared for {place}."
        ))


async def setup(bot):
    await bot.add_cog(Leaderboard(bot))
