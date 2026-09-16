# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░█░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                     ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 CodeX Devs — All Rights Reserved              ║
# ║                                                                  ║
# ║   Advanced Security  ──  security <subcommand> / health           ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

import json
import os
import platform
import sqlite3
import time
from datetime import datetime, timezone

import discord
import psutil
from discord import app_commands
from discord.ext import commands

from utils.emoji import (ZSAFE, LOCK, THUNDER, ZBAN, ZARROW, TICK, CROSS, INFO,
                         STAR, ZWRENCH, KING, ZMODULE, ENABLE, DISABLE, NEW)
from utils.config import OWNER_IDS

DB_FILE = "db/advsecurity.db"
COLOR = 0xFF0000

DANGEROUS_PERMS = ("administrator", "manage_guild", "manage_roles",
                   "manage_channels", "manage_webhooks", "ban_members",
                   "kick_members", "mention_everyone")

TRUST_KINDS = {"trustuser": "user", "trustrole": "role", "trustbot": "bot"}
TRUST_ACTIONS = ("add", "remove", "list")


class AdvancedSecurity(commands.Cog):
    """Advanced server security: audits, lockdowns, raid mode and trust lists."""

    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
        os.makedirs("db", exist_ok=True)
        self.db = sqlite3.connect(DB_FILE)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sec_settings (
                guild_id TEXT PRIMARY KEY,
                raidmode TEXT DEFAULT '0',
                locked TEXT DEFAULT '0',
                log_channel TEXT
            );
            CREATE TABLE IF NOT EXISTS sec_trust (
                guild_id TEXT, kind TEXT, target_id TEXT,
                PRIMARY KEY (guild_id, kind, target_id)
            );
            CREATE TABLE IF NOT EXISTS sec_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT,
                action TEXT, author_id TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sec_blacklist (
                target_id TEXT PRIMARY KEY, kind TEXT, reason TEXT
            );
            CREATE TABLE IF NOT EXISTS sec_backups (
                guild_id TEXT PRIMARY KEY, payload TEXT, created_at TEXT
            );
        """)
        self.db.commit()

    def cog_unload(self):
        self.db.close()

    @staticmethod
    def help_custom():
        return (LOCK, "Advanced Security",
                "Audits, lockdown, raidmode & trust lists.")

    # ----------------------------- helpers -----------------------------
    def embed(self, title, description):
        return discord.Embed(title=title, description=description, color=COLOR)

    def setting(self, guild_id, field):
        row = self.db.execute(f"SELECT {field} FROM sec_settings WHERE guild_id=?",
                              (str(guild_id), )).fetchone()
        return row[0] if row and row[0] else None

    def set_setting(self, guild_id, field, value):
        self.db.execute(
            f"""INSERT INTO sec_settings (guild_id, {field}) VALUES (?,?)
                ON CONFLICT(guild_id) DO UPDATE SET {field}=excluded.{field}""",
            (str(guild_id), str(value)))
        self.db.commit()

    def record(self, guild_id, author_id, action):
        self.db.execute(
            "INSERT INTO sec_actions (guild_id, action, author_id, created_at) "
            "VALUES (?,?,?,?)",
            (str(guild_id), action, str(author_id),
             datetime.utcnow().isoformat()))
        self.db.commit()

    def is_trusted(self, member: discord.Member) -> bool:
        rows = {r[0] for r in self.db.execute(
            "SELECT target_id FROM sec_trust WHERE guild_id=? AND kind IN ('user','role')",
            (str(member.guild.id), )).fetchall()}
        if str(member.id) in rows:
            return True
        return any(str(role.id) in rows for role in member.roles)

    # ---------------------------- raid mode ----------------------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if self.setting(member.guild.id, "raidmode") != "1":
            return
        if self.is_trusted(member):
            return
        age = (datetime.now(timezone.utc) - member.created_at).total_seconds()
        if age > 86400:
            return
        try:
            await member.kick(reason="Raid mode: account too new")
        except discord.HTTPException:
            return
        self.record(member.guild.id, self.bot.user.id,
                    f"Raid mode kick: {member} ({member.id})")
        channel_id = self.setting(member.guild.id, "log_channel")
        if channel_id:
            channel = member.guild.get_channel(int(channel_id))
            if channel:
                await channel.send(embed=self.embed(
                    f"{ZBAN} Raid Mode Action",
                    f"{ZARROW} Kicked {member} (`{member.id}`) — account too new."))

    # ----------------------------- commands -----------------------------
    @commands.hybrid_group(name="security",
                           description="Advanced server security tools.")
    @commands.guild_only()
    async def security(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @security.command(name="dashboard",
                      description="View the server's security dashboard.")
    @commands.has_permissions(manage_guild=True)
    async def dashboard(self, ctx):
        """View the server's security dashboard."""
        guild = ctx.guild
        risky = [r for r in guild.roles
                 if any(getattr(r.permissions, p) for p in DANGEROUS_PERMS)]
        bots = [m for m in guild.members if m.bot]
        trusted = self.db.execute(
            "SELECT COUNT(*) FROM sec_trust WHERE guild_id=?",
            (str(guild.id), )).fetchone()[0]
        raid = f"{ENABLE} On" if self.setting(guild.id, "raidmode") == "1" else f"{DISABLE} Off"
        lock = f"{LOCK} Locked" if self.setting(guild.id, "locked") == "1" else f"{TICK} Normal"
        embed = self.embed(
            f"{ZSAFE} Security Dashboard",
            f"{ZARROW} **Verification Level:** `{guild.verification_level}`\n"
            f"{ZARROW} **2FA Requirement:** `{bool(guild.mfa_level)}`\n"
            f"{ZARROW} **Risky Roles:** `{len(risky)}`\n"
            f"{ZARROW} **Bots In Server:** `{len(bots)}`\n"
            f"{ZARROW} **Trusted Entries:** `{trusted}`\n"
            f"{ZARROW} **Raid Mode:** {raid}\n"
            f"{ZARROW} **Server State:** {lock}")
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await ctx.send(embed=embed)

    @security.command(name="audit",
                      description="Full permission audit — dangerous roles and who holds them.")
    @commands.has_permissions(manage_guild=True)
    async def audit(self, ctx):
        """Full permission audit — dangerous roles and who holds them."""
        lines = []
        for role in sorted(ctx.guild.roles, reverse=True):
            flags = [p for p in DANGEROUS_PERMS if getattr(role.permissions, p)]
            if not flags:
                continue
            lines.append(f"{ZARROW} {role.mention} — `{len(role.members)}` members\n"
                         f"     `{', '.join(flags)}`")
        if not lines:
            return await ctx.send(f"{TICK} No roles hold dangerous permissions.")
        await ctx.send(embed=self.embed(f"{ZSAFE} Permission Audit",
                                        "\n".join(lines[:15])))

    @security.command(name="permscan",
                      description="Scan all roles for dangerous permissions.")
    @commands.has_permissions(manage_guild=True)
    async def permscan(self, ctx):
        """Scan all roles for dangerous permissions."""
        admins = [r.mention for r in ctx.guild.roles if r.permissions.administrator]
        managers = [r.mention for r in ctx.guild.roles
                    if r.permissions.manage_guild and not r.permissions.administrator]
        await ctx.send(embed=self.embed(
            f"{ZWRENCH} Permission Scan",
            f"{ZARROW} **Administrator Roles:** {', '.join(admins) or 'None'}\n"
            f"{ZARROW} **Manage Server Roles:** {', '.join(managers) or 'None'}\n"
            f"{ZARROW} **Total Roles:** `{len(ctx.guild.roles)}`"))

    @security.command(name="lockdown",
                      description="Lock all text channels down (deny @everyone send messages).")
    @commands.has_permissions(administrator=True)
    async def lockdown(self, ctx, *, reason: str = "Emergency lockdown"):
        """Lock all text channels down (deny @everyone send messages)."""
        done = 0
        for channel in ctx.guild.text_channels:
            try:
                await channel.set_permissions(ctx.guild.default_role,
                                              send_messages=False,
                                              reason=reason)
                done += 1
            except discord.HTTPException:
                continue
        self.set_setting(ctx.guild.id, "locked", "1")
        self.record(ctx.guild.id, ctx.author.id, f"Lockdown: {reason}")
        await ctx.send(embed=self.embed(
            f"{LOCK} Server Lockdown Active",
            f"{ZARROW} **Channels Locked:** `{done}`\n"
            f"{ZARROW} **Reason:** {reason}\n"
            f"{ZARROW} **By:** {ctx.author.mention}"))

    @security.command(name="unlock", description="Lift the emergency lockdown.")
    @commands.has_permissions(administrator=True)
    async def unlock(self, ctx):
        """Lift the emergency lockdown."""
        done = 0
        for channel in ctx.guild.text_channels:
            try:
                await channel.set_permissions(ctx.guild.default_role,
                                              send_messages=None,
                                              reason="Lockdown lifted")
                done += 1
            except discord.HTTPException:
                continue
        self.set_setting(ctx.guild.id, "locked", "0")
        self.record(ctx.guild.id, ctx.author.id, "Lockdown lifted")
        await ctx.send(embed=self.embed(
            f"{TICK} Lockdown Lifted",
            f"{ZARROW} **Channels Restored:** `{done}`\n"
            f"{ZARROW} **By:** {ctx.author.mention}"))

    @security.command(name="raidmode",
                      description="Toggle raid mode (auto-kicks very new accounts on join).")
    @commands.has_permissions(administrator=True)
    async def raidmode(self, ctx):
        """Toggle raid mode (auto-kicks very new accounts on join)."""
        current = self.setting(ctx.guild.id, "raidmode") or "0"
        new = "0" if current == "1" else "1"
        self.set_setting(ctx.guild.id, "raidmode", new)
        self.record(ctx.guild.id, ctx.author.id, f"Raid mode set to {new}")
        state = f"{ENABLE} **Enabled**" if new == "1" else f"{DISABLE} **Disabled**"
        await ctx.send(embed=self.embed(
            f"{THUNDER} Raid Mode {state}",
            f"{ZARROW} Accounts younger than 24 hours will "
            f"{'be kicked on join' if new == '1' else 'no longer be kicked'}."))

    @security.command(name="stats", description="View security action statistics.")
    @commands.has_permissions(manage_guild=True)
    async def stats(self, ctx):
        """View security action statistics."""
        total = self.db.execute(
            "SELECT COUNT(*) FROM sec_actions WHERE guild_id=?",
            (str(ctx.guild.id), )).fetchone()[0]
        rows = self.db.execute(
            "SELECT action, created_at FROM sec_actions WHERE guild_id=? "
            "ORDER BY id DESC LIMIT 10", (str(ctx.guild.id), )).fetchall()
        recent = "\n".join(f"{ZARROW} `{r[1][:16]}` {r[0]}" for r in rows) or "None"
        await ctx.send(embed=self.embed(
            f"{STAR} Security Statistics",
            f"{ZARROW} **Total Actions Logged:** `{total}`\n\n**Recent**\n{recent}"))

    @security.command(name="backup",
                      description="Backup and restore server configuration.")
    @commands.has_permissions(administrator=True)
    @app_commands.describe(action="create | view | restore")
    async def backup(self, ctx, action: str = "create"):
        """Backup and restore server configuration."""
        action = action.lower()
        guild = ctx.guild
        if action == "create":
            payload = {
                "name": guild.name,
                "roles": [{"name": r.name, "permissions": r.permissions.value,
                           "color": r.color.value, "hoist": r.hoist}
                          for r in guild.roles if not r.managed and not r.is_default()],
                "channels": [{"name": c.name, "type": str(c.type),
                              "category": c.category.name if c.category else None}
                             for c in guild.channels],
            }
            self.db.execute(
                """INSERT INTO sec_backups (guild_id, payload, created_at) VALUES (?,?,?)
                   ON CONFLICT(guild_id) DO UPDATE SET payload=excluded.payload,
                   created_at=excluded.created_at""",
                (str(guild.id), json.dumps(payload), datetime.utcnow().isoformat()))
            self.db.commit()
            self.record(guild.id, ctx.author.id, "Configuration backup created")
            return await ctx.send(embed=self.embed(
                f"{TICK} Backup Created",
                f"{ZARROW} **Roles Saved:** `{len(payload['roles'])}`\n"
                f"{ZARROW} **Channels Saved:** `{len(payload['channels'])}`"))

        row = self.db.execute(
            "SELECT payload, created_at FROM sec_backups WHERE guild_id=?",
            (str(guild.id), )).fetchone()
        if not row:
            return await ctx.send(f"{CROSS} No backup found. Run `security backup create`.")
        data = json.loads(row[0])

        if action == "view":
            return await ctx.send(embed=self.embed(
                f"{ZMODULE} Latest Backup",
                f"{ZARROW} **Created:** `{row[1][:16]}`\n"
                f"{ZARROW} **Roles:** `{len(data['roles'])}`\n"
                f"{ZARROW} **Channels:** `{len(data['channels'])}`"))

        if action == "restore":
            existing = {r.name for r in guild.roles}
            created = 0
            for role in reversed(data["roles"]):
                if role["name"] in existing:
                    continue
                try:
                    await guild.create_role(
                        name=role["name"],
                        permissions=discord.Permissions(role["permissions"]),
                        colour=discord.Colour(role["color"]),
                        hoist=role["hoist"],
                        reason=f"Backup restore by {ctx.author}")
                    created += 1
                except discord.HTTPException:
                    continue
            self.record(guild.id, ctx.author.id, "Configuration restored")
            return await ctx.send(embed=self.embed(
                f"{TICK} Backup Restored",
                f"{ZARROW} **Roles Recreated:** `{created}`"))

        await ctx.send(f"{CROSS} Valid actions: `create`, `view`, `restore`.")

    @security.command(name="blacklist",
                      description="Manage the global user/server blacklist (bot owner only).")
    @app_commands.describe(action="add | remove | list",
                           target_id="User or server ID.")
    async def blacklist(self, ctx, action: str = "list", target_id: str = None,
                        *, reason: str = None):
        """Manage the global user/server blacklist (bot owner only)."""
        if ctx.author.id not in OWNER_IDS:
            return await ctx.send(f"{CROSS} This command is bot owner only.")
        action = action.lower()
        if action == "list":
            rows = self.db.execute(
                "SELECT target_id, kind, reason FROM sec_blacklist").fetchall()
            if not rows:
                return await ctx.send(f"{INFO} The global blacklist is empty.")
            return await ctx.send(embed=self.embed(
                f"{ZBAN} Global Blacklist ({len(rows)})",
                "\n".join(f"{ZARROW} `{r[0]}` — `{r[1]}` • {r[2] or 'No reason'}"
                          for r in rows[:20])))
        if not target_id:
            return await ctx.send(f"{CROSS} Provide a user or server ID.")
        if action == "add":
            kind = "guild" if self.bot.get_guild(int(target_id)) else "user"
            self.db.execute(
                "INSERT OR REPLACE INTO sec_blacklist (target_id, kind, reason) "
                "VALUES (?,?,?)", (target_id, kind, reason or "No reason"))
            self.db.commit()
            return await ctx.send(f"{TICK} `{target_id}` blacklisted as `{kind}`.")
        if action == "remove":
            self.db.execute("DELETE FROM sec_blacklist WHERE target_id=?",
                            (target_id, ))
            self.db.commit()
            return await ctx.send(f"{TICK} `{target_id}` removed from the blacklist.")
        await ctx.send(f"{CROSS} Valid actions: `add`, `remove`, `list`.")

    async def _trust(self, ctx, kind: str, action: str, target: str):
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send(f"{CROSS} You need administrator permission.")
        action = (action or "list").lower()
        if action not in TRUST_ACTIONS:
            return await ctx.send(f"{CROSS} Valid actions: `add`, `remove`, `list`.")

        if action == "list":
            rows = self.db.execute(
                "SELECT target_id FROM sec_trust WHERE guild_id=? AND kind=?",
                (str(ctx.guild.id), kind)).fetchall()
            if not rows:
                return await ctx.send(f"{INFO} No trusted {kind}s configured.")
            mention = "<@&{}>" if kind == "role" else "<@{}>"
            return await ctx.send(embed=self.embed(
                f"{ZSAFE} Trusted {kind.title()}s ({len(rows)})",
                "\n".join(f"{ZARROW} {mention.format(r[0])} (`{r[0]}`)"
                          for r in rows[:25])))

        if not target:
            return await ctx.send(f"{CROSS} Provide a {kind} mention or ID.")
        target_id = "".join(ch for ch in target if ch.isdigit())
        if not target_id:
            return await ctx.send(f"{CROSS} Invalid {kind} provided.")

        if action == "add":
            self.db.execute(
                "INSERT OR REPLACE INTO sec_trust (guild_id, kind, target_id) "
                "VALUES (?,?,?)", (str(ctx.guild.id), kind, target_id))
            text = f"{TICK} `{target_id}` added to the trusted {kind} list."
        else:
            self.db.execute(
                "DELETE FROM sec_trust WHERE guild_id=? AND kind=? AND target_id=?",
                (str(ctx.guild.id), kind, target_id))
            text = f"{CROSS} `{target_id}` removed from the trusted {kind} list."
        self.db.commit()
        self.record(ctx.guild.id, ctx.author.id, text)
        await ctx.send(embed=self.embed(f"{KING} Trust List Updated", text))

    @security.command(name="trustuser", description="Manage trusted users.")
    async def trustuser(self, ctx, action: str = "list", target: str = None):
        """Manage trusted users."""
        await self._trust(ctx, "user", action, target)

    @security.command(name="trustrole", description="Manage trusted roles.")
    async def trustrole(self, ctx, action: str = "list", target: str = None):
        """Manage trusted roles."""
        await self._trust(ctx, "role", action, target)

    @security.command(name="trustbot", description="Manage trusted bots.")
    async def trustbot(self, ctx, action: str = "list", target: str = None):
        """Manage trusted bots."""
        await self._trust(ctx, "bot", action, target)

    @commands.hybrid_command(name="health",
                             description="View the bot's live health status dashboard.")
    async def health(self, ctx):
        """View the bot's live health status dashboard."""
        uptime = int(time.time() - self.start_time)
        hours, rem = divmod(uptime, 3600)
        minutes, seconds = divmod(rem, 60)
        try:
            cpu = psutil.cpu_percent()
            memory = psutil.virtual_memory().percent
        except Exception:
            cpu = memory = 0.0
        await ctx.send(embed=self.embed(
            f"{THUNDER} Bot Health Status {NEW}",
            f"{ZARROW} **Latency:** `{round(self.bot.latency * 1000)}ms`\n"
            f"{ZARROW} **Uptime:** `{hours}h {minutes}m {seconds}s`\n"
            f"{ZARROW} **Guilds:** `{len(self.bot.guilds)}`\n"
            f"{ZARROW} **CPU:** `{cpu}%` • **RAM:** `{memory}%`\n"
            f"{ZARROW} **Python:** `{platform.python_version()}` • "
            f"**discord.py:** `{discord.__version__}`"))


async def setup(bot):
    await bot.add_cog(AdvancedSecurity(bot))
