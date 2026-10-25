import discord
from discord import app_commands

from commands.guild import guild, guild_title
from services.wynncraft_api import WynncraftAPIError


@guild.command(name="refresh", description="Refresh guild data")
@app_commands.default_permissions(manage_guild=True)
async def refresh(interaction: discord.Interaction) -> None:
    bot = interaction.client
    if interaction.guild is None or not interaction.permissions.manage_guild:
        await interaction.response.send_message(
            "This command is restricted to server members with Manage Server.",
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        bot.guild_service.api.cache.clear()
        guild_data = await bot.guild_service.current()
    except WynncraftAPIError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    await interaction.followup.send(
        f"Refreshed **{guild_title(guild_data, bot.settings)}**.",
        ephemeral=True,
    )
