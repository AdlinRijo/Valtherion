import importlib
import logging
import pkgutil
from logging.handlers import RotatingFileHandler

import discord
from discord.ext import commands

import commands as command_modules

from config import settings
from services.guild_service import GuildService
from services.wynncraft_api import WynncraftAPI

logger = logging.getLogger(__name__)


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
        self.guild_service = GuildService(self.api)
        self.settings = settings

    async def setup_hook(self) -> None:
        await self.api.start()
        for module_info in pkgutil.iter_modules(command_modules.__path__):
            module = importlib.import_module(
                f"{command_modules.__name__}.{module_info.name}"
            )
            setup = getattr(module, "setup", None)
            if setup is not None:
                await setup(self)
        synced = await self.tree.sync()
        logger.info("Synced %d global application commands.", len(synced))

    async def close(self) -> None:
        await self.api.close()
        await super().close()


def main() -> None:
    configure_logging()
    if not settings.discord_token:
        raise RuntimeError("DISCORD_TOKEN is required; set it in the environment.")
    bot = GuildCompanionBot()
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
