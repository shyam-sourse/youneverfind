# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░█░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                     ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 CodeX Devs — All Rights Reserved              ║
# ║                                                                  ║
# ║   Staff Applications  ──  application <subcommand>               ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

import os
import sqlite3
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from utils.emoji import (ZSAFE, TICKET, ZARROW, TICK, CROSS, INFO, ENABLE,
                         DISABLE, KING, MESSAGE, NEW)

DB_FILE = "db/applications.db"
COLOR = 0xFF0000
PENDING_COLOR = discord.Color.yellow()
ACCEPTED_COLOR = discord.Color.green()
DENIED_COLOR = discord.Color.red()

DEFAULT_QUESTIONS = [
    "Why do you want to join our staff team?",
    "What relevant experience do you have?",
    "How many hours per week can you dedicate?",
    "Describe a time you resolved a conflict.",
    "Anything else we should know?",
]


class ReasonModal(discord.ui.Modal):
    """Asks the reviewer for a reason before accepting/denying."""

    def __init__(self, cog: "StaffApplication", app_id: int, accepted: bool):
        super().__init__(title=f"{'Accept' if accepted else 'Deny'} Application #{app_id}",
                         timeout=300)
        self.cog = cog
        self.app_id = app_id
        self.accepted = accepted
        self.reason = discord.ui.TextInput(
            label="Reason",
            placeholder="Reason shown to the applicant...",
            style=discord.TextStyle.paragraph,
            max_length=500,
            required=not accepted,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.decide(interaction, self.app_id,
                              str(self.reason.value) or None, self.accepted)


class ReviewPanel(discord.ui.View):
    """Persistent Accept / Deny buttons attached to a review message."""

    def __init__(self, cog: "StaffApplication"):
        super().__init__(timeout=None)
        self.cog = cog

    @staticmethod
    def _app_id(interaction: discord.Interaction):
        for embed in interaction.message.embeds:
            if embed.footer and embed.footer.text:
                for part in embed.footer.text.split():
                    if part.isdigit():
                        return int(part)
        return None

    async def _handle(self, interaction: discord.Interaction, accepted: bool):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                f"{CROSS} You need **Manage Server** to review applications.",
                ephemeral=True)
        app_id = self._app_id(interaction)
        if app_id is None:
            return await interaction.response.send_message(
                f"{CROSS} Couldn't resolve this application.", ephemeral=True)
        row = self.cog.fetch_application(interaction.guild.id, app_id)
        if not row:
            return await interaction.response.send_message(
                f"{CROSS} Application `{app_id}` no longer exists.", ephemeral=True)
        if row[4] != "pending":
            return await interaction.response.send_message(
                f"{CROSS} Application `{app_id}` was already **{row[4]}**.",
                ephemeral=True)
        await interaction.response.send_modal(
            ReasonModal(self.cog, app_id, accepted))

    @discord.ui.button(label="Accept",
                       emoji="✅",
                       style=discord.ButtonStyle.success,
                       custom_id="staff_application_review_accept")
    async def accept_btn(self, interaction: discord.Interaction,
                         button: discord.ui.Button):
        await self._handle(interaction, True)

    @discord.ui.button(label="Deny",
                       emoji="❌",
                       style=discord.ButtonStyle.danger,
                       custom_id="staff_application_review_deny")
    async def deny_btn(self, interaction: discord.Interaction,
                       button: discord.ui.Button):
        await self._handle(interaction, False)


