import discord

from commands.guild import TerritoryView, guild, guild_title
from services.wynncraft_api import WynncraftAPIError


@guild.command(name="territories", description="Show currently owned territories")
async def territories(interaction: discord.Interaction) -> None:
    bot = interaction.client
    service = bot.guild_service
    await interaction.response.defer(thinking=True)
    try:
        guild_data = await service.current()
        territory_data = await service.owned_territories()
    except WynncraftAPIError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    rows = sorted(territory_data.items(), key=lambda item: item[0].casefold())
    view = TerritoryView(
        rows,
        f"🗺️ {guild_title(guild_data, bot.settings)} · Territories",
        bot.settings.success_color,
    )
    await interaction.followup.send(embed=view.make_embed(), view=view)
