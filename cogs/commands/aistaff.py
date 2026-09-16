# ╔══════════════════════════════════════════════════════════════════╗
# ║   AI Staff  ──  activity tracking, reviews, coaching, insights   ║
# ╚══════════════════════════════════════════════════════════════════╝

import discord
from discord.ext import commands

from utils.emoji import (ZAI, TICK, CROSS, WARNING, INFO, STAR, TIME, KING,
                         MANAGER, LEVEL_UP, MESSAGE)
from utils.ai_staff_core import (db, now, today, days_ago, bump, is_staff,
                                 activity_totals, activity_board, ai_json,
                                 ai_text, COLOR)

REPORT_SYSTEM = (
    "You are a Discord staff-team analyst. Write a short performance review of "
    "one staff member from their raw activity numbers. Be concrete, mention "
    "strengths, weaknesses and one improvement. Max 130 words. No markdown "
    "headers."
)
COACH_SYSTEM = (
    "You are a friendly senior Discord moderator coaching a junior staff "
    "member. Give 4 short, actionable bullet tips tailored to their stats."
)
SUGGEST_SYSTEM = (
    "You are a Discord moderation advisor. Given an incident, recommend the "
    "fairest action. Return JSON: {\"action\":\"warn|mute|timeout|kick|ban|none\","
    "\"duration\":\"e.g. 1h or n/a\",\"reason\":\"short reason\","
    "\"explanation\":\"2 sentences\"}"
)
SUMMARY_SYSTEM = (
    "You are a Discord staff-team analyst. Summarise the whole staff team's "
    "week from the numbers: who carried the team, who is slipping, and two "
    "recommendations. Max 160 words."
)
HIRE_SYSTEM = (
    "You are a Discord staff recruiter. Evaluate a staff applicant. Return "
    "JSON: {\"score\":0-100,\"recommendation\":\"hire|maybe|reject\","
    "\"strengths\":\"...\",\"concerns\":\"...\",\"questions\":\"two interview "
    "questions\"}"
)


