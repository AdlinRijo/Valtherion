from typing import Any

import discord

from commands.guild import RANK_LABELS, base_embed, format_number, guild, guild_title
from services.wynncraft_api import WynncraftAPIError


@guild.command(name="member", description="Show a guild member's public profile")
@discord.app_commands.describe(username="Wynncraft username")
async def member(interaction: discord.Interaction, username: str) -> None:
    bot = interaction.client
    service = bot.guild_service
    await interaction.response.defer(thinking=True)
    try:
        guild_data = await service.current()
        members = await service.members()
    except WynncraftAPIError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    member_data = next(
        (
            row
            for row in members
            if row["username"].casefold() == username.casefold()
        ),
        None,
    )
    if member_data is None:
        await interaction.followup.send(
            f"**{username}** is not listed in this guild.", ephemeral=True
        )
        return

    profile: dict[str, Any] | None = None
    profile_note = ""
    try:
        profile = await service.api.get_player(
            member_data.get("uuid") or member_data["username"]
        )
    except WynncraftAPIError:
        profile_note = "\nSome player-profile details are restricted."
    global_data = member_data.get("globalData") or {}
    if not isinstance(global_data, dict):
        global_data = {}
    if profile:
        profile_restrictions = profile.get("restrictions") or {}
        if not isinstance(profile_restrictions, dict):
            profile_restrictions = {}
        if profile_restrictions.get("mainAccess"):
            global_data = {}
            profile_note = "\nPublic player statistics are access-restricted."
        else:
            profile_data = profile.get("globalData") or {}
            global_data = profile_data if isinstance(profile_data, dict) else {}
    member_restrictions = member_data.get("restrictions") or {}
    if not isinstance(member_restrictions, dict):
        member_restrictions = {}
    if member_restrictions.get("main_access") is True:
        global_data = {}

    embed = base_embed(
        f"🛡️ {member_data['username']}",
        bot.settings.accent_color,
        f"Guild: **{guild_title(guild_data, bot.settings)}**\n"
        f"Rank: **{RANK_LABELS.get(member_data['rank'], 'NIL')}**"
        f"{profile_note}",
    )
    restrictions = (profile or {}).get("restrictions") or {}
    if not isinstance(restrictions, dict):
        restrictions = {}
    online_value = profile.get("online") if profile else member_data.get("online")
    online_restricted = (
        restrictions.get("onlineStatus", False)
        or member_restrictions.get("online_status") is True
    )
    status = (
        "NIL"
        if online_restricted or not isinstance(online_value, bool)
        else "Online"
        if online_value
        else "Offline"
    )
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(
        name="Guild contribution",
        value=format_number(member_data.get("contributed")),
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
        value=format_number(
            current_raids.get("total") if isinstance(current_raids, dict) else None
        ),
        inline=True,
    )
    embed.add_field(
        name="Joined guild",
        value=str(member_data.get("joined") or "NIL"),
        inline=True,
    )
    await interaction.followup.send(embed=embed)
