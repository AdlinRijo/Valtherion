import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp

from commands.guild import (
    GuildCommands,
    MemberDirectoryView,
    TerritoryView,
    format_number,
)
from config import Settings
from database.database import Database
from services.wynncraft_api import WynncraftAPI, WynncraftAPIError


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        payload: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.payload = payload if payload is not None else {"ok": True}
        self.headers = headers or {}

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def json(self, content_type: str | None = None) -> Any:
        return self.payload


class FakeSession:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.calls = 0

    def get(self, *_: Any, **__: Any) -> FakeResponse:
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_settings() -> Settings:
    return Settings(
        discord_token="",
        wynncraft_api_token="",
        guild_name="Example Guild",
        guild_tag="EXG",
        accent_color=0x8B5CF6,
        success_color=0x2ECC71,
        database_path="unused.sqlite3",
    )


class WynncraftAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_api_token_uses_bearer_authorization_scheme(self) -> None:
        for configured, expected in (
            ("example-token", "Bearer example-token"),
            ("Bearer example-token", "Bearer example-token"),
        ):
            api = WynncraftAPI(
                replace(test_settings(), wynncraft_api_token=configured)
            )
            with patch("services.wynncraft_api.aiohttp.ClientSession") as session:
                await api.start()
                headers = session.call_args.kwargs["headers"]
                self.assertEqual(headers["Authorization"], expected)

    async def test_placeholder_guild_name_fails_before_network_request(self) -> None:
        placeholder_settings = replace(test_settings(), guild_name="MY GUILD NAME")
        self.assertFalse(placeholder_settings.guild_configured)
        api = WynncraftAPI(placeholder_settings)
        with self.assertRaisesRegex(WynncraftAPIError, "Set your real Wynncraft"):
            await api.get_guild()

    async def test_caches_successful_response_for_server_ttl(self) -> None:
        api = WynncraftAPI(test_settings())
        session = FakeSession(
            FakeResponse(headers={"Cache-Control": "public, max-age=60"})
        )
        api.session = session  # type: ignore[assignment]

        self.assertEqual(await api.get("/guild/test"), {"ok": True})
        self.assertEqual(await api.get("/guild/test"), {"ok": True})
        self.assertEqual(session.calls, 1)

    async def test_reports_not_found_and_rate_limit(self) -> None:
        for response, expected in (
            (FakeResponse(status=404, payload={"detail": "missing"}), "No matching"),
            (FakeResponse(status=429, headers={"Retry-After": "12"}), "12 seconds"),
        ):
            api = WynncraftAPI(test_settings())
            api.session = FakeSession(response)  # type: ignore[assignment]
            with self.assertRaisesRegex(WynncraftAPIError, expected):
                await api.get("/guild/test")

    async def test_reports_request_timeout(self) -> None:
        api = WynncraftAPI(test_settings())
        api.session = FakeSession(aiohttp.ServerTimeoutError())  # type: ignore[assignment]
        with self.assertRaisesRegex(WynncraftAPIError, "timed out"):
            await api.get("/guild/test")

    async def test_rejects_unexpected_resource_shape(self) -> None:
        api = WynncraftAPI(test_settings())
        api.session = FakeSession(FakeResponse(payload=[]))  # type: ignore[assignment]
        with self.assertRaisesRegex(WynncraftAPIError, "unexpected guild response"):
            await api.get_guild()


class PersistenceAndPresentationTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_round_trip_and_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Database(str(Path(tmp) / "history.sqlite3"))
            await database.initialize()
            await database.save_snapshot(
                {
                    "level": 20,
                    "xpPercent": 40,
                    "members": {"total": 1},
                    "territories": 3,
                    "wars": 7,
                    "raids": 2,
                },
                [{"username": "ExamplePlayer", "contributed": 120}],
                {"Ragni": {"acquired": "2026-01-01T00:00:00Z"}},
            )
            rows = await database.all_snapshots()
            self.assertEqual(rows[0]["members"][0]["contributed"], 120)
            self.assertIn("Ragni", rows[0]["territories"])
            self.assertEqual(rows[0]["guild_level"], 20)
            await database.close()

    async def test_member_and_territory_pagination(self) -> None:
        rows = [
            {"username": f"Player{index}", "rank": "recruit", "contributed": index}
            for index in range(23)
        ]
        directory = MemberDirectoryView(rows, "Test", 0x123456)
        self.assertEqual(len(directory.make_embed().description.splitlines()), 10)
        directory.rank = "chief"
        self.assertEqual(directory.filtered, [])
        self.assertEqual(directory.make_embed().description, "No members match this filter.")

        territories = TerritoryView(
            [(f"Territory{index}", {}) for index in range(23)], "Test", 0x123456
        )
        self.assertEqual(len(territories.make_embed().fields), 11)
        territories.page = 2
        self.assertEqual(len(territories.make_embed().fields), 1)

    def test_refresh_requires_manage_server(self) -> None:
        refresh = GuildCommands.guild.get_command("refresh")
        self.assertIsNotNone(refresh.default_permissions)
        self.assertTrue(refresh.default_permissions.manage_guild)
        self.assertEqual(format_number(None), "Not available")

    async def test_slow_command_defers_before_fetching_api_data(self) -> None:
        events: list[str] = []

        class Service:
            async def current(self) -> dict[str, Any]:
                events.append("fetch")
                return {
                    "name": "Example Guild",
                    "prefix": "EXG",
                    "level": 20,
                    "xpPercent": 40,
                    "members": {"total": 1},
                    "online": 0,
                    "territories": 0,
                    "wars": 0,
                    "raids": 0,
                }

            async def owned_territories(self) -> dict[str, Any]:
                return {}

        interaction = type(
            "Interaction",
            (),
            {
                "response": type(
                    "Response",
                    (),
                    {
                        "defer": AsyncMock(
                            side_effect=lambda **_: events.append("defer")
                        )
                    },
                )(),
                "followup": type(
                    "Followup", (), {"send": AsyncMock()}
                )(),
            },
        )()
        cog = GuildCommands(None, Service(), test_settings())  # type: ignore[arg-type]

        await GuildCommands.info.callback(cog, interaction)

        self.assertEqual(events, ["defer", "fetch"])
        interaction.followup.send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
