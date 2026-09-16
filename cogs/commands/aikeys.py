# ╔══════════════════════════════════════════════════════════════════╗
# ║   AI Keys  ──  manage Groq API keys from inside Discord          ║
# ║   add • remove • list • health • rotate • use • reload           ║
# ╚══════════════════════════════════════════════════════════════════╝
"""Owner-only commands to manage the Groq API keys the bot rotates.

Keys added with ``aikeys add`` are persisted to ``data/groq_keys.json`` and
take effect immediately (no restart). ``aikeys health`` checks every key
against the Groq API and re-enables / disables them accordingly.
"""

import re

import discord
from discord.ext import commands

from utils.emoji import ZAI, TICK, CROSS, WARNING, INFO
from utils.groq_keys import key_manager, mask_key

COLOR = 0xFF0000

SPLIT = re.compile(r"[,\n;\s]+")


class AIKeys(commands.Cog):
    """Manage the AI (Groq) API key pool without touching the server files."""

    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def help_custom():
        return (ZAI, "AI Keys", "Add, check and rotate the bot's Groq AI keys.")

    def embed(self, title, description):
        return discord.Embed(title=title, description=description, color=COLOR)

    # ----------------------------- input ------------------------------
    @staticmethod
    def _extract_keys(text):
        out = []
        if not text:
            return out
        for token in SPLIT.split(text):
            token = token.strip().strip('"').strip("'")
            if "=" in token:
                token = token.split("=", 1)[1].strip().strip('"').strip("'")
            if token:
                out.append(token)
        return out

    async def _collect(self, ctx, raw):
        keys = self._extract_keys(raw)
        for att in ctx.message.attachments:
            if att.size and att.size > 500_000:
                continue
            if not att.filename.lower().endswith((".txt", ".env", ".json", ".csv")):
                continue
            try:
                data = (await att.read()).decode("utf-8", "ignore")
            except Exception:
                continue
            for line in data.splitlines():
                line = line.strip().strip('"').strip("'")
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    name, _, value = line.partition("=")
                    if "GROQ" not in name.upper() and "KEY" not in name.upper():
                        continue
                    line = value.strip().strip('"').strip("'")
                keys.extend(self._extract_keys(line))

        clean, seen = [], set()
        for key in keys:
            if len(key) < 20:
                continue
            if key.lower().startswith("your_") or key.lower().startswith("gsk_your"):
                continue
            if key not in seen:
                seen.add(key)
                clean.append(key)
        return clean

    # --------------------------- commands -----------------------------
    @commands.group(name="aikeys", aliases=["gkeys", "aikey"],
                    invoke_without_command=True,
                    help="Manage the Groq AI API keys (owner only).")
    @commands.is_owner()
    async def aikeys(self, ctx):
        rows = key_manager.info()
        if not rows:
            body = "No keys loaded yet. Add one with `aikeys add <key>`."
        else:
            body = "\n".join(
                f"`#{r['index']}` {r['masked']} — {r['state']}"
                f"{' [active]' if r['active'] else ''}" for r in rows)
        p = ctx.clean_prefix
        await ctx.send(embed=self.embed(
            f"{ZAI} AI Key Manager",
            f"{body}\n\n"
            f"`{p}aikeys add <key>` — add key(s), or attach a .txt/.env file\n"
            f"`{p}aikeys list` — list all keys\n"
            f"`{p}aikeys health` — live check every key\n"
            f"`{p}aikeys remove <#|last4>` — remove a stored key\n"
            f"`{p}aikeys rotate` — move to the next key\n"
            f"`{p}aikeys use <#|last4>` — force one key to be tried first\n"
            f"`{p}aikeys reload` — re-read .env + stored keys"))

    @aikeys.command(name="add", aliases=["set", "import"],
                    help="Add one or more Groq API keys.")
    @commands.is_owner()
    async def add(self, ctx, *, keys: str = None):
        parsed = await self._collect(ctx, keys)
        # never leave a raw key sitting in the channel
        if ctx.guild:
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass
        if not parsed:
            return await ctx.send(embed=self.embed(
                f"{CROSS} Nothing Added",
                "No valid key found. Use `aikeys add gsk_...` or attach a "
                "`.txt`/`.env` file containing `GROQ_API_KEY=...` lines."))

        added = key_manager.add_key(parsed)
        if not added:
            return await ctx.send(embed=self.embed(
                f"{INFO} Already Present",
                "All of those keys are already in the rotation."))
        masked = "\n".join(f"{TICK} `{mask_key(k)}`" for k in added)
        await ctx.send(embed=self.embed(
            f"{TICK} Added {len(added)} Key(s)",
            f"{masked}\n\nThey are active immediately. Run "
            f"`{ctx.clean_prefix}aikeys health` to verify them."))

    @aikeys.command(name="list", aliases=["status", "show"],
                    help="List every loaded key and its current state.")
    @commands.is_owner()
    async def list_keys(self, ctx):
        rows = key_manager.info()
        if not rows:
            return await ctx.send(embed=self.embed(
                f"{WARNING} No Keys",
                "No Groq keys loaded. Add one with `aikeys add <key>`."))
        lines = []
        for r in rows:
            icon = TICK if r["state"] == "ready" else WARNING
            src = "stored" if r["stored"] else "env"
            active = " • active" if r["active"] else ""
            lines.append(f"{icon} `#{r['index']}` {r['masked']} — "
                         f"{r['state']} [{src}]{active} ({r['calls']} calls)")
        await ctx.send(embed=self.embed(
            f"{ZAI} AI Keys ({len(rows)})", "\n".join(lines)))

    @aikeys.command(name="health", aliases=["check", "test"],
                    help="Live-check every key against the Groq API.")
    @commands.is_owner()
    async def health(self, ctx):
        if not key_manager.has_keys:
            return await ctx.send(embed=self.embed(
                f"{WARNING} No Keys", "Add a key first with `aikeys add <key>`."))
        async with ctx.typing():
            results = await key_manager.health_check_all()
        ok = sum(1 for r in results if r["ok"])
        lines = []
        for r in results:
            if r["ok"]:
                icon = TICK
                detail = f"{r['ms']}ms"
            elif r["status"] == 429:
                icon = WARNING
                detail = "rate limited"
            else:
                icon = CROSS
                detail = r["detail"] or f"HTTP {r['status']}"
            lines.append(f"{icon} `#{r['index']}` {r['masked']} — {detail}")
        await ctx.send(embed=self.embed(
            f"{ZAI} Key Health — {ok}/{len(results)} healthy",
            "\n".join(lines) + "\n\nInvalid keys are disabled automatically."))

    @aikeys.command(name="remove", aliases=["delete", "del"],
                    help="Remove a stored key by number or last 4 characters.")
    @commands.is_owner()
    async def remove(self, ctx, identifier: str):
        masked, stored = key_manager.remove_key(identifier)
        if not masked:
            return await ctx.send(embed=self.embed(
                f"{CROSS} Not Found",
                f"No key matches `{identifier}`."))
        extra = "" if stored else ("\n\nNote: this key came from `.env`, so it "
                                  "will reappear after a reload — remove it "
                                  "from the `.env` file to delete it for good.")
        await ctx.send(embed=self.embed(
            f"{TICK} Key Removed", f"Removed `{masked}`.{extra}"))

    @aikeys.command(name="rotate", aliases=["next"],
                    help="Rotate to the next available key right now.")
    @commands.is_owner()
    async def rotate(self, ctx):
        before, after = key_manager.rotate()
        if not after:
            return await ctx.send(embed=self.embed(
                f"{WARNING} No Keys", "There are no keys to rotate."))
        await ctx.send(embed=self.embed(
            f"{TICK} Rotated",
            f"`{mask_key(before)}` → next up: `{mask_key(after)}`"))

    @aikeys.command(name="use", aliases=["active"],
                    help="Force one key to be tried first.")
    @commands.is_owner()
    async def use(self, ctx, identifier: str):
        masked = key_manager.set_active(identifier)
        if not masked:
            return await ctx.send(embed=self.embed(
                f"{CROSS} Not Found", f"No key matches `{identifier}`."))
        await ctx.send(embed=self.embed(
            f"{TICK} Active Key Set",
            f"`{masked}` will be tried first on the next request."))

    @aikeys.command(name="clearactive", aliases=["auto"],
                    help="Clear the forced active key and resume round-robin.")
    @commands.is_owner()
    async def clearactive(self, ctx):
        key_manager.clear_active()
        await ctx.send(embed=self.embed(
            f"{TICK} Automatic Rotation", "Forced key cleared — round-robin resumed."))

    @aikeys.command(name="reload", help="Re-read keys from .env and the store.")
    @commands.is_owner()
    async def reload(self, ctx):
        count = key_manager.reload()
        await ctx.send(embed=self.embed(
            f"{TICK} Keys Reloaded", f"Loaded `{count}` key(s) from .env + store."))


async def setup(bot):
    await bot.add_cog(AIKeys(bot))
