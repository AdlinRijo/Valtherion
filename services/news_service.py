from datetime import datetime, timezone
from typing import Any

from services.wynncraft_api import WynncraftAPI


class NewsService:
    def __init__(self, api: WynncraftAPI) -> None:
        self.api = api

    async def latest(self, limit: int = 5) -> list[dict[str, Any]]:
        articles = await self.api.get_latest_articles()
        articles = [
            article for article in articles if article.get("visible") is not False
        ]
        articles.sort(key=_published_at, reverse=True)
        return articles[:limit]


def _published_at(article: dict[str, Any]) -> datetime:
    value = article.get("published_at")
    if not isinstance(value, str):
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
