import discord

from commands.guild import MemberDirectoryView, guild, guild_title
from services.wynncraft_api import WynncraftAPIError


@guild.command(name="members", description="Browse guild members")
async def members(interaction: discord.Interaction) -> None:
    bot = interaction.client
    service = bot.guild_service
    await interaction.response.defer(thinking=True)
    try:
        guild_data = await service.current()
        member_rows = await service.members()
    except WynncraftAPIError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    view = MemberDirectoryView(
        member_rows,
        f"⚔️ {guild_title(guild_data, bot.settings)} · Members",
        bot.settings.accent_color,
    )
    await interaction.followup.send(embed=view.make_embed(), view=view)
