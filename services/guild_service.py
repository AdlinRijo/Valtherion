from datetime import datetime, timedelta, timezone
from typing import Any

from config import Settings
from database.database import Database
from services.wynncraft_api import WynncraftAPI

RANK_ORDER = ("owner", "chief", "strategist", "recruiter", "recruit")


class GuildService:
    def __init__(
        self, api: WynncraftAPI, database: Database, settings: Settings
    ) -> None:
        self.api = api
        self.database = database
        self.settings = settings

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

    async def capture_snapshot(self) -> None:
        guild = await self.current()
        territories = await self.api.get_territories()
        owned = {
            territory_name: territory
            for territory_name, territory in territories.items()
            if isinstance(territory, dict)
            and isinstance(territory.get("guild"), dict)
            and territory["guild"].get("uuid") == guild.get("uuid")
        }
        member_rows = _member_rows(guild)
        await self.database.save_snapshot(guild, member_rows, owned)

    async def history(self, period: str) -> dict[str, Any]:
        days = 1 if period == "day" else 7
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        baselines = await self.database.snapshots_before(cutoff)
        all_rows = await self.database.all_snapshots()
        return {
            "baseline": baselines[0] if baselines else None,
            "first": all_rows[0] if all_rows else None,
            "days": days,
        }


def _member_rows(guild: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    member_data = guild.get("members", {})
    if not isinstance(member_data, dict):
        return rows
    for rank in RANK_ORDER:
        members = member_data.get(rank, {})
        if isinstance(members, dict):
            for username, member in members.items():
                if isinstance(member, dict):
                    rows.append(
                        {
                            **member,
                            "username": member.get("username", username),
                            "rank": rank,
                        }
                    )
    return rows
