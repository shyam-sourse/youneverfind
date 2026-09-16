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
from utils.emoji import MESSAGE
from discord.ext import commands


class _leaderboard(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    """Leaderboard"""

    def help_custom(self):
        emoji = MESSAGE
        label = "Leaderboard"
        description = "Message + Voice Time leaderboards and the Top #1 role"
        return emoji, label, description

    @commands.group()
    async def __Leaderboard__(self, ctx: commands.Context):
        """`>lb`, `>lb daily/weekly/monthly/lifetime`, `>lb daily #channel`, `>lb server daily/weekly/monthly/lifetime`, `>lb me`, `>lb reset channel/server`"""

    @commands.group()
    async def __Voice_Time__(self, ctx: commands.Context):
        """`>lb vc daily/weekly/monthly/lifetime`, `>lb vc channel #voice daily/weekly/monthly/lifetime`, `>lb vc me`, `>lb vc reset`"""

    @commands.group()
    async def __Top_1_Role__(self, ctx: commands.Context):
        """`>lb role set @role messages daily/weekly/monthly/lifetime`, `>lb role set @role vc daily/weekly/monthly/lifetime`, `>lb role show`, `>lb role remove messages/vc`"""


async def setup(bot):
    await bot.add_cog(_leaderboard(bot))
