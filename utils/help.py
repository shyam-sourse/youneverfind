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
from utils.Tools import *
from utils.cv2 import build_container
from utils.config import OWNER_IDS
from utils.emoji import REWIND, PREVIOUS, NEXT, FORWARD, DELETE, HOME
from discord.ui import LayoutView, TextDisplay, Separator, ActionRow


class Dropdown(discord.ui.Select):

    def __init__(self, ctx, options, placeholder="Choose a Category for Help"):
        super().__init__(placeholder=placeholder,
                         min_values=1,
                         max_values=1,
                         options=options)
        self.invoker = ctx.author

    async def callback(self, interaction: discord.Interaction):
        if self.invoker == interaction.user:
            index = self.view.find_index_from_select(self.values[0])
            if not index:
                index = 0
            await self.view.set_page(index, interaction)
        else:
            await interaction.response.send_message(
                "You must run this command to interact with it.", ephemeral=True)


class View(LayoutView):

    def __init__(self, mapping: dict, ctx, homeembed, ui: int):
        super().__init__(timeout=None)
        self.mapping = mapping
        self.ctx = ctx
        self.index = 0
        self.current_page = 0
        self.ui = ui

        self.options, self.pages, self.total_pages = self.gen_pages(homeembed)
        self.pages[0]['footer'] = f"• Help page 1/{self.total_pages} | Requested by: {self.ctx.author.display_name}"
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        page = self.pages[self.index]
        page['footer'] = f"• Help page {self.index + 1}/{self.total_pages} | Requested by: {self.ctx.author.display_name}"

        # Build container items (text content)
        items = []
        if page.get('title'):
            items.append(TextDisplay(f"**{page['title']}**"))
        if page.get('description'):
            if items:
                items.append(Separator(visible=True))
            items.append(TextDisplay(page['description']))
        for name, value in page.get('fields', []):
            items.append(Separator(visible=True))
            items.append(TextDisplay(f"**{name}**\n{value}"))

        # Build buttons
        is_first = self.index == 0
        is_last = self.index >= len(self.pages) - 1

        homeB = discord.ui.Button(label="", emoji=REWIND, style=discord.ButtonStyle.secondary, disabled=is_first)
        backB = discord.ui.Button(label="", emoji=PREVIOUS, style=discord.ButtonStyle.secondary, disabled=is_first)
        quitB = discord.ui.Button(label="", emoji=DELETE, style=discord.ButtonStyle.danger)
        nextB = discord.ui.Button(label="", emoji=NEXT, style=discord.ButtonStyle.secondary, disabled=is_last)
        lastB = discord.ui.Button(label="", emoji=FORWARD, style=discord.ButtonStyle.secondary, disabled=is_last)

        homeB.callback = self._home_cb
        backB.callback = self._back_cb
        quitB.callback = self._quit_cb
        nextB.callback = self._next_cb
        lastB.callback = self._last_cb

        # Add buttons ActionRow inside the container
        items.append(ActionRow(homeB, backB, quitB, nextB, lastB))

        # Add dropdowns inside the container
        if self.ui == 0:
            items.append(ActionRow(Dropdown(ctx=self.ctx, options=self.options)))
        elif self.ui == 2:
            mid = len(self.options) // 2
            o1, o2 = self.options[:mid], self.options[mid:]
            if o1:
                items.append(ActionRow(Dropdown(ctx=self.ctx, options=o1, placeholder="Main Commands")))
            if o2:
                items.append(ActionRow(Dropdown(ctx=self.ctx, options=o2, placeholder="Extra Commands")))
        elif self.ui == 3:
            items.append(ActionRow(Dropdown(ctx=self.ctx, options=self.options)))

        # Add footer after controls
        if page.get('footer'):
            items.append(Separator(visible=True))
            items.append(TextDisplay(f"*{page['footer']}*"))

        # Build the single container with everything inside
        self.add_item(build_container(*items))

    async def _check(self, interaction):
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("You must run this command to interact with it.", ephemeral=True)
            return False
        return True

    async def _home_cb(self, interaction):
        if await self._check(interaction):
            await self.set_page(0, interaction)

    async def _back_cb(self, interaction):
        if await self._check(interaction):
            await self.set_page(self.index - 1 if self.index > 0 else len(self.pages) - 1, interaction)

    async def _quit_cb(self, interaction):
        if await self._check(interaction):
            await interaction.response.defer()
            await interaction.delete_original_response()

    async def _next_cb(self, interaction):
        if await self._check(interaction):
            await self.set_page(self.index + 1 if self.index < len(self.pages) - 1 else 0, interaction)

    async def _last_cb(self, interaction):
        if await self._check(interaction):
            await self.set_page(len(self.pages) - 1, interaction)

    def is_owner(self):
        return self.ctx.author.id in OWNER_IDS

    def find_index_from_select(self, value):
        return self.label_index.get(value, 0)

    def get_cogs(self):
        return list(self.mapping.keys())

    @staticmethod
    def _walk(command):
        """Yield a command and every one of its subcommands (recursively)."""
        yield command
        for sub in getattr(command, "commands", []):
            yield from View._walk(sub)

    @staticmethod
    def _signature(command):
        params = ""
        for param in command.clean_params:
            if param not in ("self", "ctx"):
                params += f" <{param}>"
        return f"{command.qualified_name}{params}"

    def gen_pages(self, homeembed):
        options, pages = [], []
        used_labels = set()
        self.label_index = {}

        options.append(discord.SelectOption(label="Home", emoji=HOME, description=""))

        # Convert homeembed (CV2Embed) to page data
        if hasattr(homeembed, '_title'):
            home_page = {
                'title': homeembed._title or '',
                'description': homeembed._description or '',
                'fields': list(homeembed._fields) if hasattr(homeembed, '_fields') else [],
                'footer': None
            }
        else:
            home_page = {
                'title': getattr(homeembed, 'title', '') or '',
                'description': getattr(homeembed, 'description', '') or '',
                'fields': [(f.name, f.value) for f in homeembed.fields] if hasattr(homeembed, 'fields') and homeembed.fields else [],
                'footer': homeembed.footer.text if hasattr(homeembed, 'footer') and homeembed.footer else None
            }

        pages.append(home_page)
        used_labels.add("Home")

        PER_PAGE = 8

        for cog in self.get_cogs():
            if cog.__class__.__name__ == "Roleplay":
                continue
            if getattr(cog, "owner_only", False) and not self.is_owner():
                continue
            if "help_custom" not in dir(cog):
                continue

            emoji, label, description = cog.help_custom()
            original_label = label
            counter = 1
            while label in used_labels:
                label = f"{original_label} {counter}"
                counter += 1
            used_labels.add(label)
            options.append(discord.SelectOption(label=label, emoji=emoji, description=description))

            # Collect every command AND subcommand of the cog
            fields = []
            for command in cog.get_commands():
                for cmd in self._walk(command):
                    if getattr(cmd, "hidden", False):
                        continue
                    # Skip the bare group itself when it only exists to hold subcommands
                    if getattr(cmd, "commands", None) and not (cmd.help or cmd.description):
                        continue
                    help_text = cmd.help or cmd.description or "No description available"
                    if len(help_text) > 300:
                        help_text = help_text[:297] + "..."
                    fields.append((self._signature(cmd), f"{help_text}\n•"))

            if not fields:
                fields = [("No commands", "This module has no usable commands.\n•")]

            # Split long categories across multiple pages so nothing gets cut off
            chunks = [fields[i:i + PER_PAGE] for i in range(0, len(fields), PER_PAGE)]
            self.label_index[label] = len(pages)
            for idx, chunk in enumerate(chunks, start=1):
                title = f"{emoji} {original_label}"
                if len(chunks) > 1:
                    title += f" ({idx}/{len(chunks)})"
                pages.append({
                    'title': title,
                    'description': '',
                    'fields': chunk,
                    'footer': None
                })

        return options, pages, len(pages)

    async def set_page(self, page, interaction):
        self.index = page
        self.current_page = page
        self._rebuild()
        await interaction.response.edit_message(view=self)