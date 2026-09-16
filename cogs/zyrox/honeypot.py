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
from utils.emoji import ZBAN
from discord.ext import commands


class _honeypot(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    """Honeypot"""

    def help_custom(self):
        emoji = ZBAN
        label = "Honeypot"
        description = "Show you Commands of Honeypot"
        return emoji, label, description

    @commands.group()
    async def __Honeypot__(self, ctx: commands.Context):
        """`>honeypot`, `>honeypot enable/disable`, `>honeypot add/remove #channel`, `>honeypot action kick/ban/mute/delete`, `>honeypot reason <text>`, `>honeypot log #channel`, `>honeypot whitelist add/remove @role`, `>honeypot config`, `>honeypot reset`"""
