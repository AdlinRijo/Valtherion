import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _color(value: str, fallback: int) -> int:
    try:
        parsed = int(value.strip().removeprefix("#"), 16)
        return parsed if 0 <= parsed <= 0xFFFFFF else fallback
    except (ValueError, AttributeError):
        return fallback


def _channel_id(value: str | None) -> int | None:
    if not value or not value.strip():
        return None
    try:
        channel_id = int(value.strip())
    except ValueError as exc:
        raise ValueError("WORLD_EVENT_CHANNEL_ID must be a Discord channel ID.") from exc
    if channel_id <= 0:
        raise ValueError("WORLD_EVENT_CHANNEL_ID must be a positive Discord channel ID.")
    return channel_id


def _excluded_events(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(
        event.strip().casefold()
        for event in value.split(",")
        if event.strip()
    )


@dataclass(frozen=True)
class Settings:
    discord_token: str
    wynncraft_api_token: str
    guild_name: str
    guild_tag: str
    accent_color: int
    success_color: int
    world_event_channel_id: int | None = None
    world_event_excluded_events: frozenset[str] = frozenset()
    api_base_url: str = "https://api.wynncraft.com/v3"

    @property
    def display_name(self) -> str:
        return f"[{self.guild_tag}] {self.guild_name}" if self.guild_tag else self.guild_name

    @property
    def guild_configured(self) -> bool:
        return bool(self.guild_name) and self.guild_name.casefold() != "my guild name"


settings = Settings(
    discord_token=os.getenv("DISCORD_TOKEN", "").strip(),
    wynncraft_api_token=os.getenv("WYNNCRAFT_API_TOKEN", "").strip(),
    guild_name=os.getenv("GUILD_NAME", "MY GUILD NAME").strip(),
    guild_tag=os.getenv("GUILD_TAG", "MY GUILD TAG").strip(),
    accent_color=_color(os.getenv("ACCENT_COLOR", "8B5CF6"), 0x8B5CF6),
    success_color=_color(os.getenv("SUCCESS_COLOR", "2ECC71"), 0x2ECC71),
    world_event_channel_id=_channel_id(os.getenv("WORLD_EVENT_CHANNEL_ID")),
    world_event_excluded_events=_excluded_events(os.getenv("WORLD_EVENT_EXCLUDED")),
)
