from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from config import Settings
from services.news_service import NewsService
from services.wynncraft_api import WynncraftAPIError


def _date_label(value: Any) -> str:
    if not isinstance(value, str):
        return "Date unavailable"
    try:
        published = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return discord.utils.format_dt(published, style="D")


class NewsCommands(commands.Cog):
    news = app_commands.Group(name="news", description="Wynncraft announcements")

    def __init__(self, service: NewsService, settings: Settings) -> None:
        self.service = service
        self.settings = settings

    @news.command(name="latest", description="Show the latest Wynncraft announcements")
    async def latest(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            articles = await self.service.latest()
        except WynncraftAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        embed = discord.Embed(
            title="📣 Latest Wynncraft Announcements",
            color=self.settings.accent_color,
        )
        for article in articles:
            title = str(article.get("title") or "Untitled announcement")
            article_type = str(article.get("type") or "announcement").title()
            recap = str(article.get("recap") or "No summary available.")
            if len(recap) > 1024:
                recap = recap[:1023] + "…"
            embed.add_field(
                name=f"{title[:220]} · {article_type}",
                value=f"{recap}\n\nPublished {_date_label(article.get('published_at'))}",
                inline=False,
            )
        if not articles:
            embed.description = "No published announcements are currently available."
        embed.set_footer(text="Source: Wynncraft published articles")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NewsCommands(NewsService(bot.api), bot.settings))
