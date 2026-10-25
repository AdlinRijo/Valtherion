from datetime import datetime, timezone
from importlib import import_module
from pkgutil import iter_modules
from typing import Any, Protocol

import discord
from discord import app_commands

import commands as command_package

from config import Settings
from services.guild_service import RANK_ORDER

RANK_LABELS = {
    "owner": "Owner",
    "chief": "Chief",
    "strategist": "Strategist",
    "recruiter": "Recruiter",
    "recruit": "Recruit",
}
LEADERBOARD_CATEGORIES = [
    app_commands.Choice(name="Total level", value="total_level"),
    app_commands.Choice(name="Guild contribution", value="contribution"),
    app_commands.Choice(name="Wars", value="wars"),
    app_commands.Choice(name="Guild raids", value="raids"),
]


class PagedView(Protocol):
    page: int
    page_size: int

    @property
    def filtered(self) -> list[Any]: ...

    async def update(self, interaction: discord.Interaction) -> None: ...


def guild_title(guild: dict[str, Any], settings: Settings) -> str:
    api_name = guild.get("name")
    configured_name = settings.guild_name
    name = (
        configured_name
        if api_name
        and configured_name != "MY GUILD NAME"
        and configured_name.casefold() == str(api_name).casefold()
        else api_name or settings.guild_name
    )
    api_prefix = guild.get("prefix")
    configured_tag = settings.guild_tag
    prefix = (
        configured_tag
        if api_prefix
        and configured_tag != "MY GUILD TAG"
        and configured_tag.casefold() == str(api_prefix).casefold()
        else api_prefix
    )
    return f"[{prefix}] {name}" if prefix else name


def base_embed(title: str, color: int, description: str | None = None) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.timestamp = datetime.now(timezone.utc)
    embed.set_footer(text=f"Updated {embed.timestamp:%Y-%m-%d %H:%M UTC}")
    return embed


def format_number(value: Any) -> str:
    return f"{value:,}" if isinstance(value, (int, float)) else "NIL"


class MemberSearchModal(discord.ui.Modal, title="Find a guild member"):
    search = discord.ui.TextInput(
        label="Username contains",
        placeholder="Enter all or part of a username",
        max_length=32,
        required=True,
    )

    def __init__(self, view: "MemberDirectoryView") -> None:
        super().__init__()
        self.directory_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.directory_view.query = str(self.search.value).casefold().strip()
        self.directory_view.page = 0
        await self.directory_view.update(interaction)


class MemberDirectoryView(discord.ui.View):
    page_size = 10

    def __init__(self, members: list[dict[str, Any]], title: str, color: int) -> None:
        super().__init__(timeout=180)
        self.all_members = members
        self.title = title
        self.color = color
        self.rank = "all"
        self.query = ""
        self.page = 0
        self.refresh_controls()

    @property
    def filtered(self) -> list[dict[str, Any]]:
        return [
            member
            for member in self.all_members
            if (self.rank == "all" or member.get("rank") == self.rank)
            and self.query in member["username"].casefold()
        ]

    def refresh_controls(self) -> None:
        self.clear_items()
        self.add_item(RankSelect(self))
        self.add_item(SearchButton(self))
        self.add_item(PageButton(self, -1))
        self.add_item(PageButton(self, 1))

    def make_embed(self) -> discord.Embed:
        members = self.filtered
        pages = max(1, (len(members) + self.page_size - 1) // self.page_size)
        self.page = min(self.page, pages - 1)
        subset = members[
            self.page * self.page_size : (self.page + 1) * self.page_size
        ]
        rows = []
        for member in subset:
            restrictions = member.get("restrictions") or {}
            if not isinstance(restrictions, dict):
                restrictions = {}
            online = member.get("online")
            status = (
                "NIL"
                if restrictions.get("online_status", False)
                or not isinstance(online, bool)
                else "Online"
                if online
                else "Offline"
            )
            rows.append(
                (
                    member["username"],
                    RANK_LABELS.get(member.get("rank"), "NIL"),
                    format_number(member.get("contributed")),
                    status,
                )
            )
        if rows:
            headers = ("NAME", "RANK", "CONTRIBUTION", "ONLINE / OFFLINE")
            widths = tuple(
                max(len(header), *(len(row[index]) for row in rows))
                for index, header in enumerate(headers)
            )
            table_lines = [
                f"{headers[0]:<{widths[0]}}  "
                f"{headers[1]:<{widths[1]}}  "
                f"{headers[2]:>{widths[2]}}  "
                f"{headers[3]}"
            ]
            table_lines.extend(
                f"{row[0]:<{widths[0]}}  "
                f"{row[1]:<{widths[1]}}  "
                f"{row[2]:>{widths[2]}}  "
                f"{row[3]}"
                for row in rows
            )
            table = "\n".join(table_lines)
            description = f"```\n{table}\n```"
        else:
            description = "NIL"
        embed = base_embed(self.title, self.color, description)
        embed.set_footer(
            text=f"{len(members)} member(s) • Page {self.page + 1}/{pages}"
        )
        return embed

    async def update(self, interaction: discord.Interaction) -> None:
        self.refresh_controls()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)


