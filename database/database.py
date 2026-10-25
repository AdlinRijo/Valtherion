import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self.connection: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                guild_level INTEGER,
                xp_percent INTEGER,
                member_count INTEGER NOT NULL,
                territory_count INTEGER NOT NULL,
                guild_wars INTEGER,
                guild_raids INTEGER,
                members_json TEXT NOT NULL,
                territories_json TEXT NOT NULL
            )
            """
        )
        await self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshots_captured_at "
            "ON snapshots(captured_at)"
        )
        await self.connection.commit()

    async def save_snapshot(
        self,
        guild: dict[str, Any],
        members: list[dict[str, Any]],
        territories: dict[str, Any],
    ) -> None:
        if self.connection is None:
            raise RuntimeError("Database is not initialized")
        guild_members = guild.get("members")
        member_count = (
            guild_members.get("total", len(members))
            if isinstance(guild_members, dict)
            else len(members)
        )
        territory_count = guild.get("territories")
        if not isinstance(territory_count, int):
            territory_count = len(territories)
        await self.connection.execute(
            """
            INSERT INTO snapshots (
                captured_at, guild_level, xp_percent, member_count, territory_count,
                guild_wars, guild_raids, members_json, territories_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                guild.get("level"),
                guild.get("xpPercent"),
                member_count,
                territory_count,
                guild.get("wars"),
                guild.get("raids"),
                json.dumps(members),
                json.dumps(territories),
            ),
        )
        await self.connection.commit()

    async def snapshots_before(self, timestamp: datetime) -> list[dict[str, Any]]:
        if self.connection is None:
            raise RuntimeError("Database is not initialized")
        cursor = await self.connection.execute(
            """
            SELECT captured_at, guild_level, xp_percent, member_count,
                   territory_count, guild_wars, guild_raids,
                   members_json, territories_json
            FROM snapshots
            WHERE captured_at <= ?
            ORDER BY captured_at DESC
            """,
            (timestamp.isoformat(),),
        )
        rows = await cursor.fetchall()
        return [self._decode_row(row) for row in rows]

    async def all_snapshots(self) -> list[dict[str, Any]]:
        if self.connection is None:
            raise RuntimeError("Database is not initialized")
        cursor = await self.connection.execute(
            """
            SELECT captured_at, guild_level, xp_percent, member_count,
                   territory_count, guild_wars, guild_raids,
                   members_json, territories_json
            FROM snapshots ORDER BY captured_at ASC
            """
        )
        return [self._decode_row(row) for row in await cursor.fetchall()]

    @staticmethod
    def _decode_row(row: tuple[Any, ...]) -> dict[str, Any]:
        keys = (
            "captured_at",
            "guild_level",
            "xp_percent",
            "member_count",
            "territory_count",
            "guild_wars",
            "guild_raids",
            "members_json",
            "territories_json",
        )
        result = dict(zip(keys, row))
        result["members"] = json.loads(result.pop("members_json"))
        result["territories"] = json.loads(result.pop("territories_json"))
        return result

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None