class AIStaff(commands.Cog):
    """AI staff activity tracking, reviews, coaching and moderation advice."""

    def __init__(self, bot):
        self.bot = bot
        self.db = db()

    @staticmethod
    def help_custom():
        return (MANAGER, "AI Staff", "AI staff activity, reviews & insights.")

    def embed(self, title, description):
        return discord.Embed(title=title, description=description, color=COLOR)

    # ----------------------------- tracking ---------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        if is_staff(message.author):
            bump(message.guild.id, message.author.id, "messages")

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        if ctx.guild and is_staff(ctx.author):
            bump(ctx.guild.id, ctx.author.id, "commands")

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry):
        try:
            user = entry.user
            if user and entry.guild and not user.bot:
                action = str(entry.action)
                if any(k in action for k in ("ban", "kick", "member_update",
                                             "message_delete", "timeout")):
                    bump(entry.guild.id, user.id, "mod_actions")
        except Exception:
            pass

    # ----------------------------- commands ---------------------------
    @commands.group(name="aistaff", invoke_without_command=True,
                    help="AI staff suite — activity, reports, coaching and more.")
    @commands.guild_only()
    async def aistaff(self, ctx):
        p = ctx.clean_prefix
        await ctx.send(embed=self.embed(
            f"{MANAGER} AI Staff Suite",
            f"`{p}aistaff activity [@member]` — activity stats\n"
            f"`{p}aistaff leaderboard` — most active staff\n"
            f"`{p}aistaff inactive [days]` — find inactive staff\n"
            f"`{p}aistaff report [@member]` — AI performance review\n"
            f"`{p}aistaff coach [@member]` — AI coaching tips\n"
            f"`{p}aistaff summary` — AI weekly team summary\n"
            f"`{p}aistaff suggest <incident>` — AI punishment advice\n"
            f"`{p}aistaff evaluate <@member> <application>` — AI hire check\n"
            f"`{p}aistaff role add/remove <@role>` — mark staff roles\n"
            f"`{p}aistaff keys` — AI key rotation status"))

    @aistaff.command(name="activity", aliases=["stats"],
                     help="Show tracked activity for a staff member.")
    @commands.guild_only()
    async def activity(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        week = activity_totals(ctx.guild.id, member.id, 7)
        month = activity_totals(ctx.guild.id, member.id, 30)
        await ctx.send(embed=self.embed(
            f"{LEVEL_UP} Staff Activity — {member.display_name}",
            f"**Last 7 days**\n"
            f"{MESSAGE} Messages `{week['messages']}` • "
            f"Commands `{week['commands']}` • Mod actions `{week['mod_actions']}`\n\n"
            f"**Last 30 days**\n"
            f"{MESSAGE} Messages `{month['messages']}` • "
            f"Commands `{month['commands']}` • Mod actions `{month['mod_actions']}`\n\n"
            f"{TIME} **Last seen:** `{week['last_seen'] or month['last_seen'] or 'never'}`"))

    @aistaff.command(name="leaderboard", aliases=["lb", "top"],
                     help="Rank staff by weekly activity score.")
    @commands.guild_only()
    async def leaderboard(self, ctx, days: int = 7):
        rows = activity_board(ctx.guild.id, days)
        if not rows:
            return await ctx.send(embed=self.embed(
                f"{INFO} No Data", "No staff activity recorded yet."))
        medals = [KING, STAR, STAR]
        lines = []
        for i, r in enumerate(rows):
            score = (r[1] or 0) + (r[2] or 0) * 2 + (r[3] or 0) * 5
            prefix = medals[i] if i < 3 else f"`#{i + 1}`"
            lines.append(f"{prefix} <@{r[0]}> — **{score}** pts "
                         f"(`{r[1]}` msg • `{r[2]}` cmd • `{r[3]}` mod)")
        await ctx.send(embed=self.embed(
            f"{KING} Staff Activity Leaderboard ({days}d)", "\n".join(lines)))

    @aistaff.command(name="inactive", help="List staff with no activity recently.")
    @commands.guild_only()
    async def inactive(self, ctx, days: int = 7):
        active = {r[0] for r in activity_board(ctx.guild.id, days, 100)}
        missing = [m for m in ctx.guild.members
                   if is_staff(m) and str(m.id) not in active]
        if not missing:
            return await ctx.send(embed=self.embed(
                f"{TICK} All Active", f"Every staff member was active in {days} days."))
        body = "\n".join(f"{WARNING} {m.mention} — no activity" for m in missing[:20])
        await ctx.send(embed=self.embed(f"{WARNING} Inactive Staff ({days}d)", body))

    @aistaff.command(name="report", aliases=["review"],
                     help="AI performance review of a staff member.")
    @commands.guild_only()
    async def report(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        week = activity_totals(ctx.guild.id, member.id, 7)
        month = activity_totals(ctx.guild.id, member.id, 30)
        task = self.db.execute(
            "SELECT COUNT(*), SUM(status='done'), AVG(score) FROM ai_tasks "
            "WHERE guild_id=? AND assigned_to=?",
            (str(ctx.guild.id), str(member.id))).fetchone()
        async with ctx.typing():
            text = await ai_text(
                f"Staff member: {member.display_name}\n"
                f"7d -> messages {week['messages']}, commands {week['commands']}, "
                f"mod actions {week['mod_actions']}\n"
                f"30d -> messages {month['messages']}, commands {month['commands']}, "
                f"mod actions {month['mod_actions']}\n"
                f"Tasks assigned {task[0] or 0}, completed {task[1] or 0}, "
                f"average AI score {task[2] or 0:.0f}\n"
                f"Last seen: {week['last_seen'] or 'unknown'}",
                REPORT_SYSTEM)
        await ctx.send(embed=self.embed(
            f"{ZAI} AI Performance Review — {member.display_name}", text))

    @aistaff.command(name="coach", help="AI coaching tips for a staff member.")
    @commands.guild_only()
    async def coach(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        week = activity_totals(ctx.guild.id, member.id, 7)
        async with ctx.typing():
            text = await ai_text(
                f"Staff member {member.display_name} last 7 days: "
                f"{week['messages']} messages, {week['commands']} commands, "
                f"{week['mod_actions']} moderation actions.", COACH_SYSTEM)
        await ctx.send(embed=self.embed(
            f"{STAR} AI Coaching — {member.display_name}", text))

    @aistaff.command(name="summary", help="AI weekly summary of the whole staff team.")
    @commands.guild_only()
    async def summary(self, ctx):
        rows = activity_board(ctx.guild.id, 7, 20)
        if not rows:
            return await ctx.send(embed=self.embed(
                f"{INFO} No Data", "No staff activity recorded yet."))
        lines = []
        for r in rows:
            member = ctx.guild.get_member(int(r[0]))
            name = member.display_name if member else r[0]
            lines.append(f"{name}: {r[1]} msg, {r[2]} cmd, {r[3]} mod actions")
        async with ctx.typing():
            text = await ai_text(
                f"Server: {ctx.guild.name}\nStaff activity last 7 days:\n"
                + "\n".join(lines), SUMMARY_SYSTEM)
        await ctx.send(embed=self.embed(f"{ZAI} AI Staff Team Summary", text))

    @aistaff.command(name="suggest", aliases=["advice"],
                     help="AI recommends a fair punishment for an incident.")
    @commands.guild_only()
    async def suggest(self, ctx, *, incident: str):
        async with ctx.typing():
            data = await ai_json(f"Incident: {incident}", SUGGEST_SYSTEM)
        if not data:
            return await ctx.send(embed=self.embed(
                f"{WARNING} AI Unavailable", "Could not get advice right now."))
        await ctx.send(embed=self.embed(
            f"{ZAI} AI Moderation Advice",
            f"**Action:** `{data.get('action', 'none')}`\n"
            f"**Duration:** `{data.get('duration', 'n/a')}`\n"
            f"**Reason:** {data.get('reason', '—')}\n\n"
            f"{data.get('explanation', '')}"))

    @aistaff.command(name="evaluate", aliases=["hire"],
                     help="AI evaluates a staff applicant's application text.")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def evaluate(self, ctx, member: discord.Member, *, application: str):
        async with ctx.typing():
            data = await ai_json(
                f"Applicant: {member.display_name}\n"
                f"Account age days: {(discord.utils.utcnow() - member.created_at).days}\n"
                f"Application: {application}", HIRE_SYSTEM)
        if not data:
            return await ctx.send(embed=self.embed(
                f"{WARNING} AI Unavailable", "Could not evaluate right now."))
        await ctx.send(embed=self.embed(
            f"{ZAI} AI Applicant Evaluation — {member.display_name}",
            f"**Score:** `{data.get('score', 0)}/100`\n"
            f"**Recommendation:** `{data.get('recommendation', 'maybe')}`\n\n"
            f"**Strengths:** {data.get('strengths', '—')}\n"
            f"**Concerns:** {data.get('concerns', '—')}\n"
            f"**Interview questions:** {data.get('questions', '—')}"))

    @aistaff.group(name="role", invoke_without_command=True,
                   help="Register which roles count as staff for AI tracking.")
    @commands.guild_only()
    async def role(self, ctx):
        rows = self.db.execute("SELECT role_id FROM ai_staff_roles WHERE guild_id=?",
                               (str(ctx.guild.id),)).fetchall()
        body = ", ".join(f"<@&{r[0]}>" for r in rows) or "None registered."
        await ctx.send(embed=self.embed(f"{MANAGER} Staff Roles", body))

    @role.command(name="add", help="Mark a role as staff for AI tracking.")
    @commands.has_permissions(manage_guild=True)
    async def role_add(self, ctx, role: discord.Role):
        self.db.execute("INSERT OR IGNORE INTO ai_staff_roles VALUES (?,?)",
                        (str(ctx.guild.id), str(role.id)))
        self.db.commit()
        await ctx.send(embed=self.embed(f"{TICK} Staff Role Added", role.mention))

    @role.command(name="remove", help="Remove a role from AI staff tracking.")
    @commands.has_permissions(manage_guild=True)
    async def role_remove(self, ctx, role: discord.Role):
        self.db.execute("DELETE FROM ai_staff_roles WHERE guild_id=? AND role_id=?",
                        (str(ctx.guild.id), str(role.id)))
        self.db.commit()
        await ctx.send(embed=self.embed(f"{TICK} Staff Role Removed", role.mention))

    @aistaff.command(name="keys", help="Show AI key rotation status (owner only).")
    @commands.is_owner()
    async def keys(self, ctx):
        from utils.groq_keys import key_manager
        try:
            rows = key_manager.status()
            body = "\n".join(str(r) for r in rows) if rows else "No keys loaded."
        except Exception as exc:
            body = f"Could not read key status: {exc}"
        await ctx.send(embed=self.embed(
            f"{ZAI} AI Key Rotation", f"```{body[:1800]}```"))


async def setup(bot):
    await bot.add_cog(AIStaff(bot))
