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
from utils.emoji import BLACKCROWN
from discord.ext import commands


class _owner(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    """Owner commands"""

    owner_only = True

    def help_custom(self):
        emoji = BLACKCROWN
        label = "Owner Commands"
        description = "Show you the commands of Owner"
        return emoji, label, description

    @commands.group()
    async def __Owner__(self, ctx: commands.Context):
        """`staff_add` , `staff_remove` , `staff_list` , `slist` , `mutuals` , `getinvite` , `reload` , `sync` , `owners` , `dm` , `change` , `ownerban` , `ownerunban` , `globalunban` , `guildban` , `guildunban` , `leaveguild` , `guildinfo` , `servertour` , `forcepurgebots` , `forcepurgeuser` , `global` , `extraowner` , `bdg`"""
        pass
