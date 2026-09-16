# ╔══════════════════════════════════════════════════════════════════╗
# ║   Booster Custom Colour  —  Server boosters pick their own       ║
# ║   role colour. Per-server enable / disable.                      ║
# ╚══════════════════════════════════════════════════════════════════╝

from __future__ import annotations

import random
import re

import aiosqlite
import discord
from discord.ext import commands

DB_PATH = "db/boostcolor.db"
RED = 0xFF0000

HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")

PRESETS = {
    "red": 0xFF0000,
    "crimson": 0xDC143C,
    "pink": 0xFF69B4,
    "orange": 0xFF8C00,
    "gold": 0xFFD700,
    "yellow": 0xFFFF00,
    "green": 0x2ECC71,
    "lime": 0x00FF7F,
    "cyan": 0x00FFFF,
    "blue": 0x3498DB,
    "navy": 0x2C3E50,
    "purple": 0x9B59B6,
    "violet": 0x8A2BE2,
    "magenta": 0xFF00FF,
    "white": 0xFFFFFE,
    "black": 0x010101,
    "grey": 0x95A5A6,
    "brown": 0x8B4513,
}


class BoostColor(commands.Cog):
    """Let server boosters manage their own colour role."""

    def __init__(self, bot):
        self.bot = bot
        self.color = RED
        self.bot.loop.create_task(self.setup_database())

    # ------------------------------------------------------------------ db
    async def setup_database(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS boostcolor_config (
                    guild_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0
                )"""
            )
            await db.execute(
                """CREATE TABLE IF NOT EXISTS boostcolor_roles (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                )"""
            )
            await db.commit()

    async def is_enabled(self, guild_id: int) -> bool:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT enabled FROM boostcolor_config WHERE guild_id = ?", (guild_id,)
            ) as cur:
                row = await cur.fetchone()
        return bool(row and row[0])

    async def set_enabled(self, guild_id: int, value: bool):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO boostcolor_config (guild_id, enabled) VALUES (?, ?)",
                (guild_id, int(value)),
            )
            await db.commit()

    async def get_role_id(self, guild_id: int, user_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT role_id FROM boostcolor_roles WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row else None

    async def save_role(self, guild_id: int, user_id: int, role_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO boostcolor_roles (guild_id, user_id, role_id) VALUES (?, ?, ?)",
                (guild_id, user_id, role_id),
            )
            await db.commit()

    async def drop_role(self, guild_id: int, user_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM boostcolor_roles WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            await db.commit()

    async def all_roles(self, guild_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT user_id, role_id FROM boostcolor_roles WHERE guild_id = ?",
                (guild_id,),
            ) as cur:
                return await cur.fetchall()

    # --------------------------------------------------------------- utils
    def embed(self, title: str, desc: str) -> discord.Embed:
        e = discord.Embed(title=title, description=desc, color=RED)
        return e

    @staticmethod
    def parse_color(value: str):
        value = value.strip().lower()
        if value in ("random", "rand"):
            return random.randint(0, 0xFFFFFF)
        if value in PRESETS:
            return PRESETS[value]
        m = HEX_RE.match(value)
        if m:
            return int(m.group(1), 16)
        return None

    async def ensure_booster(self, ctx) -> bool:
        if not await self.is_enabled(ctx.guild.id):
            await ctx.reply(
                embed=self.embed(
                    "❌ Disabled",
                    "Booster colours are **disabled** in this server.\n"
                    "An admin can turn it on with `boostcolor enable`.",
                )
            )
            return False
        if ctx.author.premium_since is None and not ctx.author.guild_permissions.administrator:
            await ctx.reply(
                embed=self.embed(
                    "💎 Boosters Only",
                    "This feature is only for **server boosters**.\n"
                    "Boost the server to unlock your own custom colour role!",
                )
            )
            return False
        if not ctx.guild.me.guild_permissions.manage_roles:
            await ctx.reply(
                embed=self.embed("❌ Missing Permission", "I need the **Manage Roles** permission.")
            )
            return False
        return True

    async def lift_role(self, ctx, role):
        """Move the personal colour role above every other role the member has,
        so it is the one that actually colours their nickname."""
        try:
            me_top = ctx.guild.me.top_role.position
            highest_other = 0
            for r in ctx.author.roles:
                if r.id == role.id or r.is_default():
                    continue
                if r.position > highest_other:
                    highest_other = r.position
            target = min(highest_other + 1, me_top - 1)
            target = max(target, 1)
            if role.position != target:
                await role.edit(position=target, reason="Booster colour role position")
        except discord.HTTPException:
            pass

    async def get_or_create_role(self, ctx, color: int):
        role_id = await self.get_role_id(ctx.guild.id, ctx.author.id)
        role = ctx.guild.get_role(role_id) if role_id else None
        if role is None:
            role = await ctx.guild.create_role(
                name=ctx.author.display_name,
                colour=discord.Colour(color),
                reason="Booster custom colour",
            )
            await self.save_role(ctx.guild.id, ctx.author.id, role.id)
        else:
            await role.edit(colour=discord.Colour(color), reason="Booster custom colour")
        if role not in ctx.author.roles:
            await ctx.author.add_roles(role, reason="Booster custom colour")
        # always re-position after assigning (new roles land at the bottom)
        await self.lift_role(ctx, role)
        return role


    # ------------------------------------------------------------ commands
    @commands.group(
        name="boostcolor",
        aliases=["bcolor", "boostercolor", "bc"],
        invoke_without_command=True,
        help="Booster custom role colour system",
    )
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def boostcolor(self, ctx):
        enabled = await self.is_enabled(ctx.guild.id)
        status = "🟢 Enabled" if enabled else "🔴 Disabled"
        e = self.embed(
            "💎 Booster Colour",
            f"**Status:** {status}\n\n"
            "Server boosters can create and recolour their **own personal role**.",
        )
        e.add_field(
            name="🎨 Booster Commands",
            value=(
                "`boostcolor set <hex/name>` • set your colour\n"
                "`boostcolor random` • surprise colour\n"
                "`boostcolor name <text>` • rename your role\n"
                "`boostcolor show` • view your colour role\n"
                "`boostcolor remove` • delete your colour role\n"
                "`boostcolor colors` • list preset colour names"
            ),
            inline=False,
        )
        e.add_field(
            name="🛠️ Admin Commands",
            value=(
                "`boostcolor enable` • turn the system on\n"
                "`boostcolor disable` • turn the system off\n"
                "`boostcolor list` • all booster colour roles\n"
                "`boostcolor clear` • delete every booster colour role"
            ),
            inline=False,
        )
        e.set_footer(text="Example: boostcolor set #ff0000")
        await ctx.reply(embed=e)

    @boostcolor.command(name="enable", help="Enable the booster colour system")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def bc_enable(self, ctx):
        if await self.is_enabled(ctx.guild.id):
            return await ctx.reply(
                embed=self.embed("⚠️ Already Enabled", "Booster colours are already **enabled**.")
            )
        await self.set_enabled(ctx.guild.id, True)
        await ctx.reply(
            embed=self.embed(
                "✅ Enabled",
                "Server boosters can now use `boostcolor set <hex>` to pick their own role colour.",
            )
        )

    @boostcolor.command(name="disable", help="Disable the booster colour system")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def bc_disable(self, ctx):
        if not await self.is_enabled(ctx.guild.id):
            return await ctx.reply(
                embed=self.embed("⚠️ Already Disabled", "Booster colours are already **disabled**.")
            )
        await self.set_enabled(ctx.guild.id, False)
        await ctx.reply(
            embed=self.embed(
                "🔴 Disabled",
                "Booster colour commands are now turned off. Existing roles were kept — use "
                "`boostcolor clear` to delete them.",
            )
        )

    @boostcolor.command(name="set", aliases=["color", "colour"], help="Set your booster role colour")
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def bc_set(self, ctx, *, value: str):
        if not await self.ensure_booster(ctx):
            return
        color = self.parse_color(value)
        if color is None:
            return await ctx.reply(
                embed=self.embed(
                    "❌ Invalid Colour",
                    "Give me a hex code like `#ff0000` or a preset name.\n"
                    "Use `boostcolor colors` to see all presets.",
                )
            )
        try:
            role = await self.get_or_create_role(ctx, color)
        except discord.Forbidden:
            return await ctx.reply(
                embed=self.embed("❌ Failed", "My role must be **above** your colour role.")
            )
        e = self.embed(
            "🎨 Colour Updated",
            f"{role.mention} is now **#{color:06X}**.",
        )
        e.colour = discord.Colour(color)
        await ctx.reply(embed=e)

    @boostcolor.command(name="random", help="Get a random booster role colour")
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def bc_random(self, ctx):
        await ctx.invoke(self.bc_set, value="random")

    @boostcolor.command(name="name", aliases=["rename"], help="Rename your booster colour role")
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def bc_name(self, ctx, *, name: str):
        if not await self.ensure_booster(ctx):
            return
        if len(name) > 32:
            return await ctx.reply(
                embed=self.embed("❌ Too Long", "Role names can be at most **32** characters.")
            )
        role_id = await self.get_role_id(ctx.guild.id, ctx.author.id)
        role = ctx.guild.get_role(role_id) if role_id else None
        if role is None:
            return await ctx.reply(
                embed=self.embed(
                    "❌ No Role", "You don't have a colour role yet — use `boostcolor set <hex>`."
                )
            )
        try:
            await role.edit(name=name, reason="Booster custom colour rename")
        except discord.Forbidden:
            return await ctx.reply(
                embed=self.embed("❌ Failed", "My role must be **above** your colour role.")
            )
        await ctx.reply(embed=self.embed("✏️ Renamed", f"Your role is now **{name}**."))

    @boostcolor.command(name="show", aliases=["view", "my"], help="Show your booster colour role")
    @commands.guild_only()
    async def bc_show(self, ctx):
        role_id = await self.get_role_id(ctx.guild.id, ctx.author.id)
        role = ctx.guild.get_role(role_id) if role_id else None
        if role is None:
            return await ctx.reply(
                embed=self.embed("💤 Nothing Yet", "You don't have a booster colour role.")
            )
        e = self.embed(
            "🎨 Your Colour Role",
            f"**Role:** {role.mention}\n**Hex:** `#{role.colour.value:06X}`",
        )
        e.colour = role.colour
        await ctx.reply(embed=e)

    @boostcolor.command(name="remove", aliases=["delete"], help="Delete your booster colour role")
    @commands.guild_only()
    async def bc_remove(self, ctx):
        role_id = await self.get_role_id(ctx.guild.id, ctx.author.id)
        role = ctx.guild.get_role(role_id) if role_id else None
        if role is not None:
            try:
                await role.delete(reason="Booster colour removed")
            except discord.HTTPException:
                pass
        await self.drop_role(ctx.guild.id, ctx.author.id)
        await ctx.reply(embed=self.embed("🗑️ Removed", "Your booster colour role has been deleted."))

    @boostcolor.command(name="colors", aliases=["colours", "presets"], help="List preset colours")
    @commands.guild_only()
    async def bc_colors(self, ctx):
        listing = " • ".join(f"`{n}`" for n in PRESETS)
        await ctx.reply(
            embed=self.embed(
                "🌈 Preset Colours", f"{listing}\n\nOr use any hex code, e.g. `boostcolor set #ff4757`."
            )
        )

    @boostcolor.command(name="list", help="List all booster colour roles")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def bc_list(self, ctx):
        rows = await self.all_roles(ctx.guild.id)
        lines = []
        for user_id, role_id in rows:
            role = ctx.guild.get_role(role_id)
            if role:
                lines.append(f"<@{user_id}> → {role.mention} `#{role.colour.value:06X}`")
        if not lines:
            return await ctx.reply(
                embed=self.embed("📭 Empty", "No booster colour roles have been created yet.")
            )
        await ctx.reply(embed=self.embed("💎 Booster Colour Roles", "\n".join(lines[:25])))

    @boostcolor.command(name="clear", help="Delete every booster colour role")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def bc_clear(self, ctx):
        rows = await self.all_roles(ctx.guild.id)
        deleted = 0
        for user_id, role_id in rows:
            role = ctx.guild.get_role(role_id)
            if role:
                try:
                    await role.delete(reason="Booster colours cleared")
                    deleted += 1
                except discord.HTTPException:
                    pass
            await self.drop_role(ctx.guild.id, user_id)
        await ctx.reply(embed=self.embed("🧹 Cleared", f"Deleted **{deleted}** colour role(s)."))

    # ------------------------------------------------------------ listener
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.premium_since is not None and after.premium_since is None:
            role_id = await self.get_role_id(after.guild.id, after.id)
            if role_id:
                role = after.guild.get_role(role_id)
                if role:
                    try:
                        await role.delete(reason="No longer boosting")
                    except discord.HTTPException:
                        pass
                await self.drop_role(after.guild.id, after.id)


async def setup(bot):
    await bot.add_cog(BoostColor(bot))
