import unittest
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp

from commands.guild import (
    MemberDirectoryView,
    TerritoryView,
    base_embed,
    format_number,
    guild,
)
from commands.item import ITEM_GUIDE_URL, ItemCommands, item_embed
from commands.news import NewsCommands
from config import Settings
from main import GuildCompanionBot
from services.news_service import NewsService
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
        self.requests: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def get(self, *args: Any, **kwargs: Any) -> FakeResponse:
        self.calls += 1
        self.requests.append((args, kwargs))
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

    async def test_searches_items_and_loads_published_news(self) -> None:
        item_api = WynncraftAPI(test_settings())
        item_session = FakeSession(
            FakeResponse(payload=[{"displayName": "The Item"}])
        )
        item_api.session = item_session  # type: ignore[assignment]
        self.assertEqual(
            await item_api.search_items("The Item"),
            [{"displayName": "The Item"}],
        )
        self.assertTrue(
            item_session.requests[0][0][0].endswith("/item/search/The%20Item")
        )

        news_api = WynncraftAPI(test_settings())
        news_api.session = FakeSession(
            FakeResponse(
                payload={
                    "results": {
                        "1": {"title": "News", "visible": True},
                    }
                }
            )
        )  # type: ignore[assignment]
        self.assertEqual(
            await news_api.get_latest_articles(),
            [{"title": "News", "visible": True}],
        )

    async def test_api_rejects_unexpected_item_and_news_shapes(self) -> None:
        for method, response in (
            ("search_items", FakeResponse(payload={"results": []})),
            ("get_latest_articles", FakeResponse(payload={"results": []})),
        ):
            api = WynncraftAPI(test_settings())
            api.session = FakeSession(response)  # type: ignore[assignment]
            with self.assertRaisesRegex(WynncraftAPIError, "unexpected"):
                if method == "search_items":
                    await api.search_items("sword")
                else:
                    await api.get_latest_articles()


class ItemAndNewsTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_registers_each_command_module(self) -> None:
        bot = GuildCompanionBot()
        bot.api.start = AsyncMock()
        bot.tree.sync = AsyncMock()
        try:
            await bot.setup_hook()
            guild_command = bot.tree.get_command("guild")
            self.assertIsNotNone(guild_command)
            self.assertEqual(
                {command.name for command in guild_command.commands},
                {
                    "info",
                    "leaderboard",
                    "member",
                    "members",
                    "refresh",
                    "territories",
                },
            )
            valt = bot.tree.get_command("valt")
            self.assertIsNotNone(valt)
            self.assertIsNotNone(valt.get_command("help"))
            self.assertIsNotNone(bot.tree.get_command("item"))
            news = bot.tree.get_command("news")
            self.assertIsNotNone(news)
            self.assertIsNotNone(news.get_command("latest"))
            bot.tree.sync.assert_awaited_once()
        finally:
            await bot.close()

    async def test_item_embed_includes_details_and_item_guide_link(self) -> None:
        embed = item_embed(
            {
                "displayName": "Example Blade",
                "internalName": "Example_Blade",
                "type": "weapon",
                "subType": "dagger",
                "tier": "legendary",
                "emblem": "diamond_5",
                "icon": {
                    "format": "attribute",
                    "value": {
                        "name": "dagger.example",
                        "id": "minecraft:item",
                        "customModelData": {"rangeDispatch": [42]},
                    },
                },
                "requirements": {"level": 90, "dexterity": 50},
                "identifications": {"walkSpeed": {"min": 10, "raw": 15, "max": 20}},
                "base": {"baseDamage": {"min": 100, "raw": 100, "max": 150}},
                "majorIds": {"Quick Strike": "<span>Deal more damage</span>"},
                "lore": "<span>A sharp blade</span>",
            },
            0x123456,
        )

        self.assertEqual(embed.title, "Example Blade")
        self.assertEqual(embed.url, ITEM_GUIDE_URL)
        self.assertIn("weapon", embed.description)
        fields = {field.name: field.value for field in embed.fields}
        self.assertIn("Level", fields["Requirements"])
        self.assertIn("Walk Speed", fields["Identifications"])
        self.assertIn("Base Damage", fields["Base stats"])
        self.assertIn("Deal more damage", fields["Other details"])
        self.assertIn("Example_Blade", fields["Other details"])
        self.assertIn("model data: 42", fields["Other details"])
        self.assertEqual(fields["Lore"], "A sharp blade")

    async def test_news_service_returns_latest_visible_articles(self) -> None:
        class API:
            async def get_latest_articles(self) -> list[dict[str, Any]]:
                return [
                    {
                        "title": "Older",
                        "visible": True,
                        "published_at": "2025-01-01T00:00:00Z",
                    },
                    {
                        "title": "Hidden",
                        "visible": False,
                        "published_at": "2026-01-01T00:00:00Z",
                    },
                    {
                        "title": "Newer",
                        "visible": True,
                        "published_at": "2026-01-01T00:00:00Z",
                    },
                ]

        latest = await NewsService(API()).latest(limit=1)  # type: ignore[arg-type]
        self.assertEqual([article["title"] for article in latest], ["Newer"])
        self.assertEqual(ItemCommands.item.name, "item")
        self.assertIsNotNone(NewsCommands.news.get_command("latest"))


