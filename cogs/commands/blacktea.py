# ╔══════════════════════════════════════════════════════════════════╗
# ║   BLACK TEA  —  Mudae style word game                            ║
# ║   Drop this file at: cogs/commands/blacktea.py                   ║
# ╚══════════════════════════════════════════════════════════════════╝

import os
import random
import asyncio
from collections import Counter

import discord
from discord.ext import commands

from core import Cog, zyrox, Context
from utils.Tools import *

RED = 0xFF0000

# ── built-in (unicode) emojis only ──────────────────────────────────
E_TEA = "🫖"
E_HEART = "❤️"
E_BROKEN = "💔"
E_TIMER = "⏱️"
E_TICK = "✅"
E_CROSS = "❌"
E_SKULL = "💀"
E_CROWN = "👑"
E_BOOK = "📖"
E_FIRE = "🔥"
E_STAR = "⭐"
E_PEOPLE = "👥"
E_PLAY = "▶️"
E_STOP = "🛑"

WORDS_PATH = os.path.join("games", "assets", "blacktea_words.txt")
WORDS_URL = "https://raw.githubusercontent.com/dwyl/english-words/master/words_alpha.txt"

_WORDS: set[str] = set()
_TRIGRAMS: list[str] = []
_LOCK = asyncio.Lock()


async def _ensure_words() -> None:
    """Load (and if needed download) the dictionary + build the trigram pool."""
    global _WORDS, _TRIGRAMS
    async with _LOCK:
        if _WORDS:
            return

        if not os.path.exists(WORDS_PATH):
            os.makedirs(os.path.dirname(WORDS_PATH), exist_ok=True)
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(WORDS_URL) as resp:
                    data = await resp.text()
            with open(WORDS_PATH, "w", encoding="utf-8") as f:
                f.write(data)
        else:
            with open(WORDS_PATH, "r", encoding="utf-8") as f:
                data = f.read()

        words = {w.strip().lower() for w in data.split() if w.strip().isalpha()}
        _WORDS = {w for w in words if 3 <= len(w) <= 20}

        counter = Counter()
        for w in _WORDS:
            if len(w) < 5:
                continue
            for i in range(len(w) - 2):
                counter[w[i:i + 3]] += 1
        # only trigrams that are comfortably solvable
        _TRIGRAMS = [t for t, c in counter.items() if c >= 250]


def is_valid(word: str, trigram: str) -> bool:
    return trigram in word and word in _WORDS


class BlackTeaGame:
    """State for one Black Tea game in one channel."""

    def __init__(self, ctx: Context, hp: int, turn_time: int):
        self.ctx = ctx
        self.channel = ctx.channel
        self.host = ctx.author
        self.hp = hp
        self.turn_time = turn_time
        self.players: list[discord.Member] = [ctx.author]
        self.lives: dict[int, int] = {}
        self.used: set[str] = set()
        self.round = 0
        self.running = True
        self.solo_score = 0

    def hearts(self, member) -> str:
        left = self.lives.get(member.id, 0)
        return E_HEART * left + E_BROKEN * (self.hp - left)

    def alive(self) -> list[discord.Member]:
        return [p for p in self.players if self.lives.get(p.id, 0) > 0]


class JoinView(discord.ui.View):
    def __init__(self, game: BlackTeaGame):
        super().__init__(timeout=None)
        self.game = game

    @discord.ui.button(label="Join", emoji=E_TEA, style=discord.ButtonStyle.danger)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user in self.game.players:
            return await interaction.response.send_message(
                f"{E_CROSS} You already joined the table.", ephemeral=True)
        if len(self.game.players) >= 15:
            return await interaction.response.send_message(
                f"{E_CROSS} The table is full (15 players).", ephemeral=True)
        self.game.players.append(interaction.user)
        await interaction.response.send_message(
            f"{E_TICK} You joined the Black Tea table!", ephemeral=True)
        await interaction.followup.send(
            f"{E_TEA} **{interaction.user.display_name}** sat down at the table "
            f"`({len(self.game.players)} players)`")

    @discord.ui.button(label="Start now", emoji=E_PLAY, style=discord.ButtonStyle.secondary)
    async def start_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.game.host:
            return await interaction.response.send_message(
                f"{E_CROSS} Only the host can start the game.", ephemeral=True)
        await interaction.response.defer()
        self.stop()