class RankSelect(discord.ui.Select):
    def __init__(self, view: MemberDirectoryView) -> None:
        options = [
            discord.SelectOption(
                label="All ranks", value="all", default=view.rank == "all"
            )
        ]
        options.extend(
            discord.SelectOption(
                label=RANK_LABELS[rank], value=rank, default=view.rank == rank
            )
            for rank in RANK_ORDER
        )
        super().__init__(
            placeholder="Filter by rank",
            options=options,
            row=0,
        )
        self.directory_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        self.directory_view.rank = self.values[0]
        self.directory_view.page = 0
        await self.directory_view.update(interaction)


class SearchButton(discord.ui.Button):
    def __init__(self, view: MemberDirectoryView) -> None:
        super().__init__(label="Search", style=discord.ButtonStyle.secondary, row=1)
        self.directory_view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MemberSearchModal(self.directory_view))


class PageButton(discord.ui.Button):
    def __init__(self, view: PagedView, direction: int) -> None:
        super().__init__(
            label="Previous" if direction < 0 else "Next",
            style=discord.ButtonStyle.primary,
            row=1,
        )
        self.directory_view = view
        self.direction = direction

    async def callback(self, interaction: discord.Interaction) -> None:
        members = self.directory_view.filtered
        pages = max(
            1,
            (len(members) + self.directory_view.page_size - 1)
            // self.directory_view.page_size,
        )
        self.directory_view.page = (self.directory_view.page + self.direction) % pages
        await self.directory_view.update(interaction)


class TerritoryView(discord.ui.View):
    page_size = 11

    def __init__(self, territories: list[tuple[str, dict[str, Any]]], title: str, color: int):
        super().__init__(timeout=180)
        self.territories = territories
        self.title = title
        self.color = color
        self.page = 0
        self.add_item(PageButton(self, -1))
        self.add_item(PageButton(self, 1))

    @property
    def filtered(self) -> list[tuple[str, dict[str, Any]]]:
        return self.territories

    async def update(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    def make_embed(self) -> discord.Embed:
        pages = max(
            1, (len(self.territories) + self.page_size - 1) // self.page_size
        )
        self.page = min(self.page, pages - 1)
        subset = self.territories[
            self.page * self.page_size : (self.page + 1) * self.page_size
        ]
        embed = base_embed(self.title, self.color)
        if not subset:
            embed.description = "NIL"
        for name, territory in subset:
            location = territory.get("location", {})
            if not isinstance(location, dict):
                location = {}
            start, end = location.get("start"), location.get("end")
            coordinates = (
                f"{start} → {end}"
                if isinstance(start, list) and isinstance(end, list)
                else "NIL"
            )
            acquired = territory.get("acquired")
            acquired_text = str(acquired) if acquired else "NIL"
            marker = " · Headquarters" if territory.get("hq") else ""
            embed.add_field(
                name=f"🗺️ {name}{marker}",
                value=(
                    f"Acquired: {acquired_text}\n"
                    f"Treasury: {territory.get('treasury') or 'NIL'} · "
                    f"Defences: {territory.get('defences') or 'NIL'}\n"
                    f"Map bounds: {coordinates}"
                ),
                inline=False,
            )
        embed.set_footer(
            text=f"{len(self.territories)} owned • Page {self.page + 1}/{pages}"
        )
        return embed

guild = app_commands.Group(name="guild", description="Guild companion")

# Import each subcommand module so it registers its command on the shared group.
for module_name in (
    module.name
    for module in iter_modules(command_package.__path__)
    if module.name.startswith("guild_")
):
    import_module(f"{__package__}.{module_name}")


async def setup(bot: Any) -> None:
    bot.tree.add_command(guild)
