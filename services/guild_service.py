from typing import Any

from services.wynncraft_api import WynncraftAPI

RANK_ORDER = ("owner", "chief", "strategist", "recruiter", "recruit")


class GuildService:
    def __init__(self, api: WynncraftAPI) -> None:
        self.api = api

    async def current(self) -> dict[str, Any]:
        return await self.api.get_guild()

    async def members(self) -> list[dict[str, Any]]:
        guild = await self.current()
        result: list[dict[str, Any]] = []
        member_data = guild.get("members", {})
        if not isinstance(member_data, dict):
            return result
        for rank in RANK_ORDER:
            rank_members = member_data.get(rank, {})
            if not isinstance(rank_members, dict):
                continue
            for username, member in rank_members.items():
                if isinstance(member, dict):
                    result.append(
                        {
                            **member,
                            "username": member.get("username", username),
                            "rank": rank,
                        }
                    )
        return sorted(result, key=lambda member: member["username"].casefold())

    async def owned_territories(self) -> dict[str, dict[str, Any]]:
        guild = await self.current()
        territories = await self.api.get_territories()
        prefix = str(guild.get("prefix") or "").casefold()
        name = str(guild.get("name") or "").casefold()
        owned = {}
        for territory_name, territory in territories.items():
            if not isinstance(territory, dict):
                continue
            owner = territory.get("guild", {})
            if not isinstance(owner, dict):
                continue
            if (
                owner.get("uuid") == guild.get("uuid")
                or (
                    str(owner.get("name") or "").casefold() == name
                    and str(owner.get("prefix") or "").casefold() == prefix
                )
            ):
                owned[territory_name] = territory
        return owned
