import discord
from discord import app_commands
from discord.ext import commands

from commands.guild import base_embed

valt = app_commands.Group(name="valt", description="Valtherion bot commands")


@valt.command(name="help", description="Show Valtherion bot command help")
async def help_command(interaction: discord.Interaction) -> None:
    settings = interaction.client.settings
    embed = base_embed(
        f"📖 {settings.display_name} · Valtherion",
        settings.accent_color,
        "Guild information, item lookups, and Wynncraft announcements.",
    )
    embed.add_field(
        name="Commands",
        value=(
            "`/guild info` · guild overview\n"
            "`/guild members` · browse, filter, and search members\n"
            "`/guild member username` · public member profile\n"
            "`/guild leaderboard category` · member rankings\n"
            "`/guild territories` · current territory holdings\n"
            "`/guild refresh` · staff-only data refresh\n"
            "`/item name` · Wynncraft item details\n"
            "`/news latest` · latest Wynncraft announcements\n"
            "`/valt help` · show this help"
        ),
        inline=False,
    )
    embed.add_field(
        name="Data notes",
        value=(
            "Player details follow Wynncraft privacy settings. "
            "Territory regions and total lifetime guild XP are not exposed "
            "by the fields this companion uses. Data is fetched on demand "
            "and kept only in short-lived memory cache."
        ),
        inline=False,
    )
    await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(valt)
