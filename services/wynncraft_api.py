import logging
from time import monotonic
from typing import Any
from urllib.parse import quote

import aiohttp

from config import Settings

logger = logging.getLogger(__name__)


class WynncraftAPIError(Exception):
    pass


class WynncraftAPI:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session: aiohttp.ClientSession | None = None
        self.cache: dict[str, tuple[float, Any]] = {}

    async def start(self) -> None:
        headers = {"User-Agent": "WynncraftGuildCompanion/1.0"}
        if self.settings.wynncraft_api_token:
            token = self.settings.wynncraft_api_token.strip()
            if not token.lower().startswith("bearer "):
                token = f"Bearer {token}"
            headers["Authorization"] = token
        timeout = aiohttp.ClientTimeout(total=15)
        self.session = aiohttp.ClientSession(headers=headers, timeout=timeout)

    async def get_guild(self) -> dict[str, Any]:
        if not self.settings.guild_configured:
            raise WynncraftAPIError(
                "Set your real Wynncraft guild name in GUILD_NAME before using commands."
            )
        payload = await self.get(
            f"/guild/{quote(self.settings.guild_name, safe='')}",
            params={"identifier": "username"},
        )
        if not isinstance(payload, dict):
            raise WynncraftAPIError("Wynncraft returned an unexpected guild response.")
        return payload

    async def get_player(self, username: str) -> dict[str, Any]:
        payload = await self.get(f"/player/{quote(username, safe='')}")
        if not isinstance(payload, dict):
            raise WynncraftAPIError("Wynncraft returned an unexpected player response.")
        return payload

    async def search_items(self, query: str) -> list[dict[str, Any]]:
        payload = await self.get(f"/item/search/{quote(query, safe='')}")
        if not isinstance(payload, list) or any(
            not isinstance(item, dict) for item in payload
        ):
            raise WynncraftAPIError("Wynncraft returned an unexpected item response.")
        return payload

    async def get_latest_articles(self) -> list[dict[str, Any]]:
        payload = await self.get(
            "/publisher/articles/list/article",
            params={"page": "1"},
        )
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, dict) or any(
            not isinstance(article, dict) for article in results.values()
        ):
            raise WynncraftAPIError("Wynncraft returned an unexpected news response.")
        return list(results.values())

    async def get_territories(self) -> dict[str, Any]:
        payload = await self.get("/guild/list/territory")
        if not isinstance(payload, dict):
            raise WynncraftAPIError(
                "Wynncraft returned an unexpected territory response."
            )
        return payload

    async def get(
        self, path: str, params: dict[str, str] | None = None
    ) -> Any:
        if self.session is None:
            raise RuntimeError("Wynncraft API session has not been started")
        query = ""
        if params:
            query = "?" + "&".join(
                f"{quote(key)}={quote(value)}" for key, value in sorted(params.items())
            )
        cache_key = f"{path}{query}"
        cached = self.cache.get(cache_key)
        now = monotonic()
        if cached and cached[0] > now:
            return cached[1]
        if self.cache:
            self.cache = {
                key: value for key, value in self.cache.items() if value[0] > now
            }

        url = f"{self.settings.api_base_url}{path}"
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 429:
                    retry = response.headers.get("Retry-After", "a short time")
                    raise WynncraftAPIError(
                        f"Wynncraft API rate limit reached; retry after {retry} seconds."
                    )
                try:
                    payload = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    raise WynncraftAPIError(
                        f"Wynncraft API returned an unreadable response (HTTP {response.status})."
                    ) from exc
                if response.status >= 400:
                    detail = payload.get("detail") if isinstance(payload, dict) else None
                    if response.status == 404:
                        raise WynncraftAPIError("No matching public Wynncraft record was found.")
                    raise WynncraftAPIError(
                        detail or f"Wynncraft API returned HTTP {response.status}."
                    )
                ttl = _cache_ttl(response.headers.get("Cache-Control", ""))
                self.cache[cache_key] = (now + ttl, payload)
                return payload
        except TimeoutError as exc:
            raise WynncraftAPIError(
                "The Wynncraft API request timed out. Please try again shortly."
            ) from exc
        except aiohttp.ClientError as exc:
            logger.warning("Wynncraft API request failed: %s", type(exc).__name__)
            raise WynncraftAPIError(
                "Could not connect to the Wynncraft API. Please try again shortly."
            ) from exc

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None


def _cache_ttl(header: str) -> int:
    for directive in header.split(","):
        key, separator, value = directive.strip().partition("=")
        if separator and key.lower() == "max-age":
            try:
                return max(0, min(int(value), 3600))
            except ValueError:
                break
    return 30
