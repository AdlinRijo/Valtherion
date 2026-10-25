import re
from html.parser import HTMLParser
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from config import Settings
from services.item_service import ItemService
from services.wynncraft_api import WynncraftAPIError

ITEM_GUIDE_URL = "https://wynncraft.com/help/item-guide"


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: Any) -> str:
    parser = _HTMLText()
    parser.feed(str(value))
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def _clip(value: str, limit: int = 1024) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _stat_lines(stats: Any) -> str:
    if not isinstance(stats, dict) or not stats:
        return "None listed"
    lines = []
    for name, value in stats.items():
        label = re.sub(r"(?<!^)(?=[A-Z])", " ", str(name))
        label = label[0].upper() + label[1:] if label else label
        if isinstance(value, dict):
            raw = value.get("raw")
            minimum = value.get("min")
            maximum = value.get("max")
            if raw is not None:
                detail = f"{raw:+}"
                if minimum is not None and maximum is not None:
                    detail += f" ({minimum:+} to {maximum:+})"
            else:
                detail = _plain_text(value)
        else:
            detail = str(value)
        lines.append(f"**{_clip(label, 80)}:** {_plain_text(detail)}")
    return _clip("\n".join(lines))


def item_embed(item: dict[str, Any], color: int) -> discord.Embed:
    name = _plain_text(item.get("displayName") or item.get("internalName") or "Item")
    requirements = item.get("requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    requirement_lines = [
        f"**{_label(key)}:** {value}"
        for key, value in requirements.items()
    ]
    overview = [
        f"**Type:** {_plain_text(item.get('type', 'Unknown'))}"
        + (
            f" · {_plain_text(item['subType'])}"
            if item.get("subType")
            else ""
        ),
        f"**Tier:** {_plain_text(item.get('tier', 'Unknown'))}",
    ]
    if item.get("attackSpeed"):
        overview.append(f"**Attack speed:** {_plain_text(item['attackSpeed'])}")
    if item.get("averageDps") is not None:
        overview.append(f"**Average DPS:** {item['averageDps']}")
    if item.get("elements"):
        elements = item["elements"]
        if isinstance(elements, list):
            overview.append(f"**Elements:** {_plain_text(', '.join(map(str, elements)))}")

    embed = discord.Embed(
        title=_clip(name, 256),
        url=ITEM_GUIDE_URL,
        description="\n".join(overview),
        color=color,
    )
    embed.add_field(
        name="Requirements",
        value=_clip("\n".join(requirement_lines) or "None listed"),
        inline=True,
    )
    embed.add_field(
        name="Identifications",
        value=_stat_lines(item.get("identifications")),
        inline=True,
    )
    embed.add_field(
        name="Base stats",
        value=_stat_lines(item.get("base")),
        inline=True,
    )

    details = []
    if item.get("internalName"):
        details.append(f"**Internal name:** {_plain_text(item['internalName'])}")
    if item.get("emblem"):
        details.append(f"**Emblem:** {_plain_text(item['emblem'])}")
    for key in ("set", "gathering", "restriction", "dropRestriction", "powderSlots"):
        if item.get(key) is not None:
            label = _label(key)
            details.append(f"**{label}:** {_plain_text(item[key])}")
    icon = item.get("icon")
    icon_value = icon.get("value") if isinstance(icon, dict) else None
    if isinstance(icon_value, dict):
        icon_name = icon_value.get("name")
        icon_id = icon_value.get("id")
        icon_model = icon_value.get("customModelData")
        model_data = (
            icon_model.get("rangeDispatch")
            if isinstance(icon_model, dict)
            else None
        )
        icon_detail = ", ".join(
            str(value) for value in (icon_name, icon_id) if value
        )
        if model_data:
            icon_detail += f" (model data: {', '.join(map(str, model_data))})"
        if icon.get("format"):
            icon_detail += f" · {_plain_text(icon['format'])}"
        if icon_detail:
            details.append(f"**Icon:** {_plain_text(icon_detail)}")
    major_ids = item.get("majorIds")
    if isinstance(major_ids, dict):
        details.extend(
            f"**{_plain_text(key)}:** {_plain_text(value)}"
            for key, value in major_ids.items()
        )
    if details:
        embed.add_field(name="Other details", value=_clip("\n".join(details)))
    lore = _plain_text(item.get("lore", ""))
    if lore:
        embed.add_field(name="Lore", value=_clip(lore), inline=False)
    embed.set_footer(text="Wynncraft item database • Open the Item Guide")
    return embed


def _label(value: Any) -> str:
    label = re.sub(r"(?<!^)(?=[A-Z])", " ", str(value))
    return label[0].upper() + label[1:] if label else label


class ItemCommands(commands.Cog):
    def __init__(
        self, service: ItemService, settings: Settings
    ) -> None:
        self.service = service
        self.settings = settings

    @app_commands.command(name="item", description="Show full Wynncraft item details")
    @app_commands.describe(name="Item name to look up")
    async def item(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            matches = await self.service.search(name.strip())
        except WynncraftAPIError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        if not matches:
            await interaction.followup.send(
                f"No items matched **{name}**. Check the spelling and try again.",
                ephemeral=True,
            )
            return

        query = name.casefold().strip()
        exact = [
            item
            for item in matches
            if query
            in {
                str(item.get("displayName", "")).casefold(),
                str(item.get("internalName", "")).casefold(),
            }
        ]
        if exact:
            selected = exact[0]
        elif len(matches) == 1:
            selected = matches[0]
        else:
            names = [
                _plain_text(item.get("displayName") or item.get("internalName") or "")
                for item in matches[:10]
            ]
            await interaction.followup.send(
                "Several items matched. Try a more specific name:\n"
                + "\n".join(f"• {candidate}" for candidate in names),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=item_embed(selected, self.settings.accent_color)
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ItemCommands(ItemService(bot.api), bot.settings))