class BlackTea(Cog):
    """Black Tea word game"""

    def __init__(self, client: zyrox):
        self.client = client
        self.games: dict[int, BlackTeaGame] = {}
        self.wins: dict[int, int] = {}

    # ── helpers ────────────────────────────────────────────────────
    def embed(self, title: str, desc: str) -> discord.Embed:
        return discord.Embed(title=title, description=desc, color=RED)

    def rules_embed(self, prefix: str = ".") -> discord.Embed:
        e = self.embed(
            f"{E_TEA} Black Tea — How to play",
            f"> Type a **real English word** that contains the **3 letters** "
            f"the bot shows, **in that exact order**, before the timer runs out.")
        e.add_field(
            name=f"{E_BOOK} Rules",
            value=(f"{E_STAR} Everyone starts with **2 {E_HEART} HP** (1-5 configurable)\n"
                   f"{E_STAR} You get **5 seconds** per turn (3-15 configurable)\n"
                   f"{E_STAR} Wrong word / no answer = **-1 {E_HEART}**\n"
                   f"{E_STAR} A word can only be used **once** per game\n"
                   f"{E_STAR} Turns rotate — **solo play is allowed**\n"
                   f"{E_STAR} Last player alive wins {E_CROWN}"),
            inline=False)
        e.add_field(
            name=f"{E_FIRE} Commands",
            value=(f"`{prefix}blacktea` — start a game\n"
                   f"`{prefix}blacktea start [hp] [seconds]` — custom game\n"
                   f"`{prefix}blacktea rules` — show these instructions\n"
                   f"`{prefix}blacktea end` — stop the game in this channel\n"
                   f"`{prefix}blacktea leaderboard` — top Black Tea winners\n"
                   f"**Aliases:** `bt`, `btea`"),
            inline=False)
        e.set_footer(text="Example: letters TEA → \"steal\", \"team\", \"instead\"")
        return e

    async def get_prefix(self, ctx: Context) -> str:
        try:
            data = await getConfig(ctx.guild.id)
            return data["prefix"]
        except Exception:
            return "."

    # ── commands ───────────────────────────────────────────────────
    @commands.group(name="blacktea",
                    help="Play the Black Tea word game (Mudae style).",
                    aliases=["bt", "btea", "black-tea"],
                    usage="blacktea [hp] [seconds]",
                    invoke_without_command=True)
    @blacklist_check()
    @ignore_check()
    @commands.cooldown(1, 5, commands.BucketType.channel)
    @commands.guild_only()
    async def blacktea(self, ctx: Context, hp: int = 2, seconds: int = 5):
        await self._start(ctx, hp, seconds)

    @blacktea.command(name="start", help="Start a Black Tea game.")
    @commands.guild_only()
    async def _start_cmd(self, ctx: Context, hp: int = 2, seconds: int = 5):
        await self._start(ctx, hp, seconds)

    @blacktea.command(name="rules", help="Black Tea instructions.",
                      aliases=["help", "info", "instructions"])
    @commands.guild_only()
    async def _rules(self, ctx: Context):
        await ctx.send(embed=self.rules_embed(await self.get_prefix(ctx)))

    @blacktea.command(name="end", help="Stop the Black Tea game in this channel.",
                      aliases=["stop", "cancel"])
    @commands.guild_only()
    async def _end(self, ctx: Context):
        game = self.games.get(ctx.channel.id)
        if not game:
            return await ctx.send(embed=self.embed(
                f"{E_CROSS} No game", "There is no Black Tea game running here."))
        if ctx.author != game.host and not ctx.author.guild_permissions.manage_messages:
            return await ctx.send(embed=self.embed(
                f"{E_CROSS} Not allowed",
                "Only the host or a member with **Manage Messages** can end the game."))
        game.running = False
        await ctx.send(embed=self.embed(f"{E_STOP} Game ended",
                                        f"The Black Tea game was ended by {ctx.author.mention}."))

    @blacktea.command(name="leaderboard", help="Top Black Tea winners.",
                      aliases=["lb", "top"])
    @commands.guild_only()
    async def _lb(self, ctx: Context):
        if not self.wins:
            return await ctx.send(embed=self.embed(
                f"{E_CROWN} Black Tea Leaderboard", "No winners yet — be the first!"))
        top = sorted(self.wins.items(), key=lambda x: x[1], reverse=True)[:10]
        lines = []
        for i, (uid, w) in enumerate(top, 1):
            user = self.client.get_user(uid)
            lines.append(f"**{i}.** {user.mention if user else f'<@{uid}>'} — `{w}` wins")
        await ctx.send(embed=self.embed(f"{E_CROWN} Black Tea Leaderboard",
                                        "\n".join(lines)))

    # ── game flow ──────────────────────────────────────────────────
    async def _start(self, ctx: Context, hp: int, seconds: int):
        if ctx.channel.id in self.games:
            return await ctx.send(embed=self.embed(
                f"{E_CROSS} Already brewing",
                "A Black Tea game is already running in this channel."))

        hp = max(1, min(5, hp))
        seconds = max(3, min(15, seconds))

        loading = await ctx.send(embed=self.embed(
            f"{E_TEA} Black Tea", "Boiling the water (loading dictionary)..."))
        try:
            await _ensure_words()
        except Exception as e:
            return await loading.edit(embed=self.embed(
                f"{E_CROSS} Failed to start", f"Could not load the word list.\n`{e}`"))

        game = BlackTeaGame(ctx, hp, seconds)
        self.games[ctx.channel.id] = game
        prefix = await self.get_prefix(ctx)

        try:
            view = JoinView(game)
            lobby = self.rules_embed(prefix)
            lobby.title = f"{E_TEA} Black Tea — Join the table!"
            lobby.description = (
                f"> {ctx.author.mention} started a game of **Black Tea**.\n"
                f"> Press {E_TEA} **Join** to play — starting in **20 seconds**.\n"
                f"> {E_HEART} HP: **{hp}**  •  {E_TIMER} Turn time: **{seconds}s**  •  "
                f"Solo play allowed.")
            await loading.edit(embed=lobby, view=view)
            await asyncio.wait_for(view.wait(), timeout=20)
        except asyncio.TimeoutError:
            pass
        finally:
            with_view = None
            try:
                await loading.edit(view=with_view)
            except discord.HTTPException:
                pass

        if not game.running:
            self.games.pop(ctx.channel.id, None)
            return

        for p in game.players:
            game.lives[p.id] = hp

        solo = len(game.players) == 1
        names = ", ".join(f"**{p.display_name}**" for p in game.players)
        await ctx.send(embed=self.embed(
            f"{E_FIRE} The game begins!",
            f"{E_PEOPLE} Players: {names}\n"
            f"{'🎯 **Solo mode** — survive as many rounds as you can!' if solo else ''}\n"
            f"Type a word containing the shown letters within **{seconds}s**."))

        try:
            await self._loop(ctx, game, solo)
        finally:
            self.games.pop(ctx.channel.id, None)

    async def _loop(self, ctx: Context, game: BlackTeaGame, solo: bool):
        idx = 0
        while game.running and len(game.alive()) > (0 if solo else 1):
            alive = game.alive()
            player = alive[idx % len(alive)]
            trigram = random.choice(_TRIGRAMS)
            game.round += 1

            e = self.embed(
                f"{E_TEA} Round {game.round}",
                f"{player.mention}, type a word containing **`{trigram.upper()}`**\n"
                f"{E_TIMER} **{game.turn_time}s**  •  {game.hearts(player)}")
            e.set_footer(text=f"Letters must appear in this exact order • {trigram.upper()}")
            await ctx.send(content=player.mention, embed=e)

            def check(m: discord.Message):
                return (m.channel.id == ctx.channel.id
                        and m.author.id == player.id
                        and m.content
                        and m.content.strip().isalpha())

            correct = False
            deadline = asyncio.get_event_loop().time() + game.turn_time
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    msg = await self.client.wait_for("message", check=check, timeout=remaining)
                except asyncio.TimeoutError:
                    break
                word = msg.content.strip().lower()
                if word in game.used:
                    await msg.add_reaction("♻️")
                    continue
                if is_valid(word, trigram):
                    game.used.add(word)
                    await msg.add_reaction(E_TICK)
                    correct = True
                    break
                await msg.add_reaction(E_CROSS)

            if not game.running:
                break

            if correct:
                game.solo_score += 1
                idx += 1
                continue

            game.lives[player.id] -= 1
            if game.lives[player.id] <= 0:
                await ctx.send(embed=self.embed(
                    f"{E_SKULL} Eliminated",
                    f"{player.mention} ran out of HP and left the table."))
                if not solo:
                    alive_after = game.alive()
                    if alive_after:
                        idx = idx % max(len(alive_after), 1)
                    continue
            else:
                await ctx.send(embed=self.embed(
                    f"{E_BROKEN} Ouch!",
                    f"{player.mention} missed **`{trigram.upper()}`** and lost 1 HP.\n"
                    f"{game.hearts(player)}"))
                idx += 1

            if solo and game.lives[player.id] <= 0:
                break

        if not game.running:
            return

        if solo:
            return await ctx.send(embed=self.embed(
                f"{E_CROWN} Game over",
                f"{game.host.mention} survived **{game.solo_score}** words "
                f"across **{game.round}** rounds. {E_FIRE}"))

        alive = game.alive()
        if alive:
            winner = alive[0]
            self.wins[winner.id] = self.wins.get(winner.id, 0) + 1
            await ctx.send(embed=self.embed(
                f"{E_CROWN} Winner!",
                f"{winner.mention} wins the Black Tea game with {game.hearts(winner)}\n"
                f"Words played: **{len(game.used)}**  •  Rounds: **{game.round}**"))
        else:
            await ctx.send(embed=self.embed(
                f"{E_TEA} Game over", "Everyone was eliminated. No winner!"))
