# ╔══════════════════════════════════════════════════════════════════╗
# ║   AI Task  &  AI Task Checker                                    ║
# ║   Give AI generated duties to helpers / mods and let the AI      ║
# ║   review the submitted proof.                                    ║
# ╚══════════════════════════════════════════════════════════════════╝

import discord
from discord.ext import commands

from utils.emoji import (ZAI, TICK, CROSS, WARNING, INFO, PIN, STAR, TIME,
                         LEVEL_UP)
from utils.ai_staff_core import (db, now, bump, is_staff, ai_json, ai_text,
                                 COLOR)

TASK_SYSTEM = (
    "You are a Discord server staff manager. Generate practical, verifiable "
    "duties for a server helper or moderator. Return JSON: "
    "{\"tasks\":[{\"title\":\"short title\",\"details\":\"what exactly to do and "
    "how it is verified\",\"priority\":\"low|medium|high\"}]}"
)

CHECK_SYSTEM = (
    "You are a strict but fair staff task reviewer for a Discord server. "
    "Compare the task with the proof the staff member submitted. Return JSON: "
    "{\"verdict\":\"approved|partial|rejected\",\"score\":0-100,"
    "\"feedback\":\"2-3 sentences of specific feedback\","
    "\"missing\":\"what is still missing, or 'nothing'\"}"
)