class ApplicationModal(discord.ui.Modal):
    """Dynamic modal built from the guild's configured questions."""

    def __init__(self, cog: "StaffApplication", questions: list):
        super().__init__(title="Staff Application", timeout=None)
        self.cog = cog
        self.questions = questions
        self.inputs = []
        for question in questions[:5]:
            field = discord.ui.TextInput(
                label=question[:45],
                placeholder=question[:100],
                style=discord.TextStyle.paragraph,
                max_length=1000,
                required=True,
            )
            self.inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction):
        answers = [str(field.value) for field in self.inputs]
        app_id = self.cog.create_application(interaction.guild.id,
                                            interaction.user.id,
                                            self.questions, answers)

        await interaction.response.send_message(
            f"{TICK} **Your application has been submitted!**\n"
            f"{ZARROW} Application ID: `{app_id}`\n"
            f"{ZARROW} You will be informed once the staff team reviews it.",
            ephemeral=True)

        review_id = (self.cog.get_setting(interaction.guild.id, "review_channel")
                     or self.cog.get_setting(interaction.guild.id, "log_channel"))
        if not review_id:
            return
        channel = interaction.guild.get_channel(int(review_id))
        if not channel:
            return

        embed = discord.Embed(
            title=f"{ZSAFE} New Staff Application #{app_id}",
            description=f"**Applicant:** {interaction.user.mention} (`{interaction.user.id}`)",
            color=PENDING_COLOR,
            timestamp=datetime.utcnow())
        for question, answer in zip(self.questions, answers):
            embed.add_field(name=question[:256],
                            value=f"{answer[:1000]}\n•",
                            inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"Application ID: {app_id}")
        await channel.send(embed=embed, view=ReviewPanel(self.cog))


class ApplyPanel(discord.ui.View):
    """Persistent panel with the Apply Now button."""

    def __init__(self, cog: "StaffApplication"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Apply Now",
                       emoji="📋",
                       style=discord.ButtonStyle.success,
                       custom_id="staff_application_apply")
    async def apply(self, interaction: discord.Interaction,
                    button: discord.ui.Button):
        if self.cog.get_setting(interaction.guild.id, "is_open") == "0":
            return await interaction.response.send_message(
                f"{CROSS} Staff applications are currently **closed**.",
                ephemeral=True)

        pending = self.cog.db.execute(
            "SELECT id FROM applications WHERE guild_id=? AND user_id=? AND status='pending'",
            (str(interaction.guild.id), str(interaction.user.id))).fetchone()
        if pending:
            return await interaction.response.send_message(
                f"{CROSS} You already have a pending application (`{pending[0]}`).",
                ephemeral=True)

        questions = self.cog.get_questions(interaction.guild.id)
        await interaction.response.send_modal(
            ApplicationModal(self.cog, questions))


