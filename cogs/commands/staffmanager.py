# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░█░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                     ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 CodeX Devs — All Rights Reserved              ║
# ║                                                                  ║
# ║   Staff Manager  ──  staffmanager / shift / task / staffleave     ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

import os
import sqlite3
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from utils.emoji import (MANAGER, KING, ZARROW, TICK, CROSS, INFO, LEVEL_UP,
                         PIN, LOCK, MESSAGE, STAR, ZPEOPLE, ZWRENCH, NEW)

DB_FILE = "db/staffmanager.db"
COLOR = 0xFF0000

ACCOUNT_ACTIONS = ("add", "remove", "promote", "suspend", "hire", "fire", "list")
CONDUCT_ACTIONS = ("warn", "strike", "note", "review", "appreciate", "record")
INFO_ACTIONS = ("profile", "list", "search", "stats")


def _now():
    return datetime.utcnow().isoformat()


def _fmt_duration(seconds: int) -> str:
    seconds = int(max(seconds, 0))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}h {minutes}m {secs}s"


class StaffManager(commands.Cog):
    """Full staff management suite: roster, conduct, shifts, tasks and leaves."""

    def __init__(self, bot):
        self.bot = bot
        os.makedirs("db", exist_ok=True)
        self.db = sqlite3.connect(DB_FILE)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sm_settings (
                guild_id TEXT PRIMARY KEY,
                manager_role TEXT,
                log_channel TEXT
            );
            CREATE TABLE IF NOT EXISTS sm_staff (
                guild_id TEXT, user_id TEXT, rank TEXT, status TEXT,
                hired_at TEXT, PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS sm_conduct (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT,
                user_id TEXT, kind TEXT, detail TEXT, author_id TEXT,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sm_shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT,
                user_id TEXT, started_at TEXT, ended_at TEXT,
                break_started TEXT, break_seconds INTEGER DEFAULT 0,
                total_seconds INTEGER DEFAULT 0, active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS sm_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT,
                assigned_to TEXT, title TEXT, priority TEXT, due_date TEXT,
                progress INTEGER DEFAULT 0, status TEXT DEFAULT 'open',
                created_by TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sm_leaves (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT,
                user_id TEXT, start_date TEXT, end_date TEXT, reason TEXT,
                status TEXT DEFAULT 'pending', reviewer_id TEXT, note TEXT,
                created_at TEXT
            );
        """)
        self.db.commit()

    def cog_unload(self):
        self.db.close()

    @staticmethod
    def help_custom():
        return (MANAGER, "Staff Manager",
                "Roster, conduct, shifts, tasks & leaves.")

    # ----------------------------- helpers -----------------------------
    def setting(self, guild_id, field):
        row = self.db.execute(
            f"SELECT {field} FROM sm_settings WHERE guild_id=?",
            (str(guild_id), )).fetchone()
        return row[0] if row and row[0] else None

    def embed(self, title, description):
        return discord.Embed(title=title, description=description, color=COLOR)

    async def log(self, guild, description):
        channel_id = self.setting(guild.id, "log_channel")
        if not channel_id:
            return
        channel = guild.get_channel(int(channel_id))
        if channel:
            await channel.send(embed=self.embed(f"{MANAGER} Staff Manager Log",
                                                description))

    def is_manager(self, member: discord.Member) -> bool:
        if member.guild_permissions.manage_guild:
            return True
        role_id = self.setting(member.guild.id, "manager_role")
        return bool(role_id and member.get_role(int(role_id)))

    def active_shift(self, guild_id, user_id):
        return self.db.execute(
            "SELECT id, started_at, break_started, break_seconds FROM sm_shifts "
            "WHERE guild_id=? AND user_id=? AND active=1",
            (str(guild_id), str(user_id))).fetchone()

    # --------------------------- staffmanager ---------------------------
    @commands.hybrid_group(name="staffmanager",
                           description="Staff management suite.")
    @commands.guild_only()
    async def staffmanager(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @staffmanager.command(name="setup",
                          description="Configure the Staff Manager role and log channel.")
    @commands.has_permissions(manage_guild=True)
    async def sm_setup(self, ctx, manager_role: discord.Role,
                       log_channel: discord.TextChannel):
        """Configure the Staff Manager role and log channel."""
        self.db.execute(
            """INSERT INTO sm_settings (guild_id, manager_role, log_channel)
               VALUES (?,?,?) ON CONFLICT(guild_id) DO UPDATE SET
               manager_role=excluded.manager_role, log_channel=excluded.log_channel""",
            (str(ctx.guild.id), str(manager_role.id), str(log_channel.id)))
        self.db.commit()
        await ctx.send(embed=self.embed(
            f"{ZWRENCH} Staff Manager Configured",
            f"{ZARROW} **Manager Role:** {manager_role.mention}\n"
            f"{ZARROW} **Log Channel:** {log_channel.mention}"))

    @staffmanager.command(name="account",
                          description="Add, remove, promote, suspend & hire/fire staff.")
    @app_commands.describe(action="add | remove | promote | suspend | hire | fire | list",
                           member="Target staff member.",
                           value="New rank or reason.")
    async def sm_account(self, ctx, action: str, member: discord.Member = None,
                         *, value: str = None):
        """Add, remove, promote, suspend & hire/fire staff."""
        action = action.lower()
        if not self.is_manager(ctx.author):
            return await ctx.send(f"{CROSS} You are not a staff manager.")
        if action not in ACCOUNT_ACTIONS:
            return await ctx.send(
                f"{CROSS} Valid actions: `{', '.join(ACCOUNT_ACTIONS)}`.")

        if action == "list":
            rows = self.db.execute(
                "SELECT user_id, rank, status FROM sm_staff WHERE guild_id=?",
                (str(ctx.guild.id), )).fetchall()
            if not rows:
                return await ctx.send(f"{INFO} No staff members registered.")
            desc = "\n".join(
                f"{ZARROW} <@{r[0]}> — `{r[1] or 'Staff'}` ({r[2] or 'active'})"
                for r in rows[:25])
            return await ctx.send(embed=self.embed(
                f"{ZPEOPLE} Staff Roster ({len(rows)})", desc))

        if not member:
            return await ctx.send(f"{CROSS} You must specify a member.")

        if action in ("add", "hire"):
            self.db.execute(
                """INSERT INTO sm_staff (guild_id, user_id, rank, status, hired_at)
                   VALUES (?,?,?, 'active', ?)
                   ON CONFLICT(guild_id, user_id) DO UPDATE SET
                   status='active', rank=excluded.rank""",
                (str(ctx.guild.id), str(member.id), value or "Trial Staff", _now()))
            text = f"{TICK} {member.mention} has been **hired** as `{value or 'Trial Staff'}`."
        elif action in ("remove", "fire"):
            self.db.execute("DELETE FROM sm_staff WHERE guild_id=? AND user_id=?",
                            (str(ctx.guild.id), str(member.id)))
            text = f"{CROSS} {member.mention} has been **removed** from the staff team."
        elif action == "promote":
            if not value:
                return await ctx.send(f"{CROSS} Provide the new rank.")
            self.db.execute(
                "UPDATE sm_staff SET rank=? WHERE guild_id=? AND user_id=?",
                (value, str(ctx.guild.id), str(member.id)))
            text = f"{LEVEL_UP} {member.mention} has been **promoted** to `{value}`."
        else:  # suspend
            self.db.execute(
                "UPDATE sm_staff SET status='suspended' WHERE guild_id=? AND user_id=?",
                (str(ctx.guild.id), str(member.id)))
            text = f"{LOCK} {member.mention} has been **suspended**. Reason: {value or 'None'}"

        self.db.commit()
        await ctx.send(embed=self.embed(f"{MANAGER} Staff Account", text))
        await self.log(ctx.guild, f"{text}\n{ZARROW} By {ctx.author.mention}")

    @staffmanager.command(name="conduct",
                          description="Warnings, strikes, notes, reviews & appreciation.")
    @app_commands.describe(action="warn | strike | note | review | appreciate | record",
                           member="Target staff member.",
                           detail="Details for the entry.")
    async def sm_conduct(self, ctx, action: str, member: discord.Member,
                         *, detail: str = None):
        """Warnings, strikes, notes, reviews & appreciation."""
        action = action.lower()
        if not self.is_manager(ctx.author):
            return await ctx.send(f"{CROSS} You are not a staff manager.")
        if action not in CONDUCT_ACTIONS:
            return await ctx.send(
                f"{CROSS} Valid actions: `{', '.join(CONDUCT_ACTIONS)}`.")

        if action == "record":
            rows = self.db.execute(
                "SELECT kind, detail, created_at FROM sm_conduct "
                "WHERE guild_id=? AND user_id=? ORDER BY id DESC",
                (str(ctx.guild.id), str(member.id))).fetchall()
            if not rows:
                return await ctx.send(f"{INFO} {member.mention} has a clean record.")
            desc = "\n".join(f"{ZARROW} **{r[0].title()}** — {r[1] or 'No detail'}"
                             for r in rows[:15])
            return await ctx.send(embed=self.embed(
                f"{PIN} Conduct Record — {member.display_name}", desc))

        self.db.execute(
            """INSERT INTO sm_conduct (guild_id, user_id, kind, detail, author_id, created_at)
               VALUES (?,?,?,?,?,?)""",
            (str(ctx.guild.id), str(member.id), action, detail or "No detail",
             str(ctx.author.id), _now()))
        self.db.commit()
        text = (f"{TICK} **{action.title()}** logged for {member.mention}\n"
                f"{ZARROW} Detail: {detail or 'No detail'}")
        await ctx.send(embed=self.embed(f"{MANAGER} Staff Conduct", text))
        await self.log(ctx.guild, f"{text}\n{ZARROW} By {ctx.author.mention}")

    @staffmanager.command(name="info",
                          description="Profiles, lists, search & statistics.")
    @app_commands.describe(action="profile | list | search | stats",
                           query="Member mention/ID or search text.")
    async def sm_info(self, ctx, action: str = "stats", *, query: str = None):
        """Profiles, lists, search & statistics."""
        action = action.lower()
        if action not in INFO_ACTIONS:
            return await ctx.send(
                f"{CROSS} Valid actions: `{', '.join(INFO_ACTIONS)}`.")
        guild_id = str(ctx.guild.id)

        if action == "profile":
            member = ctx.author
            if query:
                member = (await commands.MemberConverter().convert(ctx, query.strip()))
            row = self.db.execute(
                "SELECT rank, status, hired_at FROM sm_staff WHERE guild_id=? AND user_id=?",
                (guild_id, str(member.id))).fetchone()
            if not row:
                return await ctx.send(f"{INFO} {member.mention} is not staff.")
            shifts = self.db.execute(
                "SELECT COUNT(*), COALESCE(SUM(total_seconds),0) FROM sm_shifts "
                "WHERE guild_id=? AND user_id=? AND active=0",
                (guild_id, str(member.id))).fetchone()
            strikes = self.db.execute(
                "SELECT COUNT(*) FROM sm_conduct WHERE guild_id=? AND user_id=? "
                "AND kind IN ('warn','strike')",
                (guild_id, str(member.id))).fetchone()[0]
            embed = self.embed(
                f"{KING} Staff Profile — {member.display_name}",
                f"{ZARROW} **Rank:** `{row[0] or 'Staff'}`\n"
                f"{ZARROW} **Status:** `{row[1] or 'active'}`\n"
                f"{ZARROW} **Hired:** `{(row[2] or '')[:10]}`\n"
                f"{ZARROW} **Shifts:** `{shifts[0]}` • **Time:** `{_fmt_duration(shifts[1])}`\n"
                f"{ZARROW} **Warnings/Strikes:** `{strikes}`")
            embed.set_thumbnail(url=member.display_avatar.url)
            return await ctx.send(embed=embed)

        if action == "list":
            rows = self.db.execute(
                "SELECT user_id, rank FROM sm_staff WHERE guild_id=? ORDER BY rank",
                (guild_id, )).fetchall()
            if not rows:
                return await ctx.send(f"{INFO} No staff members registered.")
            return await ctx.send(embed=self.embed(
                f"{ZPEOPLE} Staff List ({len(rows)})",
                "\n".join(f"{ZARROW} <@{r[0]}> — `{r[1] or 'Staff'}`"
                          for r in rows[:25])))

        if action == "search":
            if not query:
                return await ctx.send(f"{CROSS} Provide a rank or name to search.")
            rows = self.db.execute(
                "SELECT user_id, rank FROM sm_staff WHERE guild_id=? AND rank LIKE ?",
                (guild_id, f"%{query}%")).fetchall()
            if not rows:
                return await ctx.send(f"{INFO} No staff matched `{query}`.")
            return await ctx.send(embed=self.embed(
                f"{MESSAGE} Search Results — `{query}`",
                "\n".join(f"{ZARROW} <@{r[0]}> — `{r[1]}`" for r in rows[:25])))

        total = self.db.execute("SELECT COUNT(*) FROM sm_staff WHERE guild_id=?",
                                (guild_id, )).fetchone()[0]
        on_shift = self.db.execute(
            "SELECT COUNT(*) FROM sm_shifts WHERE guild_id=? AND active=1",
            (guild_id, )).fetchone()[0]
        tasks_open = self.db.execute(
            "SELECT COUNT(*) FROM sm_tasks WHERE guild_id=? AND status='open'",
            (guild_id, )).fetchone()[0]
        leaves = self.db.execute(
            "SELECT COUNT(*) FROM sm_leaves WHERE guild_id=? AND status='pending'",
            (guild_id, )).fetchone()[0]
        await ctx.send(embed=self.embed(
            f"{STAR} Staff Statistics",
            f"{ZARROW} **Total Staff:** `{total}`\n"
            f"{ZARROW} **Currently On Shift:** `{on_shift}`\n"
            f"{ZARROW} **Open Tasks:** `{tasks_open}`\n"
            f"{ZARROW} **Pending Leave Requests:** `{leaves}`"))

    # ------------------------------- shift -------------------------------
    @commands.hybrid_group(name="shift", description="Staff shift tracking.")
    @commands.guild_only()
    async def shift(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @shift.command(name="start", description="Start your shift.")
    async def shift_start(self, ctx):
        """Start your shift."""
        if self.active_shift(ctx.guild.id, ctx.author.id):
            return await ctx.send(f"{CROSS} You already have an active shift.")
        self.db.execute(
            "INSERT INTO sm_shifts (guild_id, user_id, started_at) VALUES (?,?,?)",
            (str(ctx.guild.id), str(ctx.author.id), _now()))
        self.db.commit()
        await ctx.send(embed=self.embed(f"{TICK} Shift Started",
                                        f"{ZARROW} {ctx.author.mention} is now on duty."))
        await self.log(ctx.guild, f"{ctx.author.mention} started a shift.")

    @shift.command(name="break", description="Start a break during your shift.")
    async def shift_break(self, ctx):
        """Start a break during your shift."""
        row = self.active_shift(ctx.guild.id, ctx.author.id)
        if not row:
            return await ctx.send(f"{CROSS} You have no active shift.")
        if row[2]:
            return await ctx.send(f"{CROSS} You are already on a break.")
        self.db.execute("UPDATE sm_shifts SET break_started=? WHERE id=?",
                        (_now(), row[0]))
        self.db.commit()
        await ctx.send(f"{LOCK} {ctx.author.mention} is now on a **break**.")

    @shift.command(name="resume", description="Resume your shift after a break.")
    async def shift_resume(self, ctx):
        """Resume your shift after a break."""
        row = self.active_shift(ctx.guild.id, ctx.author.id)
        if not row or not row[2]:
            return await ctx.send(f"{CROSS} You are not on a break.")
        paused = int((datetime.utcnow() -
                      datetime.fromisoformat(row[2])).total_seconds())
        self.db.execute(
            "UPDATE sm_shifts SET break_started=NULL, break_seconds=? WHERE id=?",
            ((row[3] or 0) + paused, row[0]))
        self.db.commit()
        await ctx.send(f"{TICK} Shift resumed. Break lasted `{_fmt_duration(paused)}`.")

    @shift.command(name="end", description="End your current shift.")
    async def shift_end(self, ctx):
        """End your current shift."""
        row = self.active_shift(ctx.guild.id, ctx.author.id)
        if not row:
            return await ctx.send(f"{CROSS} You have no active shift.")
        breaks = row[3] or 0
        if row[2]:
            breaks += int((datetime.utcnow() -
                           datetime.fromisoformat(row[2])).total_seconds())
        elapsed = int((datetime.utcnow() -
                       datetime.fromisoformat(row[1])).total_seconds())
        worked = max(elapsed - breaks, 0)
        self.db.execute(
            """UPDATE sm_shifts SET active=0, ended_at=?, break_started=NULL,
               break_seconds=?, total_seconds=? WHERE id=?""",
            (_now(), breaks, worked, row[0]))
        self.db.commit()
        await ctx.send(embed=self.embed(
            f"{TICK} Shift Ended",
            f"{ZARROW} **Worked:** `{_fmt_duration(worked)}`\n"
            f"{ZARROW} **Breaks:** `{_fmt_duration(breaks)}`"))
        await self.log(ctx.guild,
                       f"{ctx.author.mention} ended a shift ({_fmt_duration(worked)}).")

    @shift.command(name="timer", description="View your current shift timer.")
    async def shift_timer(self, ctx):
        """View your current shift timer."""
        row = self.active_shift(ctx.guild.id, ctx.author.id)
        if not row:
            return await ctx.send(f"{INFO} You have no active shift.")
        elapsed = int((datetime.utcnow() -
                       datetime.fromisoformat(row[1])).total_seconds())
        state = "On Break" if row[2] else "On Duty"
        await ctx.send(embed=self.embed(
            f"{PIN} Shift Timer",
            f"{ZARROW} **Status:** `{state}`\n"
            f"{ZARROW} **Elapsed:** `{_fmt_duration(elapsed)}`\n"
            f"{ZARROW} **Break Time:** `{_fmt_duration(row[3] or 0)}`"))

    @shift.command(name="stats", description="View your shift statistics.")
    async def shift_stats(self, ctx, member: discord.Member = None):
        """View your shift statistics."""
        member = member or ctx.author
        row = self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(total_seconds),0), COALESCE(SUM(break_seconds),0) "
            "FROM sm_shifts WHERE guild_id=? AND user_id=? AND active=0",
            (str(ctx.guild.id), str(member.id))).fetchone()
        await ctx.send(embed=self.embed(
            f"{STAR} Shift Stats — {member.display_name}",
            f"{ZARROW} **Completed Shifts:** `{row[0]}`\n"
            f"{ZARROW} **Total Duty Time:** `{_fmt_duration(row[1])}`\n"
            f"{ZARROW} **Total Break Time:** `{_fmt_duration(row[2])}`"))

    @shift.command(name="logs", description="View recent shift logs for a staff member.")
    async def shift_logs(self, ctx, member: discord.Member = None):
        """View recent shift logs for a staff member."""
        member = member or ctx.author
        rows = self.db.execute(
            "SELECT started_at, ended_at, total_seconds FROM sm_shifts "
            "WHERE guild_id=? AND user_id=? ORDER BY id DESC",
            (str(ctx.guild.id), str(member.id))).fetchall()
        if not rows:
            return await ctx.send(f"{INFO} No shift logs for {member.mention}.")
        desc = "\n".join(
            f"{ZARROW} `{r[0][:16]}` → `{(r[1] or 'active')[:16]}` "
            f"({_fmt_duration(r[2] or 0)})" for r in rows[:15])
        await ctx.send(embed=self.embed(
            f"{MESSAGE} Shift Logs — {member.display_name}", desc))

    @shift.command(name="leaderboard", description="View the shift leaderboard.")
    async def shift_leaderboard(self, ctx):
        """View the shift leaderboard."""
        rows = self.db.execute(
            "SELECT user_id, SUM(total_seconds) AS t FROM sm_shifts WHERE guild_id=? "
            "AND active=0 GROUP BY user_id ORDER BY t DESC LIMIT 10",
            (str(ctx.guild.id), )).fetchall()
        if not rows:
            return await ctx.send(f"{INFO} No completed shifts yet.")
        medals = ["🥇", "🥈", "🥉"]
        desc = "\n".join(
            f"{medals[i] if i < 3 else ZARROW} <@{r[0]}> — `{_fmt_duration(r[1] or 0)}`"
            for i, r in enumerate(rows))
        await ctx.send(embed=self.embed(f"{LEVEL_UP} Shift Leaderboard {NEW}", desc))

    # ------------------------------- task -------------------------------
    @commands.hybrid_group(name="task", description="Staff task management.")
    @commands.guild_only()
    async def task(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @task.command(name="create", description="Create a new staff task.")
    async def task_create(self, ctx, assigned_to: discord.Member, priority: str,
                          due_date: str, *, title: str):
        """Create a new staff task."""
        if not self.is_manager(ctx.author):
            return await ctx.send(f"{CROSS} You are not a staff manager.")
        cur = self.db.execute(
            """INSERT INTO sm_tasks (guild_id, assigned_to, title, priority,
               due_date, created_by, created_at) VALUES (?,?,?,?,?,?,?)""",
            (str(ctx.guild.id), str(assigned_to.id), title, priority.lower(),
             due_date, str(ctx.author.id), _now()))
        self.db.commit()
        await ctx.send(embed=self.embed(
            f"{TICK} Task Created `#{cur.lastrowid}`",
            f"{ZARROW} **Title:** {title}\n"
            f"{ZARROW} **Assigned To:** {assigned_to.mention}\n"
            f"{ZARROW} **Priority:** `{priority}`\n"
            f"{ZARROW} **Due:** `{due_date}`"))

    @task.command(name="assign",
                  description="Reassign an existing task to another staff member.")
    async def task_assign(self, ctx, task_id: int, member: discord.Member):
        """Reassign an existing task to another staff member."""
        if not self.is_manager(ctx.author):
            return await ctx.send(f"{CROSS} You are not a staff manager.")
        self.db.execute(
            "UPDATE sm_tasks SET assigned_to=? WHERE guild_id=? AND id=?",
            (str(member.id), str(ctx.guild.id), task_id))
        self.db.commit()
        await ctx.send(f"{TICK} Task `#{task_id}` reassigned to {member.mention}.")

    @task.command(name="complete", description="Mark a task as completed.")
    async def task_complete(self, ctx, task_id: int):
        """Mark a task as completed."""
        self.db.execute(
            "UPDATE sm_tasks SET status='completed', progress=100 WHERE guild_id=? AND id=?",
            (str(ctx.guild.id), task_id))
        self.db.commit()
        await ctx.send(f"{TICK} Task `#{task_id}` marked as **completed**.")

    @task.command(name="delete", description="Delete a task.")
    async def task_delete(self, ctx, task_id: int):
        """Delete a task."""
        if not self.is_manager(ctx.author):
            return await ctx.send(f"{CROSS} You are not a staff manager.")
        self.db.execute("DELETE FROM sm_tasks WHERE guild_id=? AND id=?",
                        (str(ctx.guild.id), task_id))
        self.db.commit()
        await ctx.send(f"{CROSS} Task `#{task_id}` deleted.")

    @task.command(name="progress",
                  description="Update the progress percentage of a task.")
    async def task_progress(self, ctx, task_id: int, percent: int):
        """Update the progress percentage of a task."""
        percent = max(0, min(100, percent))
        self.db.execute(
            "UPDATE sm_tasks SET progress=?, status=? WHERE guild_id=? AND id=?",
            (percent, "completed" if percent == 100 else "open",
             str(ctx.guild.id), task_id))
        self.db.commit()
        bar = "█" * (percent // 10) + "░" * (10 - percent // 10)
        await ctx.send(embed=self.embed(f"{LEVEL_UP} Task `#{task_id}` Progress",
                                        f"{ZARROW} `{bar}` **{percent}%**"))

    @task.command(name="list",
                  description="List your assigned tasks (or all tasks for managers).")
    async def task_list(self, ctx, member: discord.Member = None):
        """List your assigned tasks (or all tasks for managers)."""
        if member and not self.is_manager(ctx.author):
            return await ctx.send(f"{CROSS} You are not a staff manager.")
        target = member or ctx.author
        rows = self.db.execute(
            "SELECT id, title, priority, progress, status, due_date FROM sm_tasks "
            "WHERE guild_id=? AND assigned_to=? ORDER BY id DESC",
            (str(ctx.guild.id), str(target.id))).fetchall()
        if not rows:
            return await ctx.send(f"{INFO} No tasks found for {target.mention}.")
        desc = "\n".join(
            f"{ZARROW} `#{r[0]}` **{r[1]}** — `{r[2]}` • `{r[3]}%` • `{r[4]}` • due `{r[5]}`"
            for r in rows[:15])
        await ctx.send(embed=self.embed(
            f"{PIN} Tasks — {target.display_name}", desc))

    # ----------------------------- staffleave -----------------------------
    @commands.hybrid_group(name="staffleave", description="Staff leave management.")
    @commands.guild_only()
    async def staffleave(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @staffleave.command(name="request", description="Request a leave of absence.")
    async def leave_request(self, ctx, start_date: str, end_date: str, *,
                            reason: str):
        """Request a leave of absence."""
        cur = self.db.execute(
            """INSERT INTO sm_leaves (guild_id, user_id, start_date, end_date,
               reason, created_at) VALUES (?,?,?,?,?,?)""",
            (str(ctx.guild.id), str(ctx.author.id), start_date, end_date,
             reason, _now()))
        self.db.commit()
        await ctx.send(embed=self.embed(
            f"{MESSAGE} Leave Request `#{cur.lastrowid}`",
            f"{ZARROW} **From:** `{start_date}` **To:** `{end_date}`\n"
            f"{ZARROW} **Reason:** {reason}\n"
            f"{ZARROW} **Status:** `pending`"))
        await self.log(ctx.guild,
                       f"{ctx.author.mention} requested leave `#{cur.lastrowid}`.")

    @staffleave.command(name="approve", description="Approve a pending leave request.")
    async def leave_approve(self, ctx, leave_id: int):
        """Approve a pending leave request."""
        if not self.is_manager(ctx.author):
            return await ctx.send(f"{CROSS} You are not a staff manager.")
        self.db.execute(
            "UPDATE sm_leaves SET status='approved', reviewer_id=? WHERE guild_id=? AND id=?",
            (str(ctx.author.id), str(ctx.guild.id), leave_id))
        self.db.commit()
        await ctx.send(f"{TICK} Leave `#{leave_id}` **approved**.")

    @staffleave.command(name="deny", description="Deny a pending leave request.")
    async def leave_deny(self, ctx, leave_id: int, *, reason: str = None):
        """Deny a pending leave request."""
        if not self.is_manager(ctx.author):
            return await ctx.send(f"{CROSS} You are not a staff manager.")
        self.db.execute(
            "UPDATE sm_leaves SET status='denied', reviewer_id=?, note=? "
            "WHERE guild_id=? AND id=?",
            (str(ctx.author.id), reason or "No reason", str(ctx.guild.id), leave_id))
        self.db.commit()
        await ctx.send(f"{CROSS} Leave `#{leave_id}` **denied** — {reason or 'No reason'}.")

    @staffleave.command(name="end", description="End an active approved leave early.")
    async def leave_end(self, ctx, leave_id: int):
        """End an active approved leave early."""
        self.db.execute(
            "UPDATE sm_leaves SET status='ended', end_date=? WHERE guild_id=? AND id=?",
            (datetime.utcnow().strftime("%Y-%m-%d"), str(ctx.guild.id), leave_id))
        self.db.commit()
        await ctx.send(f"{TICK} Leave `#{leave_id}` has been **ended**.")

    @staffleave.command(name="history", description="View leave history for a staff member.")
    async def leave_history(self, ctx, member: discord.Member = None):
        """View leave history for a staff member."""
        member = member or ctx.author
        rows = self.db.execute(
            "SELECT id, start_date, end_date, status, reason FROM sm_leaves "
            "WHERE guild_id=? AND user_id=? ORDER BY id DESC",
            (str(ctx.guild.id), str(member.id))).fetchall()
        if not rows:
            return await ctx.send(f"{INFO} No leave history for {member.mention}.")
        desc = "\n".join(
            f"{ZARROW} `#{r[0]}` `{r[1]}` → `{r[2]}` — **{r[3]}** ({r[4]})"
            for r in rows[:15])
        await ctx.send(embed=self.embed(
            f"{MESSAGE} Leave History — {member.display_name}", desc))


async def setup(bot):
    await bot.add_cog(StaffManager(bot))
