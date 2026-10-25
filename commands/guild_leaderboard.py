import discord

from commands.guild import LEADERBOARD_CATEGORIES, format_number, guild, guild_title, base_embed
from services.wynncraft_api import WynncraftAPIError


@guild.command(name="leaderboard", description="Rank members by an available statistic")
@discord.app_commands.choices(category=LEADERBOARD_CATEGORIES)
async def leaderboard(
    interaction: discord.Interaction,
    category: discord.app_commands.Choice[str],
) -> None:
    bot = interaction.client
    service = bot.guild_service
    await interaction.response.defer(thinking=True)
    try:
        guild_data = await service.current()
        members = await service.members()
    except WynncraftAPIError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return

    metric = category.value
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
        f"🏆 {guild_title(guild_data, bot.settings)} · {category.name}",
        bot.settings.accent_color,
        "\n".join(
            f"**{index}.** {name} — {format_number(value)}"
            for index, (name, value) in enumerate(ranked[:20], start=1)
        )
        or "NIL",
    )
    embed.set_footer(text=f"Calculated from member data • {category.name}")
    await interaction.followup.send(embed=embed)
