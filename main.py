import asyncio
import logging
from logging.handlers import RotatingFileHandler

import aiosqlite
import discord
from discord.ext import commands

from commands.guild import GuildCommands
from config import settings
from database.database import Database
from services.guild_service import GuildService
from services.wynncraft_api import WynncraftAPI, WynncraftAPIError


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        "discord.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(console)
    root.addHandler(file_handler)
    logging.getLogger("discord").setLevel(logging.WARNING)


class GuildCompanionBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
        )
        self.api = WynncraftAPI(settings)
        self.database = Database(settings.database_path)
        self.guild_service = GuildService(self.api, self.database, settings)
        self.snapshot_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        await self.api.start()
        await self.database.initialize()
        await self.add_cog(GuildCommands(self, self.guild_service, settings))
        await self.tree.sync()
        if settings.guild_configured:
            self.snapshot_task = asyncio.create_task(self._daily_snapshots())
        else:
            logging.getLogger(__name__).warning(
                "Daily snapshots are disabled until a real GUILD_NAME is set in .env."
            )

    async def _daily_snapshots(self) -> None:
        while not self.is_closed():
            try:
                await self.guild_service.capture_snapshot()
            except WynncraftAPIError as exc:
                logging.getLogger(__name__).warning(
                    "Guild snapshot skipped: %s", exc
                )
            except aiosqlite.Error as exc:
                logging.getLogger(__name__).error(
                    "Guild snapshot could not be saved: %s", exc
                )
            await asyncio.sleep(24 * 60 * 60)

    async def close(self) -> None:
        if self.snapshot_task:
            self.snapshot_task.cancel()
            try:
                await self.snapshot_task
            except asyncio.CancelledError:
                pass
        await self.api.close()
        await self.database.close()
        await super().close()


def main() -> None:
    configure_logging()
    if not settings.discord_token:
        raise RuntimeError("DISCORD_TOKEN is required; set it in the environment.")
    bot = GuildCompanionBot()
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
