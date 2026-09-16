from discord.ext import commands, tasks
import datetime
from discord.ui import Button, Select, View
import aiosqlite
import random
import typing
import sqlite3
import asyncio
import discord
import logging
from utils.emoji import ARROWRED, TADAA, TICK
from discord.utils import get
from utils.Tools import *
import os
import aiohttp
from utils.cv2 import CV2


db_folder = "db"
db_file = "giveaways.db"
db_path = os.path.join(db_folder, db_file)

# Make sure db folder exists
os.makedirs(db_folder, exist_ok=True)

# Create database/table
connection = sqlite3.connect(db_path)
cursor = connection.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS Giveaway (
    guild_id INTEGER,
    host_id INTEGER,
    start_time TIMESTAMP,
    ends_at TIMESTAMP,
    prize TEXT,
    winners INTEGER,
    message_id INTEGER,
    channel_id INTEGER,
    PRIMARY KEY (guild_id, message_id)
)
""")

connection.commit()
connection.close()


def WinnerConverter(winner):
    try:
        return int(winner)
    except ValueError:
        try:
            return int(winner[:-1])
        except Exception:
            return -4


class Giveaway(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    # =========================================================
    # TIME CONVERTER
    # Supports:
    # s = seconds
    # m = minutes
    # h = hours
    # d = days
    # y = years
    #
    # Examples:
    # 10s
    # 30m
    # 5h
    # 7d
    # 100y
    # =========================================================

    def convert(self, time):
        if not time:
            return -1

        time = str(time).strip().lower()

        pos = ["s", "m", "h", "d", "y"]

        time_dict = {
            "s": 1,
            "m": 60,
            "h": 3600,
            "d": 86400,
            "y": 31536000
        }

        unit = time[-1]

        if unit not in pos:
            return -1

        try:
            val = int(time[:-1])
        except ValueError:
            return -2

        if val <= 0:
            return -2

        return val * time_dict[unit]

    # =========================================================
    # COG LOAD
    # =========================================================

    async def cog_load(self):
        self.connection = await aiosqlite.connect(db_path)
        self.cursor = await self.connection.cursor()

        await self.check_for_ended_giveaways()

        self.GiveawayEnd.start()

    # =========================================================
    # COG UNLOAD
    # =========================================================

    async def cog_unload(self):
        if self.GiveawayEnd.is_running():
            self.GiveawayEnd.cancel()

        await self.connection.close()

    # =========================================================
    # CHECK ENDED GIVEAWAYS
    # =========================================================

    async def check_for_ended_giveaways(self):

        await self.cursor.execute(
            """
            SELECT ends_at, guild_id, message_id, host_id,
                   winners, prize, channel_id
            FROM Giveaway
            WHERE ends_at <= ?
            """,
            (datetime.datetime.now().timestamp(),)
        )

        ended_giveaways = await self.cursor.fetchall()

        for giveaway in ended_giveaways:
            await self.end_giveaway(giveaway)

    # =========================================================
    # END GIVEAWAY
    # =========================================================

    async def end_giveaway(self, giveaway):

        try:
            current_time = datetime.datetime.now().timestamp()

            guild = self.bot.get_guild(int(giveaway[1]))

            if guild is None:
                await self.cursor.execute(
                    "DELETE FROM Giveaway WHERE message_id = ? AND guild_id = ?",
                    (giveaway[2], giveaway[1])
                )

                await self.connection.commit()
                return

            channel = self.bot.get_channel(int(giveaway[6]))

            if channel is None:
                return

            try:
                retries = 3
                message = None

                for attempt in range(retries):

                    try:
                        message = await channel.fetch_message(
                            int(giveaway[2])
                        )
                        break

                    except discord.NotFound:

                        await self.cursor.execute(
                            """
                            DELETE FROM Giveaway
                            WHERE message_id = ? AND guild_id = ?
                            """,
                            (giveaway[2], giveaway[1])
                        )

                        await self.connection.commit()
                        return

                    except aiohttp.ClientResponseError as e:

                        if e.status == 503:

                            if attempt < retries - 1:
                                await asyncio.sleep(2 ** attempt)
                                continue

                            raise

                        raise

                if message is None:
                    return

                # Get reaction users
                if not message.reactions:
                    users = []
                else:
                    users = [
                        i.id async for i in message.reactions[0].users()
                    ]

                # Remove bot
                if self.bot.user.id in users:
                    users.remove(self.bot.user.id)

                # No participants
                if len(users) < 1:

                    await message.reply(
                        f"No one won the **{giveaway[5]}** giveaway, "
                        f"due to not enough participants."
                    )

                    await self.cursor.execute(
                        """
                        DELETE FROM Giveaway
                        WHERE message_id = ? AND guild_id = ?
                        """,
                        (message.id, message.guild.id)
                    )

                    await self.connection.commit()
                    return

                # Calculate winners
                winners_count = min(
                    len(users),
                    int(giveaway[4])
                )

                winner = ", ".join(
                    f"<@!{i}>"
                    for i in random.sample(
                        users,
                        k=winners_count
                    )
                )

                desc = (
                    f"Ended at <t:{int(current_time)}:R>\n"
                    f"Hosted by <@{int(giveaway[3])}>\n"
                    f"Winner(s): {winner}"
                )

                view = CV2(
                    f"{giveaway[5]}",
                    desc
                )

                # Components V2: NO content=
                await message.edit(view=view)

                await message.reply(
                    f"{TADAA} Congrats {winner}, "
                    f"you won **{giveaway[5]}!**, "
                    f"Hosted by <@{int(giveaway[3])}>"
                )

                await self.cursor.execute(
                    """
                    DELETE FROM Giveaway
                    WHERE message_id = ? AND guild_id = ?
                    """,
                    (message.id, message.guild.id)
                )

                await self.connection.commit()

            except (
                discord.HTTPException,
                aiohttp.ClientResponseError
            ) as e:

                logging.error(
                    f"Error ending giveaway: {e}"
                )

        except IndexError:

            logging.error(
                f"Giveaway data is corrupted or missing: {giveaway}"
            )

            await self.cursor.execute(
                """
                DELETE FROM Giveaway
                WHERE message_id = ? AND guild_id = ?
                """,
                (giveaway[2], giveaway[1])
            )

            await self.connection.commit()

    # =========================================================
    # GIVEAWAY LOOP
    # =========================================================

    @tasks.loop(seconds=5)
    async def GiveawayEnd(self):

        await self.cursor.execute(
            """
            SELECT ends_at, guild_id, message_id,
                   host_id, winners, prize, channel_id
            FROM Giveaway
            WHERE ends_at <= ?
            """,
            (datetime.datetime.now().timestamp(),)
        )

        ends_raw = await self.cursor.fetchall()

        for giveaway in ends_raw:
            await self.end_giveaway(giveaway)

    # =========================================================
    # GSTART
    # =========================================================

    @commands.hybrid_command(
        description="Starts a new giveaway."
    )
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(
        1,
        5,
        commands.BucketType.user
    )
    @commands.has_guild_permissions(
        manage_guild=True
    )
    async def gstart(
        self,
        ctx,
        time,
        winners: int,
        *,
        prize: str
    ):

        await self.cursor.execute(
            """
            SELECT message_id, channel_id
            FROM Giveaway
            WHERE guild_id = ?
            """,
            (ctx.guild.id,)
        )

        re = await self.cursor.fetchall()

        # Maximum 15 winners
        if winners > 15:

            message = await ctx.send(
                view=CV2(
                    "⚠️ Access Denied",
                    "Cannot exceed more than 15 winners."
                )
            )

            await asyncio.sleep(5)
            await message.delete()
            return

        # Maximum 5 active giveaways
        g_list = [i[0] for i in re]

        if len(g_list) >= 5:

            message = await ctx.send(
                view=CV2(
                    "⚠️ Access Denied",
                    "You can only host upto 5 giveaways in this Guild."
                )
            )

            await asyncio.sleep(5)
            await message.delete()
            return

        # Convert time
        converted = self.convert(time)

        if converted == -1:

            message = await ctx.send(
                view=CV2(
                    "❌ Error",
                    "Invalid time format."
                )
            )

            await asyncio.sleep(5)
            await message.delete()
            return

        if converted == -2:

            message = await ctx.send(
                view=CV2(
                    "❌ Error",
                    "Invalid time format. Please provide the time in numbers."
                )
            )

            await asyncio.sleep(5)
            await message.delete()
            return

        # Calculate end time
        ends = (
            datetime.datetime.now().timestamp()
            + converted
        )

        desc = (
            f"{ARROWRED} Winner(s): **{winners}**\n"
            f"{ARROWRED} Hosted by {ctx.author.mention}\n"
            f"{ARROWRED} Ends <t:{round(ends)}:R> "
            f"(<t:{round(ends)}:f>)\n\n"
            f"{ARROWRED} React with {TADAA} to participate!"
        )

        view = CV2(
            f"{TADAA} {prize}",
            desc
        )

        # Components V2 compatible
        message = await ctx.send(view=view)

        try:
            await ctx.message.delete()
        except Exception:
            pass

        # Save giveaway
        await self.cursor.execute(
            """
            INSERT INTO Giveaway(
                guild_id,
                host_id,
                start_time,
                ends_at,
                prize,
                winners,
                message_id,
                channel_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ctx.guild.id,
                ctx.author.id,
                datetime.datetime.now(),
                ends,
                prize,
                winners,
                message.id,
                ctx.channel.id
            )
        )

        # Add reaction
        await message.add_reaction(TADAA)

        await self.connection.commit()

    # =========================================================
    # DELETE GIVEAWAY MESSAGE
    # =========================================================

    @commands.Cog.listener("on_message_delete")
    async def GiveawayMessageDelete(
        self,
        message
    ):

        if message.guild is None:
            return

        if message.author != self.bot.user:
            return

        await self.cursor.execute(
            """
            SELECT message_id
            FROM Giveaway
            WHERE guild_id = ?
            """,
            (message.guild.id,)
        )

        re = await self.cursor.fetchone()

        if re is not None:

            if message.id == int(re[0]):

                await self.cursor.execute(
                    """
                    DELETE FROM Giveaway
                    WHERE channel_id = ?
                    AND message_id = ?
                    AND guild_id = ?
                    """,
                    (
                        message.channel.id,
                        message.id,
                        message.guild.id
                    )
                )

                print(
                    f"Giveaway message deleted in "
                    f"{message.guild.name} - "
                    f"{message.guild.id}"
                )

                await self.connection.commit()

    # =========================================================
    # GEND
    # =========================================================

    @commands.hybrid_command(
        name="gend",
        description="Ends a giveaway before its ending time.",
        help="Ends a giveaway before its ending time."
    )
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(
        1,
        5,
        commands.BucketType.user
    )
    @commands.has_guild_permissions(
        manage_guild=True
    )
    async def gend(
        self,
        ctx,
        message_id=None
    ):

        if message_id:

            try:
                int(message_id)

            except ValueError:

                message = await ctx.send(
                    view=CV2(
                        "⚠️ Access Denied",
                        "Invalid message ID provided."
                    )
                )

                await asyncio.sleep(5)
                await message.delete()
                return

        # Message ID provided
        if message_id is not None:

            current_time = (
                datetime.datetime.now().timestamp()
            )

            await self.cursor.execute(
                """
                SELECT ends_at, guild_id, message_id,
                       host_id, winners, prize, channel_id
                FROM Giveaway
                WHERE message_id = ?
                """,
                (int(message_id),)
            )

            re = await self.cursor.fetchone()

            if re is None:

                message = await ctx.send(
                    view=CV2(
                        "❌ Error",
                        "The giveaway was not found."
                    )
                )

                await asyncio.sleep(5)
                await message.delete()
                return

            ch = self.bot.get_channel(
                int(re[6])
            )

            if ch is None:
                return

            message = await ch.fetch_message(
                int(message_id)
            )

            if not message.reactions:
                users = []
            else:
                users = [
                    i.id
                    async for i in message.reactions[0].users()
                ]

            try:
                users.remove(self.bot.user.id)
            except ValueError:
                pass

            if len(users) < 1:

                await ctx.send(
                    f"{TICK} Successfully Ended the giveaway "
                    f"in <#{int(re[6])}>"
                )

                await message.reply(
                    f"No one won the **{re[5]}** giveaway, "
                    f"due to not enough participants."
                )

                await self.cursor.execute(
                    """
                    DELETE FROM Giveaway
                    WHERE message_id = ?
                    AND guild_id = ?
                    """,
                    (
                        message.id,
                        message.guild.id
                    )
                )

                await self.connection.commit()
                return

            winners_count = min(
                len(users),
                int(re[4])
            )

            winner = ", ".join(
                f"<@!{i}>"
                for i in random.sample(
                    users,
                    k=winners_count
                )
            )

            desc = (
                f"Ended at <t:{int(current_time)}:R>\n"
                f"Hosted by <@{int(re[3])}>\n"
                f"Winner(s): {winner}"
            )

            view = CV2(
                f"🎁 {re[5]}",
                desc
            )

            await message.edit(view=view)

            if int(ctx.channel.id) != int(re[6]):

                await ctx.send(
                    f"{TADAA} Successfully ended the giveaway "
                    f"in <#{int(re[6])}>"
                )

            await message.reply(
                f"Congrats {winner}, "
                f"you won **{re[5]}!**, "
                f"Hosted by <@{int(re[3])}>"
            )

            await self.cursor.execute(
                """
                DELETE FROM Giveaway
                WHERE message_id = ?
                AND guild_id = ?
                """,
                (
                    message.id,
                    message.guild.id
                )
            )

        # Reply method
        elif ctx.message.reference:

            await self.cursor.execute(
                """
                SELECT ends_at, guild_id, message_id,
                       host_id, winners, prize, channel_id
                FROM Giveaway
                WHERE message_id = ?
                """,
                (
                    ctx.message.reference.resolved.id,
                )
            )

            re = await self.cursor.fetchone()

            if re is None:

                return await ctx.send(
                    "The giveaway was not found."
                )

            current_time = (
                datetime.datetime.now().timestamp()
            )

            message = await ctx.fetch_message(
                ctx.message.reference.message_id
            )

            if not message.reactions:
                users = []
            else:
                users = [
                    i.id
                    async for i in message.reactions[0].users()
                ]

            try:
                users.remove(self.bot.user.id)
            except ValueError:
                pass

            if len(users) < 1:

                await message.reply(
                    f"No one won the **{re[5]}** giveaway, "
                    f"due to not enough participants."
                )

                await self.cursor.execute(
                    """
                    DELETE FROM Giveaway
                    WHERE message_id = ?
                    AND guild_id = ?
                    """,
                    (
                        message.id,
                        message.guild.id
                    )
                )

                await self.connection.commit()
                return

            winners_count = min(
                len(users),
                int(re[4])
            )

            winner = ", ".join(
                f"<@!{i}>"
                for i in random.sample(
                    users,
                    k=winners_count
                )
            )

            desc = (
                f"Ended <t:{int(current_time)}:R>\n"
                f"Hosted by <@{int(re[3])}>\n"
                f"Winner(s): {winner}"
            )

            view = CV2(
                f"🎁 {re[5]}",
                desc
            )

            await message.edit(view=view)

            await message.reply(
                f"💐 Congrats {winner}, "
                f"you won **{re[5]}!**, "
                f"Hosted by <@{int(re[3])}>"
            )

            await self.cursor.execute(
                """
                DELETE FROM Giveaway
                WHERE message_id = ?
                AND guild_id = ?
                """,
                (
                    message.id,
                    message.guild.id
                )
            )

        else:

            await ctx.send(
                "Please reply to the giveaway message "
                "or provide the giveaway ID."
            )

        await self.connection.commit()

    # =========================================================
    # GREROLL
    # =========================================================

    @commands.hybrid_command(
        description="Rerolls a giveaway on replying the giveaway message.",
        help="Rerolls a giveaway on replying the giveaway message."
    )
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(
        1,
        5,
        commands.BucketType.user
    )
    @commands.has_guild_permissions(
        manage_guild=True
    )
    async def greroll(
        self,
        ctx,
        message_id: typing.Optional[int] = None
    ):

        if not ctx.message.reference:

            message = await ctx.reply(
                "Reply this command with the Giveaway Ended message to reroll."
            )

            await asyncio.sleep(5)
            await message.delete()
            return

        message_id = ctx.message.reference.resolved.id

        message = await ctx.fetch_message(
            message_id
        )

        if (
            ctx.message.reference.resolved.author.id
            != self.bot.user.id
        ):

            msg = await ctx.send(
                view=CV2(
                    "⚠️ Access Denied",
                    "The giveaway was not found."
                )
            )

            await asyncio.sleep(5)
            await msg.delete()
            return

        await self.cursor.execute(
            """
            SELECT message_id
            FROM Giveaway
            WHERE message_id = ?
            """,
            (message.id,)
        )

        re = await self.cursor.fetchone()

        if re is not None:

            msg = await ctx.send(
                view=CV2(
                    "⚠️ Access Denied",
                    "The giveaway is currently running. "
                    "Please use the `gend` command instead "
                    "to end the giveaway."
                )
            )

            await asyncio.sleep(5)
            await msg.delete()
            return

        if not message.reactions:
            users = []
        else:
            users = [
                i.id
                async for i in message.reactions[0].users()
            ]

        try:
            users.remove(self.bot.user.id)
        except ValueError:
            pass

        if len(users) < 1:

            await message.reply(
                "No one participated in this giveaway."
            )

            return

        winners = random.sample(
            users,
            k=1
        )

        await message.reply(
            "The new winner is "
            + ", ".join(
                f"<@{i}>"
                for i in winners
            )
            + ". Congratulations!"
        )

        await self.connection.commit()

    # =========================================================
    # GLIST
    # =========================================================

    @commands.hybrid_command(
        name="glist",
        description="Lists all ongoing giveaways."
    )
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(
        1,
        5,
        commands.BucketType.user
    )
    @commands.has_guild_permissions(
        manage_guild=True
    )
    async def glist(self, ctx):

        await self.cursor.execute(
            """
            SELECT prize, ends_at, winners, message_id
            FROM Giveaway
            WHERE guild_id = ?
            """,
            (ctx.guild.id,)
        )

        giveaways = await self.cursor.fetchall()

        if not giveaways:

            await ctx.send(
                view=CV2(
                    "Ongoing Giveaways",
                    "No ongoing giveaways."
                )
            )

            return

        desc = ""

        for giveaway in giveaways:

            prize, ends_at, winners, message_id = giveaway

            desc += (
                f"**{prize}**\n"
                f"Ends: <t:{int(ends_at)}:R> "
                f"(<t:{int(ends_at)}:f>)\n"
                f"Winners: {winners}\n"
                f"[Jump to Message]"
                f"(https://discord.com/channels/"
                f"{ctx.guild.id}/"
                f"{ctx.channel.id}/"
                f"{message_id})\n\n"
            )

        await ctx.send(
            view=CV2(
                "Ongoing Giveaways",
                desc
            )
        )


# =============================================================
# SETUP
# =============================================================

async def setup(bot):
    await bot.add_cog(
        Giveaway(bot)
    )