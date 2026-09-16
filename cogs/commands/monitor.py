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
import sys
import asyncio
import time
import datetime
import psutil
import aiosqlite
import discord
from discord.ui import LayoutView, TextDisplay, Separator, Container, ActionRow, Select
from discord.ext import commands
from utils.Tools import blacklist_check, ignore_check
from utils.emoji import (
    CHANNEL, CROSS, DISABLE, ENABLE, HEARTS, HOME, INFO, LOADING, ONLINE,
    RED_BUTTON, RED_PIN, SYSTEM, THUNDER, TICK, UPTIME,
    ZYROX_COMMAND, ZYROXCONNECTION, ZYROX_GLOBAL, ZYROXSYS
)
from utils.cv2 import CV2, CV2Embed
from utils.config import *

color = 0xFF0000


def get_health_data(bot):
    """Collect live bot health data."""
    uptime = str(
        datetime.timedelta(seconds=int(round(time.time() - bot.start_time)))
    ) if getattr(bot, "start_time", None) else "Unknown"

    total_users = sum(g.member_count for g in bot.guilds if g.member_count)
    all_cmds = len(set(bot.walk_commands()))
    slash_cmds = len(bot.tree.get_commands())

    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory().percent
    disk = psutil.disk_usage(os.getcwd()).percent

    net = psutil.net_io_counters()
    net_mb = (net.bytes_recv + net.bytes_sent) / (1024 * 1024)

    return {
        "guilds": len(bot.guilds),
        "users": total_users,
        "uptime": uptime,
        "cpu": cpu,
        "ram": ram,
        "disk": disk,
        "net": net_mb,
        "all_cmds": all_cmds,
        "slash_cmds": slash_cmds,
        "ping": round(bot.latency * 1000, 1),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "discord": discord.__version__,
    }


def create_monitor_content(data, selected):
    content_map = {
        "Quick Overview": (
            f"**{ONLINE} Quick Overview**\n\n"
            f"**Ping**: `{data['ping']}ms`\n"
            f"**Uptime**: `{data['uptime']}`\n"
            f"**Servers**: `{data['guilds']}`\n"
            f"**Users**: `{data['users']}`\n\n"
            f"_Use the dropdown to view more health stats._"
        ),
        "System Usage": (
            f"**{ZYROXSYS} Hardware**\n"
            f"CPU Usage: **{data['cpu']}%**\n"
            f"RAM Usage: **{data['ram']}%**\n"
            f"Disk Usage: **{data['disk']}%**\n\n"
            f"**{ZYROXCONNECTION} Network**\n"
            f"Total Traffic: **{data['net']:.2f} MB**"
        ),
        "Bot Info": (
            f"**{UPTIME} Uptime**: `{data['uptime']}`\n\n"
            f"**{ZYROX_GLOBAL} Server Stats**\n"
            f"Servers: **{data['guilds']}**\n"
            f"Users: **{data['users']}**\n\n"
            f"**{ZYROX_COMMAND} Commands**\n"
            f"Total Commands: **{data['all_cmds']}**\n"
            f"Slash Commands: **{data['slash_cmds']}**"
        ),
        "Versions": (
            f"**{SYSTEM} Software**\n"
            f"Python: **{data['python']}**\n"
            f"Discord.py: **{data['discord']}**"
        ),
    }
    return content_map.get(selected, "")


