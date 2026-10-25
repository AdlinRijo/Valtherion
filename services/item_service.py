from typing import Any

from services.wynncraft_api import WynncraftAPI


class ItemService:
    def __init__(self, api: WynncraftAPI) -> None:
        self.api = api

    async def search(self, query: str) -> list[dict[str, Any]]:
        return await self.api.search_items(query)
