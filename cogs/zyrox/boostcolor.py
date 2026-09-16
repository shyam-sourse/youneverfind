import discord
from discord.ext import commands


class _boostcolor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    """Booster colour commands"""

    def help_custom(self):
        emoji = "💎"
        label = "Booster Colour"
        description = "Boosters can change their own role colour"
        return emoji, label, description

    @commands.group()
    async def __BoostColor__(self, ctx: commands.Context):
        """`boostcolor` , `boostcolor enable` , `boostcolor disable` , `boostcolor set` , `boostcolor random` , `boostcolor name` , `boostcolor show` , `boostcolor remove` , `boostcolor colors` , `boostcolor list` , `boostcolor clear`"""
        pass