class MonitorView(LayoutView):
    def __init__(self, ctx, data):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.data = data

        self.select = Select(
            placeholder=f"{BRAND_NAME} Health Monitor",
            options=[
                discord.SelectOption(label="Quick Overview", emoji=ONLINE, description="Quick health overview"),
                discord.SelectOption(label="System Usage", emoji=ZYROXSYS, description="CPU / RAM / Disk / Network"),
                discord.SelectOption(label="Bot Info", emoji=ZYROX_GLOBAL, description="Servers / users / commands"),
                discord.SelectOption(label="Versions", emoji=SYSTEM, description="Software versions"),
            ],
        )
        self.select.callback = self.on_select

        self.add_item(
            Container(
                TextDisplay(f"**{THUNDER} {BRAND_NAME} Health Monitor**"),
                Separator(visible=True),
                TextDisplay(create_monitor_content(data, "Quick Overview")),
                ActionRow(self.select),
            )
        )

    async def on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "Only the command invoker can use this menu.", ephemeral=True
            )
            return

        selected = interaction.data.get("values", ["Quick Overview"])[0]

        new_container = Container(
            TextDisplay(f"**{THUNDER} {BRAND_NAME} Health Monitor**"),
            Separator(visible=True),
            TextDisplay(create_monitor_content(self.data, selected)),
            ActionRow(self.select),
        )

        self.clear_items()
        self.add_item(new_container)

        await interaction.response.edit_message(view=self)


class Monitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
        self.monitor_messages = {}
        self.bot.start_time = self.start_time
        self.bot.loop.create_task(self.setup_database())
        self.update_task = self.bot.loop.create_task(self.update_loop())

    """Monitor commands"""

    def help_custom(self):
        emoji = ZYROXSYS
        label = "Monitor Commands"
        description = "Show you the commands of Monitor"
        return emoji, label, description

    async def setup_database(self):
        db_path = "db/monitor.db"
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS monitor_settings (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    enabled INTEGER DEFAULT 0
                )
                """
            )
            await db.commit()

    async def get_settings(self, guild_id):
        async with aiosqlite.connect("db/monitor.db") as db:
            cursor = await db.execute(
                "SELECT channel_id, enabled FROM monitor_settings WHERE guild_id = ?",
                (guild_id,),
            )
            row = await cursor.fetchone()
            return {"channel_id": row[0] if row else None, "enabled": bool(row[1]) if row else False}

    async def save_settings(self, guild_id, channel_id=None, enabled=None):
        async with aiosqlite.connect("db/monitor.db") as db:
            await db.execute(
                "INSERT OR REPLACE INTO monitor_settings (guild_id, channel_id, enabled) VALUES (?, ?, ?)",
                (guild_id, channel_id, enabled),
            )
            await db.commit()

    def monitor_embed(self, data):
        embed = CV2Embed(
            title=f"{THUNDER} {BRAND_NAME} Health Monitor",
            description=f"{ONLINE} **Status:** `Online`  {RED_BUTTON} **Ping:** `{data['ping']}ms`\n\n"
                        f"{UPTIME} **Uptime:** `{data['uptime']}`",
            color=color,
        )
        embed.add_field(
            name=f"{ZYROXSYS} System Usage",
            value=f"{INFO} CPU: **{data['cpu']}%**\n"
                  f"{RED_PIN} RAM: **{data['ram']}%**\n"
                  f"{SYSTEM} Disk: **{data['disk']}%**\n"
                  f"{ZYROXCONNECTION} Traffic: **{data['net']:.2f} MB**",
        )
        embed.add_field(
            name=f"{ZYROX_GLOBAL} Bot Stats",
            value=f"{HOME} Servers: **{data['guilds']}**\n"
                  f"{HEARTS} Users: **{data['users']}**\n"
                  f"{ZYROX_COMMAND} Commands: **{data['all_cmds']}**",
        )
        return embed

    async def refresh_monitor_message(self, guild_id):
        settings = await self.get_settings(guild_id)
        if not settings["enabled"] or not settings["channel_id"]:
            return

        channel = self.bot.get_channel(settings["channel_id"])
        if not channel:
            return

        data = get_health_data(self.bot)
        embed = self.monitor_embed(data)

        try:
            message = await channel.send(view=embed)
            self.monitor_messages[guild_id] = (channel.id, message.id)
        except discord.HTTPException:
            return

    @commands.group(name="monitor", invoke_without_command=True)
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def monitor(self, ctx):
        """`monitor`, `monitor channel`, `monitor enable`, `monitor disable`"""
        loading_embed = CV2(f"{LOADING} **Checking {BRAND_NAME} Health...**")
        loading_msg = await ctx.reply(view=loading_embed)

        data = get_health_data(self.bot)
        main_view = MonitorView(ctx, data)
        await loading_msg.edit(view=main_view)

    @monitor.command(name="channel")
    @commands.has_permissions(manage_channels=True)
    async def monitor_channel(self, ctx, channel: discord.TextChannel = None):
        """Set the monitor channel, or view the current one."""
        settings = await self.get_settings(ctx.guild.id)

        if channel is None:
            if settings["channel_id"]:
                status = f"{ENABLE} **Enabled**" if settings["enabled"] else f"{DISABLE} **Disabled**"
                view = CV2(
                    f"{CHANNEL} Monitor Channel",
                    f"**Channel:** <#{settings['channel_id']}>\n**Status:** {status}\n\n"
                    f"Use `{ctx.prefix}monitor channel #channel` to change it.",
                )
            else:
                view = CV2(
                    f"{CHANNEL} Monitor Channel",
                    f"No monitor channel set yet.\nUse `{ctx.prefix}monitor channel #channel` to add one.",
                )
            await ctx.send(view=view)
            return

        enabled = 1 if settings["enabled"] else 0
        await self.save_settings(ctx.guild.id, channel.id, enabled)
        view = CV2(
            f"{TICK} Monitor Channel Set",
            f"Health monitor channel successfully set to {channel.mention}!",
            f"Use `{ctx.prefix}monitor enable` to start live updates.",
        )
        await ctx.send(view=view)

    @monitor.command(name="enable")
    @commands.has_permissions(manage_channels=True)
    async def monitor_enable(self, ctx):
        """Enable the health monitor in the configured channel."""
        settings = await self.get_settings(ctx.guild.id)

        if not settings["channel_id"]:
            view = CV2(
                f"{CROSS} Monitor Not Enabled",
                f"No monitor channel set yet!\nUse `{ctx.prefix}monitor channel #channel` first.",
            )
            await ctx.send(view=view)
            return

        if settings["enabled"]:
            view = CV2(
                f"{INFO} Already Enabled",
                f"The health monitor is already **enabled** in <#{settings['channel_id']}>.",
            )
            await ctx.send(view=view)
            return

        await self.save_settings(ctx.guild.id, settings["channel_id"], 1)
        await self.refresh_monitor_message(ctx.guild.id)

        view = CV2(
            f"{TICK} Monitor Enabled",
            f"Health monitor successfully enabled in <#{settings['channel_id']}>!",
            "I will keep the live health panel updated there.",
        )
        await ctx.send(view=view)

    @monitor.command(name="disable")
    @commands.has_permissions(manage_channels=True)
    async def monitor_disable(self, ctx):
        """Disable the health monitor."""
        settings = await self.get_settings(ctx.guild.id)

        if not settings["enabled"]:
            view = CV2(
                f"{INFO} Already Disabled",
                "The health monitor is already **disabled** in this server.",
            )
            await ctx.send(view=view)
            return

        await self.save_settings(ctx.guild.id, settings["channel_id"], 0)

        if ctx.guild.id in self.monitor_messages:
            del self.monitor_messages[ctx.guild.id]

        view = CV2(
            f"{CROSS} Monitor Disabled",
            "Health monitor successfully **disabled**.",
            "Use `{0}monitor enable` to turn it back on.".format(ctx.prefix),
        )
        await ctx.send(view=view)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        self.monitor_messages.pop(guild.id, None)

    async def update_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            for guild_id in list(self.monitor_messages.keys()):
                settings = await self.get_settings(guild_id)
                if settings["enabled"]:
                    await self.refresh_monitor_message(guild_id)
            await asyncio.sleep(60)


async def setup(bot):
    cog = Monitor(bot)
    await bot.add_cog(cog)
