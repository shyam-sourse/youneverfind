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

import discord
import json
import os
import datetime
from discord.ext import commands

from utils.emoji import ARROWRED, CROSS, REDRULESBOOK, TICK, ZBAN, ZWARNING
from utils.cv2 import CV2

BOOK = REDRULESBOOK
WARNING = ZWARNING
ARROW = ARROWRED

VALID_ACTIONS = ("kick", "ban", "mute", "delete")


class Honeypot(commands.Cog):
    """Honeypot / trap channel protection."""

    def __init__(self, bot):
        self.bot = bot
        self.data_file = "db/honeypot.json"
        os.makedirs("db", exist_ok=True)
        if not os.path.exists(self.data_file):
            with open(self.data_file, "w") as f:
                json.dump({}, f)
        try:
            with open(self.data_file, "r") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    # ---------------- storage helpers ----------------

    def save(self):
        with open(self.data_file, "w") as f:
            json.dump(self.data, f, indent=4)

    def guild_conf(self, guild_id):
        gid = str(guild_id)
        if gid not in self.data:
            self.data[gid] = {
                "enabled": False,
                "channels": [],
                "action": "kick",
                "reason": "Honeypot triggered — you sent a message in a trap channel.",
                "log": None,
                "whitelist": [],
            }
        return self.data[gid]

    def is_enabled(self, guild_id):
        return self.guild_conf(guild_id).get("enabled", False)

    # ---------------- embeds ----------------

    async def send_help_embed(self, ctx):
        await ctx.send(view=CV2(
            f"{ZBAN} Honeypot Commands",
            "Create trap channels — anyone who sends a message there is punished automatically.\n\n"
            "**honeypot enable/disable** — Enable or disable honeypot protection\n"
            "**honeypot add #channel** — Mark a channel as a honeypot trap\n"
            "**honeypot remove #channel** — Unmark a trap channel\n"
            "**honeypot action kick/ban/mute/delete** — Set the punishment\n"
            "**honeypot reason <text>** — Set the punishment reason\n"
            "**honeypot log #channel** — Set the log channel\n"
            "**honeypot whitelist add/remove @role|@user** — Immune roles/users\n"
            "**honeypot config** — View current settings\n"
            "**honeypot reset** — Reset all honeypot settings"
        ))

    async def not_enabled_embed(self, ctx):
        await ctx.send(view=CV2(
            f"{BOOK} Honeypot Settings For {ctx.guild.name}",
            f"**Current Status:** {CROSS} Disabled",
            "**How to Enable:** Use `honeypot enable` to enable honeypot protection."
        ))

    # ---------------- commands ----------------

    @commands.group(name="honeypot", aliases=["trap"], invoke_without_command=True)
    @commands.guild_only()
    async def honeypot(self, ctx):
        if not self.is_enabled(ctx.guild.id):
            return await self.not_enabled_embed(ctx)
        await self.send_help_embed(ctx)

    @honeypot.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def hp_enable(self, ctx):
        conf = self.guild_conf(ctx.guild.id)
        if conf["enabled"]:
            return await ctx.send(view=CV2(f"{WARNING} Honeypot", "Honeypot is already **enabled** in this server."))
        conf["enabled"] = True
        self.save()
        await ctx.send(view=CV2(
            f"{TICK} Honeypot Enabled",
            f"{ARROW} Add a trap channel with `honeypot add #channel`.\n"
            f"{ARROW} Current action: **{conf['action']}**"
        ))

    @honeypot.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def hp_disable(self, ctx):
        conf = self.guild_conf(ctx.guild.id)
        if not conf["enabled"]:
            return await ctx.send(view=CV2(f"{WARNING} Honeypot", "Honeypot is already **disabled**."))
        conf["enabled"] = False
        self.save()
        await ctx.send(view=CV2(f"{TICK} Honeypot Disabled", "Honeypot protection has been turned off."))

    @honeypot.command(name="add")
    @commands.has_permissions(administrator=True)
    async def hp_add(self, ctx, channel: discord.TextChannel):
        conf = self.guild_conf(ctx.guild.id)
        if channel.id in conf["channels"]:
            return await ctx.send(view=CV2(f"{WARNING} Honeypot", f"{channel.mention} is already a honeypot channel."))
        conf["channels"].append(channel.id)
        self.save()
        await ctx.send(view=CV2(
            f"{TICK} Honeypot Channel Added",
            f"{ARROW} {channel.mention} is now a trap channel.\n"
            f"{ARROW} Anyone who talks there will be **{conf['action']}**ed."
        ))

    @honeypot.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def hp_remove(self, ctx, channel: discord.TextChannel):
        conf = self.guild_conf(ctx.guild.id)
        if channel.id not in conf["channels"]:
            return await ctx.send(view=CV2(f"{CROSS} Honeypot", f"{channel.mention} is not a honeypot channel."))
        conf["channels"].remove(channel.id)
        self.save()
        await ctx.send(view=CV2(f"{TICK} Honeypot Channel Removed", f"{ARROW} {channel.mention} is no longer a trap channel."))

    @honeypot.command(name="action")
    @commands.has_permissions(administrator=True)
    async def hp_action(self, ctx, action: str = None):
        conf = self.guild_conf(ctx.guild.id)
        if action is None or action.lower() not in VALID_ACTIONS:
            return await ctx.send(view=CV2(
                f"{WARNING} Honeypot Action",
                f"**Current:** `{conf['action']}`",
                "**Valid options:** `kick`, `ban`, `mute`, `delete`"
            ))
        conf["action"] = action.lower()
        self.save()
        await ctx.send(view=CV2(f"{TICK} Honeypot Action Updated", f"{ARROW} Action set to **{conf['action']}**."))

    @honeypot.command(name="reason")
    @commands.has_permissions(administrator=True)
    async def hp_reason(self, ctx, *, reason: str = None):
        conf = self.guild_conf(ctx.guild.id)
        if not reason:
            return await ctx.send(view=CV2(f"{WARNING} Honeypot Reason", f"**Current reason:**\n{conf['reason']}"))
        conf["reason"] = reason[:400]
        self.save()
        await ctx.send(view=CV2(f"{TICK} Honeypot Reason Updated", f"{ARROW} {conf['reason']}"))

    @honeypot.command(name="log")
    @commands.has_permissions(administrator=True)
    async def hp_log(self, ctx, channel: discord.TextChannel = None):
        conf = self.guild_conf(ctx.guild.id)
        conf["log"] = channel.id if channel else None
        self.save()
        if channel:
            await ctx.send(view=CV2(f"{TICK} Honeypot Log Set", f"{ARROW} Logs will be sent to {channel.mention}."))
        else:
            await ctx.send(view=CV2(f"{TICK} Honeypot Log Cleared", "Honeypot logging has been disabled."))

    @honeypot.group(name="whitelist", aliases=["wl"], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def hp_whitelist(self, ctx):
        conf = self.guild_conf(ctx.guild.id)
        if not conf["whitelist"]:
            return await ctx.send(view=CV2(
                f"{BOOK} Honeypot Whitelist",
                "No roles or users are whitelisted.",
                "Use `honeypot whitelist add @role` to add one."
            ))
        entries = []
        for _id in conf["whitelist"]:
            role = ctx.guild.get_role(_id)
            member = ctx.guild.get_member(_id)
            entries.append(role.mention if role else (member.mention if member else f"`{_id}`"))
        await ctx.send(view=CV2(f"{BOOK} Honeypot Whitelist", "\n".join(f"{ARROW} {e}" for e in entries)))

    @hp_whitelist.command(name="add")
    @commands.has_permissions(administrator=True)
    async def hp_wl_add(self, ctx, target: discord.Role | discord.Member):
        conf = self.guild_conf(ctx.guild.id)
        if target.id in conf["whitelist"]:
            return await ctx.send(view=CV2(f"{WARNING} Honeypot Whitelist", f"{target.mention} is already whitelisted."))
        conf["whitelist"].append(target.id)
        self.save()
        await ctx.send(view=CV2(f"{TICK} Honeypot Whitelist", f"{ARROW} {target.mention} is now immune to honeypot traps."))

    @hp_whitelist.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def hp_wl_remove(self, ctx, target: discord.Role | discord.Member):
        conf = self.guild_conf(ctx.guild.id)
        if target.id not in conf["whitelist"]:
            return await ctx.send(view=CV2(f"{CROSS} Honeypot Whitelist", f"{target.mention} is not whitelisted."))
        conf["whitelist"].remove(target.id)
        self.save()
        await ctx.send(view=CV2(f"{TICK} Honeypot Whitelist", f"{ARROW} {target.mention} removed from the whitelist."))

    @honeypot.command(name="config", aliases=["settings"])
    @commands.has_permissions(administrator=True)
    async def hp_config(self, ctx):
        conf = self.guild_conf(ctx.guild.id)
        channels = ", ".join(f"<#{c}>" for c in conf["channels"]) or "None"
        log = f"<#{conf['log']}>" if conf["log"] else "None"
        wl = ", ".join(f"<@&{i}>" for i in conf["whitelist"]) or "None"
        await ctx.send(view=CV2(
            f"{ZBAN} Honeypot Settings For {ctx.guild.name}",
            f"**Status:** {TICK + ' Enabled' if conf['enabled'] else CROSS + ' Disabled'}\n"
            f"**Action:** `{conf['action']}`\n"
            f"**Trap Channels:** {channels}\n"
            f"**Log Channel:** {log}\n"
            f"**Whitelist:** {wl}",
            f"**Reason:** {conf['reason']}"
        ))

    @honeypot.command(name="reset")
    @commands.has_permissions(administrator=True)
    async def hp_reset(self, ctx):
        self.data.pop(str(ctx.guild.id), None)
        self.save()
        await ctx.send(view=CV2(f"{TICK} Honeypot Reset", "All honeypot settings have been cleared."))

    # ---------------- listener ----------------

    async def log_hit(self, guild, conf, member, channel, action, success, error=None):
        if not conf.get("log"):
            return
        log_channel = guild.get_channel(conf["log"])
        if not log_channel:
            return
        status = f"{TICK} {action}" if success else f"{CROSS} failed ({error})"
        try:
            await log_channel.send(view=CV2(
                f"{ZBAN} Honeypot Triggered",
                f"**User:** {member} (`{member.id}`)\n"
                f"**Channel:** {channel.mention}\n"
                f"**Action:** {status}\n"
                f"**Time:** <t:{int(datetime.datetime.now().timestamp())}:R>",
                f"**Reason:** {conf['reason']}"
            ))
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        conf = self.data.get(str(message.guild.id))
        if not conf or not conf.get("enabled"):
            return
        if message.channel.id not in conf.get("channels", []):
            return

        member = message.author
        if not isinstance(member, discord.Member):
            return

        # immunity checks
        if member.id == message.guild.owner_id or member.guild_permissions.administrator:
            return
        wl = conf.get("whitelist", [])
        if member.id in wl or any(r.id in wl for r in member.roles):
            return

        try:
            await message.delete()
        except Exception:
            pass

        action = conf.get("action", "kick")
        reason = conf.get("reason", "Honeypot triggered.")

        if action == "delete":
            return await self.log_hit(message.guild, conf, member, message.channel, "message deleted", True)

        try:
            await member.send(f"You were **{action}ed** from **{message.guild.name}**.\nReason: {reason}")
        except Exception:
            pass

        try:
            if action == "kick":
                await member.kick(reason=reason)
            elif action == "ban":
                await member.ban(reason=reason, delete_message_days=1)
            elif action == "mute":
                until = discord.utils.utcnow() + datetime.timedelta(days=7)
                await member.timeout(until, reason=reason)
            await self.log_hit(message.guild, conf, member, message.channel, action, True)
        except Exception as e:
            await self.log_hit(message.guild, conf, member, message.channel, action, False, str(e))
