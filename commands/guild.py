import json
from datetime import datetime, timezone
from typing import Any, Protocol

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from config import Settings
from services.guild_service import RANK_ORDER, GuildService
from services.wynncraft_api import WynncraftAPIError

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
    app_commands.Choice(name="Wars (API global stat)", value="wars"),
    app_commands.Choice(name="Guild raids", value="raids"),
    app_commands.Choice(name="Weekly contribution (tracked)", value="weekly_contribution"),
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
    embed.set_footer(text="Wynncraft API v3 • refreshed on request")
    return embed


def format_number(value: Any) -> str:
    return f"{value:,}" if isinstance(value, (int, float)) else "Not available"


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
        lines = []
        for member in subset:
            details = [RANK_LABELS.get(member.get("rank"), "Unknown")]
            if isinstance(member.get("contributed"), int):
                details.append(f"{member['contributed']:,} contribution")
            restrictions = member.get("restrictions") or {}
            if not isinstance(restrictions, dict):
                restrictions = {}
            if isinstance(member.get("online"), bool) and not restrictions.get(
                "online_status", False
            ):
                details.append("Online" if member["online"] else "Offline")
            lines.append(f"**{member['username']}** — {' · '.join(details)}")
        description = "\n".join(lines) if lines else "No members match this filter."
        embed = base_embed(self.title, self.color, description)
        embed.set_footer(
            text=f"{len(members)} member(s) • Page {self.page + 1}/{pages} • Wynncraft API v3"
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
            embed.description = "This guild currently owns no territories."
        for name, territory in subset:
            location = territory.get("location", {})
            if not isinstance(location, dict):
                location = {}
            start, end = location.get("start"), location.get("end")
            coordinates = (
                f"{start} → {end}"
                if isinstance(start, list) and isinstance(end, list)
                else "Not available"
            )
            acquired = territory.get("acquired")
            acquired_text = str(acquired) if acquired else "Not available"
            marker = " · Headquarters" if territory.get("hq") else ""
            embed.add_field(
                name=f"🗺️ {name}{marker}",
                value=(
                    f"Acquired: {acquired_text}\n"
                    f"Treasury: {territory.get('treasury', 'Not available')} · "
                    f"Defences: {territory.get('defences', 'Not available')}\n"
                    f"Map bounds: {coordinates}"
                ),
                inline=False,
            )
        embed.set_footer(
            text=f"{len(self.territories)} owned • Page {self.page + 1}/{pages} • Wynncraft API v3"
        )
        return embed


class GuildCommands(commands.Cog):
    guild = app_commands.Group(name="guild", description="Wynncraft guild companion")

    def __init__(
        self, bot: commands.Bot, service: GuildService, settings: Settings
    ) -> None:
        self.bot = bot
        self.service = service
        self.settings = settings

    @guild.command(name="info", description="Show the guild overview")
    async def info(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            guild = await self.service.current()
        except WynncraftAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        territory_note = ""
        try:
            territories: dict[str, dict[str, Any]] | None = (
                await self.service.owned_territories()
            )
        except WynncraftAPIError as exc:
            territories = None
            territory_note = f"\nTerritory details unavailable: {exc}"
        members = guild.get("members", {})
        if not isinstance(members, dict):
            members = {}
        embed = base_embed(
            f"🏰 {guild_title(guild, self.settings)}",
            self.settings.accent_color,
            "A current overview drawn from the Wynncraft API.",
        )
        embed.add_field(
            name="Guild",
            value=(
                f"**Level:** {format_number(guild.get('level'))}\n"
                f"**Level progress:** "
                f"{guild.get('xpPercent', 'Not available')}%"
                if isinstance(guild.get("xpPercent"), (int, float))
                else f"**Level:** {format_number(guild.get('level'))}\n"
                "**Level progress:** Not available"
            ),
            inline=True,
        )
        embed.add_field(
            name="Activity",
            value=(
                f"**Members:** {format_number(members.get('total'))}\n"
                f"**Online:** {format_number(guild.get('online'))}\n"
                f"**Territories:** "
                f"{format_number(len(territories) if territories is not None else guild.get('territories'))}\n"
                f"**Wars:** {format_number(guild.get('wars'))}\n"
                f"**Raids:** {format_number(guild.get('raids'))}"
            ),
            inline=True,
        )
        if territories is not None:
            territory_names = sorted(territories, key=str.casefold)
            territory_text = (
                ", ".join(territory_names[:12])
                if territory_names
                else "No territories currently listed."
            )
            if len(territory_names) > 12:
                territory_text += f" and {len(territory_names) - 12} more"
            embed.add_field(
                name="Territory holdings",
                value=territory_text + territory_note,
                inline=False,
            )
        elif territory_note:
            embed.add_field(
                name="Territory holdings",
                value=territory_note,
                inline=False,
            )
        rank_counts = []
        for rank in RANK_ORDER:
            rank_members = members.get(rank)
            rank_counts.append(
                f"**{RANK_LABELS[rank]}:** "
                f"{len(rank_members) if isinstance(rank_members, dict) else 'Not available'}"
            )
        embed.add_field(name="Ranks", value="\n".join(rank_counts), inline=True)
        embed.add_field(
            name="Founded",
            value=str(guild.get("created") or "Not available"),
            inline=True,
        )
        embed.add_field(
            name="Guild experience",
            value="Total lifetime XP: Not available from the documented guild response.",
            inline=False,
        )
        season_ranks = guild.get("seasonRanks")
        if isinstance(season_ranks, dict) and season_ranks:
            season_text = "\n".join(
                f"**{season}:** rating {data.get('rating', 'Not available')} · "
                f"{data.get('finalTerritories', 'Not available')} final territories"
                for season, data in list(season_ranks.items())[:5]
                if isinstance(data, dict)
            )
            if season_text:
                embed.add_field(name="Season records", value=season_text, inline=False)
        embed.set_footer(
            text=f"Wynncraft API v3 • Updated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
        )
        await interaction.followup.send(embed=embed)

    @guild.command(name="members", description="Browse guild members")
    async def members(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            guild = await self.service.current()
            members = await self.service.members()
        except WynncraftAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        view = MemberDirectoryView(
            members,
            f"⚔️ {guild_title(guild, self.settings)} · Members",
            self.settings.accent_color,
        )
        await interaction.followup.send(embed=view.make_embed(), view=view)

    @guild.command(name="member", description="Show a guild member's public profile")
    @app_commands.describe(username="Wynncraft username")
    async def member(self, interaction: discord.Interaction, username: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            guild = await self.service.current()
            members = await self.service.members()
        except WynncraftAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        member = next(
            (
                row
                for row in members
                if row["username"].casefold() == username.casefold()
            ),
            None,
        )
        if member is None:
            await interaction.followup.send(
                f"**{username}** is not listed in this guild.", ephemeral=True
            )
            return
        profile: dict[str, Any] | None = None
        profile_note = ""
        try:
            profile = await self.service.api.get_player(
                member.get("uuid") or member["username"]
            )
        except WynncraftAPIError:
            profile_note = (
                "\nSome player-profile details are unavailable or access-restricted."
            )
        global_data = member.get("globalData") or {}
        if not isinstance(global_data, dict):
            global_data = {}
        if profile:
            profile_restrictions = profile.get("restrictions") or {}
            if not isinstance(profile_restrictions, dict):
                profile_restrictions = {}
            if profile_restrictions.get("mainAccess") is True:
                global_data = {}
                profile_note = "\nPublic player statistics are access-restricted."
            else:
                profile_data = profile.get("globalData") or {}
                global_data = profile_data if isinstance(profile_data, dict) else {}
        member_restrictions = member.get("restrictions") or {}
        if not isinstance(member_restrictions, dict):
            member_restrictions = {}
        if member_restrictions.get("main_access") is True:
            global_data = {}
        embed = base_embed(
            f"🛡️ {member['username']}",
            self.settings.accent_color,
            f"Guild rank: **{RANK_LABELS.get(member['rank'], 'Unknown')}**"
            f"{profile_note}",
        )
        restrictions = (profile or {}).get("restrictions") or {}
        if not isinstance(restrictions, dict):
            restrictions = {}
        online_value = profile.get("online") if profile else member.get("online")
        member_status_restricted = member_restrictions.get("online_status") is True
        if (
            isinstance(online_value, bool)
            and not restrictions.get("onlineStatus", False)
            and not member_status_restricted
        ):
            embed.add_field(
                name="Status", value="Online" if online_value else "Offline", inline=True
            )
        embed.add_field(
            name="Guild contribution",
            value=format_number(member.get("contributed")),
            inline=True,
        )
        embed.add_field(
            name="Total level",
            value=format_number(global_data.get("totalLevel")),
            inline=True,
        )
        embed.add_field(
            name="Wars (global stat)",
            value=format_number(global_data.get("wars")),
            inline=True,
        )
        current_raids = global_data.get("currentGuildRaids")
        embed.add_field(
            name="Guild raids",
            value=format_number(current_raids.get("total") if isinstance(current_raids, dict) else None),
            inline=True,
        )
        embed.add_field(
            name="Joined guild",
            value=str(member.get("joined") or "Not available"),
            inline=True,
        )
        embed.set_footer(text="Wynncraft API v3 • Restricted fields are not displayed")
        await interaction.followup.send(embed=embed)

    @guild.command(name="leaderboard", description="Rank members by an available statistic")
    @app_commands.choices(category=LEADERBOARD_CATEGORIES)
    async def leaderboard(
        self, interaction: discord.Interaction, category: app_commands.Choice[str]
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            guild = await self.service.current()
            members = await self.service.members()
        except WynncraftAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        metric_labels = {
            "total_level": "Total level",
            "contribution": "Guild contribution",
            "wars": "Wars (API global stat)",
            "raids": "Current-guild raids",
        }
        metric = category.value
        if metric == "weekly_contribution":
            try:
                history = await self.service.history("week")
            except (aiosqlite.Error, json.JSONDecodeError):
                await interaction.followup.send(
                    "Could not read the saved weekly snapshots.", ephemeral=True
                )
                return
            baseline = history["baseline"]
            if not baseline:
                await interaction.followup.send(
                    "Weekly contribution rankings need a saved snapshot at least "
                    "7 days old. Tracking has not reached that point yet.",
                    ephemeral=True,
                )
                return
            old_contribution = {
                row.get("username", "").casefold(): row.get("contributed")
                for row in baseline["members"]
            }
            ranked = []
            for row in members:
                previous = old_contribution.get(row["username"].casefold())
                current = row.get("contributed")
                if isinstance(previous, int) and isinstance(current, int):
                    ranked.append((row["username"], max(0, current - previous)))
            label = "Tracked contribution change (7 days)"
        else:
            label = metric_labels[metric]
            ranked = []
            for row in members:
                restrictions = row.get("restrictions") or {}
                if not isinstance(restrictions, dict):
                    restrictions = {}
                data = (
                    {}
                    if restrictions.get("main_access") is True
                    else row.get("globalData") or {}
                )
                if not isinstance(data, dict):
                    data = {}
                if metric == "total_level":
                    value = data.get("totalLevel")
                elif metric == "wars":
                    value = data.get("wars")
                elif metric == "raids":
                    raids = data.get("currentGuildRaids")
                    value = raids.get("total") if isinstance(raids, dict) else None
                else:
                    value = row.get("contributed")
                if isinstance(value, (int, float)):
                    ranked.append((row["username"], value))
        ranked.sort(key=lambda item: item[1], reverse=True)
        embed = base_embed(
            f"🏆 {guild_title(guild, self.settings)} · {category.name}",
            self.settings.accent_color,
            "\n".join(
                f"**{index}.** {name} — {format_number(value)}"
                for index, (name, value) in enumerate(ranked[:20], start=1)
            )
            or "No member values for this statistic are available.",
        )
        embed.set_footer(text=f"Bot-calculated from Wynncraft API v3 member data • {label}")
        await interaction.followup.send(embed=embed)

    @guild.command(name="territories", description="Show currently owned territories")
    async def territories(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            guild = await self.service.current()
            territories = await self.service.owned_territories()
        except WynncraftAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        rows = sorted(territories.items(), key=lambda item: item[0].casefold())
        view = TerritoryView(
            rows,
            f"🗺️ {guild_title(guild, self.settings)} · Territories",
            self.settings.success_color,
        )
        await interaction.followup.send(embed=view.make_embed(), view=view)

    @guild.command(name="history", description="Compare saved guild snapshots")
    @app_commands.choices(
        period=[
            app_commands.Choice(name="Daily (24 hours)", value="day"),
            app_commands.Choice(name="Weekly (7 days)", value="week"),
        ]
    )
    async def history(
        self, interaction: discord.Interaction, period: app_commands.Choice[str]
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            await self.service.capture_snapshot()
            guild = await self.service.current()
            history = await self.service.history(period.value)
        except WynncraftAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except (aiosqlite.Error, json.JSONDecodeError):
            await interaction.followup.send(
                "Could not read or save historical data. Check database storage and try again.",
                ephemeral=True,
            )
            return
        embed = base_embed(
            f"📜 {guild_title(guild, self.settings)} · "
            f"{period.name} history",
            self.settings.accent_color,
        )
        baseline = history["baseline"]
        if baseline is None:
            first = history["first"]
            start_date = (
                first["captured_at"].replace("+00:00", " UTC")
                if first
                else "not yet recorded"
            )
            embed.description = (
                f"Tracking began: **{start_date}**.\n"
                f"No saved snapshot is at least {history['days']} day(s) old yet. "
                "Daily captures will build the comparison history automatically."
            )
            await interaction.followup.send(embed=embed)
            return

        try:
            current_members = await self.service.members()
            territory_names = set(await self.service.owned_territories())
        except WynncraftAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        previous_members = {
            row.get("username", "").casefold(): row for row in baseline["members"]
        }
        current_names = {row["username"].casefold() for row in current_members}
        guild_members = guild.get("members")
        api_member_count = (
            guild_members.get("total") if isinstance(guild_members, dict) else None
        )
        current_member_count = (
            api_member_count if isinstance(api_member_count, int) else len(current_names)
        )
        member_growth = current_member_count - baseline["member_count"]
        previous_territories = set(baseline["territories"])
        added = sorted(territory_names - previous_territories)
        lost = sorted(previous_territories - territory_names)
        embed.description = (
            f"Baseline: **{baseline['captured_at'].replace('+00:00', ' UTC')}**\n"
            f"Member change: **{member_growth:+}** "
            f"({baseline['member_count']:,} → {current_member_count:,})\n"
            f"Guild level: **{_delta(baseline['guild_level'], guild.get('level'))}**\n"
            f"Level progress: **{_delta(baseline['xp_percent'], guild.get('xpPercent'), '%')}**\n"
            f"Territories: **{_delta(baseline['territory_count'], len(territory_names))}**\n"
            f"Wars: **{_delta(baseline['guild_wars'], guild.get('wars'))}**\n"
            f"Raids: **{_delta(baseline['guild_raids'], guild.get('raids'))}**"
        )
        embed.add_field(
            name="Territory changes",
            value=(
                f"Acquired: {', '.join(added) if added else 'None recorded'}\n"
                f"Lost: {', '.join(lost) if lost else 'None recorded'}"
            ),
            inline=False,
        )
        embed.add_field(
            name="Contribution tracking",
            value=(
                "Weekly member contribution changes are available in "
                "`/guild leaderboard` when both snapshots include that member."
            ),
            inline=False,
        )
        await interaction.followup.send(embed=embed)

    @guild.command(name="refresh", description="Refresh guild data and save a snapshot")
    @app_commands.default_permissions(manage_guild=True)
    async def refresh(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not interaction.permissions.manage_guild:
            await interaction.response.send_message(
                "This command is restricted to server members with Manage Server.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            self.service.api.cache.clear()
            await self.service.capture_snapshot()
            guild = await self.service.current()
        except WynncraftAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except aiosqlite.Error:
            await interaction.followup.send(
                "Could not save the historical snapshot. Check database storage and try again.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"Refreshed **{guild_title(guild, self.settings)}** and "
            "saved a historical snapshot.",
            ephemeral=True,
        )

    @guild.command(name="help", description="Show guild companion command help")
    async def help(self, interaction: discord.Interaction) -> None:
        embed = base_embed(
            f"📖 {self.settings.display_name} · Guild Companion",
            self.settings.accent_color,
            "Guild intelligence, drawn from Wynncraft's public API.",
        )
        embed.add_field(
            name="Commands",
            value=(
                "`/guild info` · guild overview\n"
                "`/guild members` · browse, filter, and search members\n"
                "`/guild member username` · public member profile\n"
                "`/guild leaderboard category` · member rankings\n"
                "`/guild territories` · current territory holdings\n"
                "`/guild history period` · compare saved snapshots\n"
                "`/guild refresh` · staff-only refresh and snapshot"
            ),
            inline=False,
        )
        embed.add_field(
            name="Data notes",
            value=(
                "Player details follow Wynncraft API privacy settings. Historical "
                "comparisons begin only after snapshots have been collected. "
                "Territory regions and total lifetime guild XP are not exposed "
                "by the fields this companion uses."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed)


def _delta(old: Any, new: Any, suffix: str = "") -> str:
    if not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
        return "Not available"
    difference = new - old
    return f"{difference:+g}{suffix} ({old:g}{suffix} → {new:g}{suffix})"