class AITask(commands.Cog):
    """AI generated staff tasks with an AI powered completion checker."""

    def __init__(self, bot):
        self.bot = bot
        self.db = db()

    @staticmethod
    def help_custom():
        return (PIN, "AI Tasks", "AI staff tasks + AI task checker.")

    def embed(self, title, description):
        return discord.Embed(title=title, description=description, color=COLOR)

    def row(self, guild_id, task_id):
        return self.db.execute(
            "SELECT id, assigned_to, created_by, title, details, priority, "
            "status, proof, score, verdict, review, created_at FROM ai_tasks "
            "WHERE guild_id=? AND id=?",
            (str(guild_id), int(task_id))).fetchone()

    def can_manage(self, ctx):
        perms = ctx.author.guild_permissions
        return perms.manage_guild or perms.manage_messages

    # ============================ AI TASK =============================
    @commands.group(name="aitask", aliases=["aitasks"],
                    invoke_without_command=True,
                    help="AI staff task system — create, assign and track duties.")
    @commands.guild_only()
    async def aitask(self, ctx):
        await ctx.send(embed=self.embed(
            f"{PIN} AI Tasks",
            f"`{ctx.clean_prefix}aitask generate <@member> <topic>` — AI writes duties\n"
            f"`{ctx.clean_prefix}aitask create <@member> <title>` — manual task\n"
            f"`{ctx.clean_prefix}aitask list` — all open tasks\n"
            f"`{ctx.clean_prefix}aitask mine` — your own tasks\n"
            f"`{ctx.clean_prefix}aitask view <id>` — task details\n"
            f"`{ctx.clean_prefix}aitask submit <id> <proof>` — submit your work\n"
            f"`{ctx.clean_prefix}aitask reassign <id> <@member>`\n"
            f"`{ctx.clean_prefix}aitask delete <id>`\n"
            f"`{ctx.clean_prefix}aitaskcheck <id>` — AI reviews the proof"))

    @aitask.command(name="generate", aliases=["gen"],
                    help="Let the AI write and assign duties to a staff member.")
    @commands.guild_only()
    async def generate(self, ctx, member: discord.Member, *, topic: str = "general server duties"):
        if not self.can_manage(ctx):
            return await ctx.send(embed=self.embed(
                f"{CROSS} Missing Permission", "You need `Manage Messages`."))
        role = "moderator" if member.guild_permissions.ban_members else "helper"
        async with ctx.typing():
            data = await ai_json(
                f"Server: {ctx.guild.name}\nStaff member role: {role}\n"
                f"Focus area: {topic}\nGenerate exactly 3 tasks.", TASK_SYSTEM)
        tasks = (data or {}).get("tasks") if isinstance(data, dict) else None
        if not tasks:
            return await ctx.send(embed=self.embed(
                f"{WARNING} AI Unavailable", "Could not generate tasks right now."))

        created = []
        for task in tasks[:5]:
            cur = self.db.execute(
                "INSERT INTO ai_tasks (guild_id, assigned_to, created_by, title, "
                "details, priority, status, created_at) VALUES (?,?,?,?,?,?,'open',?)",
                (str(ctx.guild.id), str(member.id), str(ctx.author.id),
                 str(task.get("title", "Untitled"))[:200],
                 str(task.get("details", ""))[:900],
                 str(task.get("priority", "medium")).lower(), now()))
            created.append((cur.lastrowid, task))
        self.db.commit()

        body = "\n\n".join(
            f"**#{tid} — {t.get('title')}** `({t.get('priority','medium')})`\n"
            f"{str(t.get('details',''))[:300]}" for tid, t in created)
        await ctx.send(embed=self.embed(
            f"{ZAI} Tasks Assigned to {member.display_name}", body))
        try:
            await member.send(embed=self.embed(
                f"{PIN} New Tasks in {ctx.guild.name}", body))
        except discord.HTTPException:
            pass

    @aitask.command(name="create", aliases=["add"],
                    help="Manually assign a task to a staff member.")
    @commands.guild_only()
    async def create(self, ctx, member: discord.Member, *, title: str):
        if not self.can_manage(ctx):
            return await ctx.send(embed=self.embed(
                f"{CROSS} Missing Permission", "You need `Manage Messages`."))
        cur = self.db.execute(
            "INSERT INTO ai_tasks (guild_id, assigned_to, created_by, title, "
            "details, priority, status, created_at) VALUES (?,?,?,?,'','medium','open',?)",
            (str(ctx.guild.id), str(member.id), str(ctx.author.id), title[:200], now()))
        self.db.commit()
        await ctx.send(embed=self.embed(
            f"{TICK} Task #{cur.lastrowid} Created",
            f"**{title}**\nAssigned to {member.mention}."))

    @aitask.command(name="list", help="List every open staff task in this server.")
    @commands.guild_only()
    async def list_tasks(self, ctx):
        rows = self.db.execute(
            "SELECT id, assigned_to, title, priority, status FROM ai_tasks "
            "WHERE guild_id=? AND status!='done' ORDER BY id DESC LIMIT 15",
            (str(ctx.guild.id),)).fetchall()
        if not rows:
            return await ctx.send(embed=self.embed(f"{INFO} No Tasks",
                                                   "There are no open tasks."))
        body = "\n".join(
            f"`#{r[0]}` <@{r[1]}> — **{r[2]}** `({r[3]})` • `{r[4]}`" for r in rows)
        await ctx.send(embed=self.embed(f"{PIN} Open Staff Tasks", body))

    @aitask.command(name="mine", help="Show the tasks assigned to you.")
    @commands.guild_only()
    async def mine(self, ctx):
        rows = self.db.execute(
            "SELECT id, title, priority, status FROM ai_tasks WHERE guild_id=? "
            "AND assigned_to=? ORDER BY id DESC LIMIT 15",
            (str(ctx.guild.id), str(ctx.author.id))).fetchall()
        if not rows:
            return await ctx.send(embed=self.embed(f"{INFO} Nothing Assigned",
                                                   "You have no tasks right now."))
        body = "\n".join(f"`#{r[0]}` **{r[1]}** `({r[2]})` • `{r[3]}`" for r in rows)
        await ctx.send(embed=self.embed(f"{PIN} Your Tasks", body))

    @aitask.command(name="view", help="Show full details of one task.")
    @commands.guild_only()
    async def view(self, ctx, task_id: int):
        row = self.row(ctx.guild.id, task_id)
        if not row:
            return await ctx.send(embed=self.embed(f"{CROSS} Not Found",
                                                   f"No task with id `{task_id}`."))
        body = (f"**{row[3]}**\n{row[4] or 'No details.'}\n\n"
                f"**Assigned to:** <@{row[1]}>\n"
                f"**Priority:** `{row[5]}` • **Status:** `{row[6]}`\n"
                f"**Proof:** {row[7] or '—'}\n"
                f"**AI verdict:** {row[9] or '—'} "
                f"{'(' + str(row[8]) + '/100)' if row[8] is not None else ''}\n"
                f"**AI feedback:** {row[10] or '—'}")
        await ctx.send(embed=self.embed(f"{PIN} Task #{row[0]}", body))

    @aitask.command(name="submit", aliases=["proof", "complete"],
                    help="Submit your proof of completion for a task.")
    @commands.guild_only()
    async def submit(self, ctx, task_id: int, *, proof: str):
        row = self.row(ctx.guild.id, task_id)
        if not row:
            return await ctx.send(embed=self.embed(f"{CROSS} Not Found",
                                                   f"No task with id `{task_id}`."))
        if row[1] != str(ctx.author.id) and not self.can_manage(ctx):
            return await ctx.send(embed=self.embed(
                f"{CROSS} Not Yours", "This task is assigned to someone else."))
        self.db.execute(
            "UPDATE ai_tasks SET proof=?, status='submitted' WHERE guild_id=? AND id=?",
            (proof[:1500], str(ctx.guild.id), task_id))
        self.db.commit()
        bump(ctx.guild.id, ctx.author.id, "commands")
        await ctx.send(embed=self.embed(
            f"{TICK} Proof Submitted",
            f"Task `#{task_id}` is ready for review — run "
            f"`{ctx.clean_prefix}aitaskcheck {task_id}`."))

    @aitask.command(name="reassign", help="Move a task to another staff member.")
    @commands.guild_only()
    async def reassign(self, ctx, task_id: int, member: discord.Member):
        if not self.can_manage(ctx):
            return await ctx.send(embed=self.embed(
                f"{CROSS} Missing Permission", "You need `Manage Messages`."))
        self.db.execute(
            "UPDATE ai_tasks SET assigned_to=? WHERE guild_id=? AND id=?",
            (str(member.id), str(ctx.guild.id), task_id))
        self.db.commit()
        await ctx.send(embed=self.embed(f"{TICK} Task Reassigned",
                                        f"Task `#{task_id}` now belongs to {member.mention}."))

    @aitask.command(name="delete", aliases=["remove"], help="Delete a staff task.")
    @commands.guild_only()
    async def delete(self, ctx, task_id: int):
        if not self.can_manage(ctx):
            return await ctx.send(embed=self.embed(
                f"{CROSS} Missing Permission", "You need `Manage Messages`."))
        self.db.execute("DELETE FROM ai_tasks WHERE guild_id=? AND id=?",
                        (str(ctx.guild.id), task_id))
        self.db.commit()
        await ctx.send(embed=self.embed(f"{TICK} Task Deleted",
                                        f"Task `#{task_id}` removed."))

    # ========================= AI TASK CHECKER ========================
    @commands.command(name="aitaskcheck", aliases=["aicheck"],
                      help="AI reviews the submitted proof of a task and scores it.")
    @commands.guild_only()
    async def aitaskcheck(self, ctx, task_id: int):
        row = self.row(ctx.guild.id, task_id)
        if not row:
            return await ctx.send(embed=self.embed(f"{CROSS} Not Found",
                                                   f"No task with id `{task_id}`."))
        if not row[7]:
            return await ctx.send(embed=self.embed(
                f"{WARNING} No Proof Yet",
                f"Ask <@{row[1]}> to run `{ctx.clean_prefix}aitask submit {task_id} <proof>`."))

        async with ctx.typing():
            data = await ai_json(
                f"Task title: {row[3]}\nTask details: {row[4]}\n"
                f"Priority: {row[5]}\nStaff proof: {row[7]}", CHECK_SYSTEM)
        if not data:
            return await ctx.send(embed=self.embed(
                f"{WARNING} AI Unavailable", "Could not review the task right now."))

        verdict = str(data.get("verdict", "partial")).lower()
        try:
            score = int(data.get("score", 0))
        except (TypeError, ValueError):
            score = 0
        feedback = str(data.get("feedback", ""))[:900]
        missing = str(data.get("missing", "nothing"))[:400]
        status = "done" if verdict == "approved" else "submitted"

        self.db.execute(
            "UPDATE ai_tasks SET verdict=?, score=?, review=?, status=?, completed_at=? "
            "WHERE guild_id=? AND id=?",
            (verdict, score, feedback, status,
             now() if status == "done" else None, str(ctx.guild.id), task_id))
        self.db.commit()
        if status == "done":
            bump(ctx.guild.id, row[1], "mod_actions")

        icon = {"approved": TICK, "partial": WARNING, "rejected": CROSS}.get(verdict, INFO)
        await ctx.send(embed=self.embed(
            f"{icon} AI Review — Task #{task_id}",
            f"**Staff:** <@{row[1]}>\n"
            f"**Task:** {row[3]}\n"
            f"**Verdict:** `{verdict}` • **Score:** `{score}/100`\n\n"
            f"**Feedback:** {feedback}\n"
            f"**Still missing:** {missing}"))

    @commands.command(name="aitaskstats", aliases=["aitaskscore"],
                      help="AI task completion stats for a staff member.")
    @commands.guild_only()
    async def aitaskstats(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        row = self.db.execute(
            "SELECT COUNT(*), SUM(status='done'), AVG(score) FROM ai_tasks "
            "WHERE guild_id=? AND assigned_to=?",
            (str(ctx.guild.id), str(member.id))).fetchone()
        total, done, avg = row[0] or 0, row[1] or 0, row[2]
        rate = f"{(done / total * 100):.0f}%" if total else "—"
        await ctx.send(embed=self.embed(
            f"{LEVEL_UP} Task Stats — {member.display_name}",
            f"**Tasks assigned:** `{total}`\n"
            f"**Completed:** `{done}`\n"
            f"**Completion rate:** `{rate}`\n"
            f"**Average AI score:** `{avg:.0f}/100`" if avg is not None else
            f"**Tasks assigned:** `{total}`\n**Completed:** `{done}`\n"
            f"**Completion rate:** `{rate}`\n**Average AI score:** `—`"))


async def setup(bot):
    await bot.add_cog(AITask(bot))