class PresentationTests(unittest.IsolatedAsyncioTestCase):
    async def test_member_and_territory_pagination(self) -> None:
        rows = [
            {"username": f"Player{index}", "rank": "recruit", "contributed": index}
            for index in range(23)
        ]
        directory = MemberDirectoryView(rows, "Test", 0x123456)
        lines = directory.make_embed().description.splitlines()
        self.assertEqual(len(lines[2:-1]), 10)
        self.assertTrue(lines[0].startswith("```"))
        self.assertIn("0", lines[2])
        self.assertIn("NIL", lines[2])
        directory.rank = "chief"
        self.assertEqual(directory.filtered, [])
        self.assertEqual(directory.make_embed().description, "NIL")

    async def test_member_directory_aligns_columns_and_shows_status(self) -> None:
        directory = MemberDirectoryView(
            [
                {
                    "username": "A",
                    "rank": "recruit",
                    "contributed": 8887,
                    "online": True,
                },
                {
                    "username": "LongerPlayer",
                    "rank": "chief",
                    "contributed": 108001759,
                    "online": False,
                },
            ],
            "Test",
            0x123456,
        )
        lines = directory.make_embed().description.splitlines()
        header = lines[1]
        for header_label, row_value in (("RANK", "Recruit"), ("ONLINE / OFFLINE", "Online")):
            self.assertEqual(header.index(header_label), lines[2].index(row_value))
        self.assertEqual(
            header.index("CONTRIBUTION") + len("CONTRIBUTION"),
            lines[2].index("8,887") + len("8,887"),
        )
        self.assertTrue(lines[2].endswith("Online"))
        self.assertTrue(lines[3].endswith("Offline"))

        territories = TerritoryView(
            [(f"Territory{index}", {}) for index in range(23)], "Test", 0x123456
        )
        self.assertEqual(len(territories.make_embed().fields), 11)
        self.assertIn("NIL", territories.make_embed().fields[0].value)
        territories.page = 2
        self.assertEqual(len(territories.make_embed().fields), 1)
        empty_territories = TerritoryView([], "Test", 0x123456)
        self.assertEqual(empty_territories.make_embed().description, "NIL")

    def test_embed_uses_compact_footer_without_api_version(self) -> None:
        embed = base_embed("Test", 0x123456)
        self.assertNotIn("API", embed.footer.text)
        self.assertIn("Updated", embed.footer.text)

    def test_refresh_requires_manage_server(self) -> None:
        refresh = guild.get_command("refresh")
        self.assertIsNotNone(refresh.default_permissions)
        self.assertTrue(refresh.default_permissions.manage_guild)
        self.assertEqual(format_number(None), "NIL")
        self.assertIsNone(guild.get_command("history"))
        self.assertNotIn(
            "weekly_contribution",
            {
                choice.value
                for choice in guild.get_command("leaderboard")._params[
                    "category"
                ].choices
            },
        )

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
        client = SimpleNamespace(guild_service=Service(), settings=test_settings())
        interaction.client = client

        await guild.get_command("info").callback(interaction)

        self.assertEqual(events, ["defer", "fetch"])
        interaction.followup.send.assert_awaited_once()

    async def test_guild_info_lists_item_and_news_tools(self) -> None:
        class Service:
            async def current(self) -> dict[str, Any]:
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
                "response": type("Response", (), {"defer": AsyncMock()})(),
                "followup": type(
                    "Followup", (), {"send": AsyncMock()}
                )(),
            },
        )()
        interaction.client = SimpleNamespace(
            guild_service=Service(),
            settings=test_settings(),
        )

        await guild.get_command("info").callback(interaction)

        embed = interaction.followup.send.await_args.kwargs["embed"]
        tools = next(field.value for field in embed.fields if field.name == "Companion tools")
        self.assertIn("/item name", tools)
        self.assertIn("/news latest", tools)


if __name__ == "__main__":
    unittest.main()
