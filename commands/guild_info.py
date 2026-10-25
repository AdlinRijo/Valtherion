from typing import Any

import discord

from commands.guild import RANK_LABELS, base_embed, format_number, guild, guild_title
from config import Settings
from services.guild_service import RANK_ORDER
from services.wynncraft_api import WynncraftAPIError


@guild.command(name="info", description="Show the guild overview")
async def info(interaction: discord.Interaction) -> None:
    bot = interaction.client
    settings: Settings = bot.settings
    service = bot.guild_service
    await interaction.response.defer(thinking=True)
    try:
        guild_data = await service.current()
    except WynncraftAPIError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return

    territory_note = ""
    try:
        territories: dict[str, dict[str, Any]] | None = (
            await service.owned_territories()
        )
    except WynncraftAPIError as exc:
        territories = None
        territory_note = f"\nTerritory details unavailable: {exc}"
    members = guild_data.get("members", {})
    if not isinstance(members, dict):
        members = {}

    embed = base_embed(
        f"🏰 {guild_title(guild_data, settings)}",
        settings.accent_color,
        "Guild overview",
    )
    level_progress = (
        f"{guild_data.get('xpPercent', 'NIL')}%"
        if isinstance(guild_data.get("xpPercent"), (int, float))
        else "NIL"
    )
    embed.add_field(
        name="Guild",
        value=(
            f"**Level:** {format_number(guild_data.get('level'))}\n"
            f"**Level progress:** {level_progress}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Activity",
        value=(
            f"**Members:** {format_number(members.get('total'))}\n"
            f"**Online:** {format_number(guild_data.get('online'))}\n"
            f"**Territories:** "
            f"{format_number(len(territories) if territories is not None else guild_data.get('territories'))}\n"
            f"**Wars:** {format_number(guild_data.get('wars'))}\n"
            f"**Raids:** {format_number(guild_data.get('raids'))}"
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
            f"{len(rank_members) if isinstance(rank_members, dict) else 'NIL'}"
        )
    embed.add_field(name="Ranks", value="\n".join(rank_counts), inline=True)
    embed.add_field(
        name="Founded",
        value=str(guild_data.get("created") or "NIL"),
        inline=True,
    )
    embed.add_field(
        name="Guild experience",
        value="Lifetime XP: NIL",
        inline=False,
    )
    embed.add_field(
        name="Companion tools",
        value=(
            "`/item name` — look up Wynncraft item details\n"
            "`/news latest` — view recent Wynncraft announcements\n"
            "`/valt help` — Valtherion command help"
        ),
        inline=False,
    )
    season_ranks = guild_data.get("seasonRanks")
    if isinstance(season_ranks, dict) and season_ranks:
        season_text = "\n".join(
            f"**{season}:** rating {data.get('rating', 'NIL')} · "
            f"{data.get('finalTerritories', 'NIL')} final territories"
            for season, data in list(season_ranks.items())[:5]
            if isinstance(data, dict)
        )
        if season_text:
            embed.add_field(name="Season records", value=season_text, inline=False)
    await interaction.followup.send(embed=embed)