class StaffApplication(commands.Cog):
    """Complete staff application system with panels, queue and reviews."""

    def __init__(self, bot):
        self.bot = bot
        os.makedirs("db", exist_ok=True)
        self.db = sqlite3.connect(DB_FILE)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                guild_id TEXT PRIMARY KEY,
                panel_channel TEXT,
                log_channel TEXT,
                accepted_role TEXT,
                questions TEXT,
                is_open TEXT DEFAULT '1',
                review_channel TEXT
            );
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER,
                guild_id TEXT,
                user_id TEXT,
                questions TEXT,
                answers TEXT,
                status TEXT DEFAULT 'pending',
                reviewer_id TEXT,
                note TEXT,
                created_at TEXT,
                PRIMARY KEY (guild_id, id)
            );
        """)
        # migration for older databases
        try:
            self.db.execute("ALTER TABLE app_settings ADD COLUMN review_channel TEXT")
        except sqlite3.OperationalError:
            pass
        self.db.commit()

    def cog_unload(self):
        self.db.close()

    @staticmethod
    def help_custom():
        return (ZSAFE, "Staff Applications",
                "Applications, panel, queue and reviews.")

    async def cog_load(self):
        self.bot.add_view(ApplyPanel(self))
        self.bot.add_view(ReviewPanel(self))


    # ----------------------------- helpers -----------------------------
    def get_setting(self, guild_id, field):
        row = self.db.execute(
            f"SELECT {field} FROM app_settings WHERE guild_id=?",
            (str(guild_id), )).fetchone()
        return row[0] if row and row[0] is not None else None

    def set_setting(self, guild_id, field, value):
        self.db.execute(
            f"""INSERT INTO app_settings (guild_id, {field}) VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET {field}=excluded.{field}""",
            (str(guild_id), str(value)))
        self.db.commit()

    def get_questions(self, guild_id):
        raw = self.get_setting(guild_id, "questions")
        if not raw:
            return DEFAULT_QUESTIONS
        questions = [q.strip() for q in raw.split("|") if q.strip()]
        return questions or DEFAULT_QUESTIONS

    def create_application(self, guild_id, user_id, questions, answers):
        row = self.db.execute(
            "SELECT COALESCE(MAX(id), 0) FROM applications WHERE guild_id=?",
            (str(guild_id), )).fetchone()
        app_id = int(row[0]) + 1
        self.db.execute(
            """INSERT INTO applications
               (id, guild_id, user_id, questions, answers, status, created_at)
               VALUES (?,?,?,?,?, 'pending', ?)""",
            (app_id, str(guild_id), str(user_id), "|".join(questions),
             "|".join(a.replace("|", "/") for a in answers),
             datetime.utcnow().isoformat()))
        self.db.commit()
        return app_id

    def fetch_application(self, guild_id, app_id):
        return self.db.execute(
            "SELECT id, user_id, questions, answers, status, reviewer_id, note, created_at "
            "FROM applications WHERE guild_id=? AND id=?",
            (str(guild_id), int(app_id))).fetchone()

    async def _apply_decision(self, guild, reviewer, app_id: int, note: str,
                              accepted: bool):
        """Core review logic. Returns (error_message, embed)."""
        row = self.fetch_application(guild.id, app_id)
        if not row:
            return f"{CROSS} No application found with ID `{app_id}`.", None
        if row[4] != "pending":
            return (f"{CROSS} Application `{app_id}` was already **{row[4]}**.",
                    None)

        status = "accepted" if accepted else "denied"
        self.db.execute(
            "UPDATE applications SET status=?, reviewer_id=?, note=? WHERE guild_id=? AND id=?",
            (status, str(reviewer.id), note or "No note", str(guild.id),
             int(app_id)))
        self.db.commit()

        member = guild.get_member(int(row[1]))
        role_id = self.get_setting(guild.id, "accepted_role")
        if accepted and member and role_id:
            role = guild.get_role(int(role_id))
            if role:
                try:
                    await member.add_roles(role, reason=f"Application accepted by {reviewer}")
                except discord.Forbidden:
                    pass

        embed = discord.Embed(
            title=f"{TICK if accepted else CROSS} Application #{app_id} {status.title()}",
            description=(f"{ZARROW} **Applicant:** <@{row[1]}>\n"
                         f"{ZARROW} **Reviewer:** {reviewer.mention}\n"
                         f"{ZARROW} **Reason:** {note or 'No reason given'}"),
            color=ACCEPTED_COLOR if accepted else DENIED_COLOR)

        if member:
            try:
                await member.send(
                    f"{ZSAFE} Your staff application in **{guild.name}** was "
                    f"**{status}**.\n{ZARROW} Reason: {note or 'No reason given'}")
            except discord.HTTPException:
                pass

        log_id = self.get_setting(guild.id, "log_channel")
        if log_id:
            channel = guild.get_channel(int(log_id))
            if channel:
                await channel.send(embed=embed)
        return None, embed

    async def _decide(self, ctx, app_id: int, note: str, accepted: bool):
        error, embed = await self._apply_decision(ctx.guild, ctx.author, app_id,
                                                  note, accepted)
        if error:
            return await ctx.send(error)
        await ctx.send(embed=embed)

    async def decide(self, interaction: discord.Interaction, app_id: int,
                     note: str, accepted: bool):
        """Called by the Accept/Deny buttons after the reason modal."""
        error, embed = await self._apply_decision(interaction.guild,
                                                  interaction.user, app_id,
                                                  note, accepted)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)
        # disable the buttons on the original review message
        try:
            view = discord.ui.View(timeout=None)
            view.add_item(
                discord.ui.Button(
                    label=f"{'Accepted' if accepted else 'Denied'} by {interaction.user.display_name}",
                    style=discord.ButtonStyle.secondary,
                    disabled=True,
                    custom_id="staff_application_review_done"))
            original = interaction.message
            if original:
                new_embeds = list(original.embeds)
                if new_embeds:
                    new_embeds[0].color = (ACCEPTED_COLOR if accepted
                                            else DENIED_COLOR)
                    new_embeds[0].set_footer(
                        text=f"Application ID: {app_id} • "
                             f"{'Accepted' if accepted else 'Denied'} by {interaction.user}")
                await original.edit(embeds=new_embeds, view=view)
                await original.reply(embed=embed)
        except discord.HTTPException:
            pass

    # ----------------------------- commands -----------------------------
    @commands.hybrid_group(name="application",
                           description="Staff application system.")
    @commands.guild_only()
    async def application(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @application.command(name="setup",
                         description="Configure the application system.")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(panel_channel="Where the apply panel is posted.",
                           log_channel="Where new applications are logged.",
                           accepted_role="Role given on acceptance.")
    async def setup(self, ctx, panel_channel: discord.TextChannel,
                    log_channel: discord.TextChannel,
                    accepted_role: discord.Role):
        """Configure the application system."""
        self.set_setting(ctx.guild.id, "panel_channel", panel_channel.id)
        self.set_setting(ctx.guild.id, "log_channel", log_channel.id)
        self.set_setting(ctx.guild.id, "accepted_role", accepted_role.id)
        embed = discord.Embed(
            title=f"{ZSAFE} Application System Configured",
            description=(f"{ZARROW} **Panel Channel:** {panel_channel.mention}\n"
                         f"{ZARROW} **Log Channel:** {log_channel.mention}\n"
                         f"{ZARROW} **Accepted Role:** {accepted_role.mention}"),
            color=COLOR)
        await ctx.send(embed=embed)

    @application.command(
        name="reviewchannel",
        description="Set the channel where applications are reviewed with buttons.")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        channel="Channel where Accept/Deny buttons are posted.")
    async def reviewchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel where applications are reviewed with buttons."""
        self.set_setting(ctx.guild.id, "review_channel", channel.id)
        await ctx.send(embed=discord.Embed(
            title=f"{ZSAFE} Review Channel Set",
            description=(f"{ZARROW} New applications will be posted in "
                         f"{channel.mention} with **Accept** / **Deny** buttons.\n"
                         f"{ZARROW} Reviewers are asked for a **reason**, which is "
                         f"DMed to the applicant."),
            color=COLOR))


    @application.command(name="panel",
                         description="Post the application panel in a channel.")
    @commands.has_permissions(manage_guild=True)
    async def panel(self, ctx, channel: discord.TextChannel = None):
        """Post the application panel in a channel."""
        channel = channel or ctx.channel
        embed = discord.Embed(
            title=f"{ZSAFE} Join Our Staff Team!",
            description=("We're looking for dedicated, active members to join the "
                         "staff team.\n\nClick **Apply Now** below to start your "
                         "application."),
            color=COLOR)
        embed.set_footer(text=f"{ctx.guild.name} Staff Applications")
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        await channel.send(embed=embed, view=ApplyPanel(self))
        self.set_setting(ctx.guild.id, "panel_channel", channel.id)
        await ctx.send(f"{TICK} Application panel posted in {channel.mention}.")

    @application.command(name="questions",
                         description="Set up to 5 custom application questions.")
    @commands.has_permissions(manage_guild=True)
    async def questions(self, ctx, *, questions: str):
        """Set up to 5 custom application questions (separate with |)."""
        parsed = [q.strip() for q in questions.split("|") if q.strip()][:5]
        if not parsed:
            return await ctx.send(
                f"{CROSS} Provide at least one question, separated by `|`.")
        self.set_setting(ctx.guild.id, "questions", "|".join(parsed))
        listed = "\n".join(f"{ZARROW} `{i}.` {q}"
                           for i, q in enumerate(parsed, 1))
        await ctx.send(embed=discord.Embed(
            title=f"{MESSAGE} Application Questions Updated",
            description=listed,
            color=COLOR))

    @application.command(name="toggle",
                         description="Open or close staff applications.")
    @commands.has_permissions(manage_guild=True)
    async def toggle(self, ctx):
        """Open or close staff applications."""
        current = self.get_setting(ctx.guild.id, "is_open") or "1"
        new = "0" if current == "1" else "1"
        self.set_setting(ctx.guild.id, "is_open", new)
        state = f"{ENABLE} **Open**" if new == "1" else f"{DISABLE} **Closed**"
        await ctx.send(f"{ZSAFE} Staff applications are now {state}.")

    @application.command(name="queue",
                         description="View the pending application queue.")
    @commands.has_permissions(manage_guild=True)
    async def queue(self, ctx):
        """View the pending application queue."""
        rows = self.db.execute(
            "SELECT id, user_id, created_at FROM applications "
            "WHERE guild_id=? AND status='pending' ORDER BY id ASC",
            (str(ctx.guild.id), )).fetchall()
        if not rows:
            return await ctx.send(f"{INFO} The application queue is empty.")
        desc = "\n".join(
            f"{ZARROW} `#{r[0]}` <@{r[1]}> — <t:{int(datetime.fromisoformat(r[2]).timestamp())}:R>"
            for r in rows[:20])
        await ctx.send(embed=discord.Embed(
            title=f"{TICKET} Pending Applications ({len(rows)})",
            description=desc,
            color=COLOR))

    @application.command(name="view", description="View a specific application.")
    @commands.has_permissions(manage_guild=True)
    async def view(self, ctx, application_id: int):
        """View a specific application."""
        row = self.fetch_application(ctx.guild.id, application_id)
        if not row:
            return await ctx.send(
                f"{CROSS} No application found with ID `{application_id}`.")
        embed = discord.Embed(
            title=f"{ZSAFE} Staff Application #{row[0]}",
            description=(f"{ZARROW} **Applicant:** <@{row[1]}>\n"
                         f"{ZARROW} **Status:** `{row[4]}`\n"
                         f"{ZARROW} **Reviewer:** "
                         f"{f'<@{row[5]}>' if row[5] else 'None'}\n"
                         f"{ZARROW} **Note:** {row[6] or 'None'}"),
            color=COLOR)
        for question, answer in zip(row[2].split("|"), row[3].split("|")):
            embed.add_field(name=question[:256],
                            value=f"{answer[:1000]}\n•",
                            inline=False)
        await ctx.send(embed=embed)

    @application.command(name="accept",
                         description="Accept a pending application by ID.")
    @commands.has_permissions(manage_guild=True)
    async def accept(self, ctx, application_id: int, *, note: str = None):
        """Accept a pending application by ID."""
        await self._decide(ctx, application_id, note, True)

    @application.command(name="deny",
                         description="Deny a pending application by ID.")
    @commands.has_permissions(manage_guild=True)
    async def deny(self, ctx, application_id: int, *, note: str = None):
        """Deny a pending application by ID."""
        await self._decide(ctx, application_id, note, False)

    @application.command(name="history",
                         description="View past applications for a member.")
    @commands.has_permissions(manage_guild=True)
    async def history(self, ctx, member: discord.Member = None):
        """View past applications for a member."""
        member = member or ctx.author
        rows = self.db.execute(
            "SELECT id, status, note FROM applications WHERE guild_id=? AND user_id=? "
            "ORDER BY id DESC", (str(ctx.guild.id), str(member.id))).fetchall()
        if not rows:
            return await ctx.send(
                f"{INFO} {member.mention} has no application history.")
        desc = "\n".join(
            f"{ZARROW} `#{r[0]}` **{r[1].title()}** — {r[2] or 'No note'}"
            for r in rows[:15])
        await ctx.send(embed=discord.Embed(
            title=f"{KING} Application History — {member.display_name} {NEW}",
            description=desc,
            color=COLOR))


async def setup(bot):
    await bot.add_cog(StaffApplication(bot))
