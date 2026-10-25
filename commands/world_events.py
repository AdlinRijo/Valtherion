import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

import discord
from discord.ext import commands, tasks

from config import Settings
from services.wynncraft_api import WynncraftAPI, WynncraftAPIError

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 30
SCHEDULE_LOOKAHEAD = timedelta(minutes=15)
INITIAL_DELETE_RETRY = timedelta(seconds=5)
MAX_DELETE_RETRY = timedelta(minutes=5)


def _scheduled_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        scheduled = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    return scheduled.astimezone(timezone.utc)


def _location_identity(event: dict[str, Any]) -> tuple[tuple[float, float, float], ...]:
    locations = event.get("location")
    if not isinstance(locations, list):
        return ()
    points = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        point = location.get("event")
        if not isinstance(point, dict):
            continue
        try:
            points.append(
                (
                    float(point["x"]),
                    float(point["y"]),
                    float(point["z"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(sorted(set(points)))


def _event_identity(
    event: dict[str, Any],
) -> tuple[str, str | None, tuple[tuple[float, float, float], ...]] | None:
    event_id = event.get("internalName")
    if not isinstance(event_id, str) or not event_id.strip():
        return None
    scheduled = _scheduled_at(event.get("schedule"))
    return (
        event_id.casefold(),
        scheduled.isoformat() if scheduled else None,
        _location_identity(event),
    )


def _started_status(event: dict[str, Any], now: datetime) -> tuple[bool | None, str]:
    for key in ("active", "isActive", "started", "isStarted", "inProgress"):
        value = event.get(key)
        if isinstance(value, bool):
            return value, key

    for key in ("status", "state"):
        value = event.get(key)
        if isinstance(value, str):
            normalized = value.casefold().replace("-", "_").replace(" ", "_")
            if normalized in {
                "active",
                "started",
                "in_progress",
                "running",
                "ended",
                "finished",
                "completed",
            }:
                return True, key
            if normalized in {
                "scheduled",
                "upcoming",
                "pending",
                "inactive",
            }:
                return False, key

    actual_start = _actual_start_at(event)
    if actual_start is not None:
        return actual_start <= now, "actual start timestamp"
    return None, "status unavailable"


def _actual_start_at(event: dict[str, Any]) -> datetime | None:
    for key in ("startedAt", "actualStart", "actualStartedAt"):
        started_at = _scheduled_at(event.get(key))
        if started_at is not None:
            return started_at
    return None


@dataclass
class EventAnnouncement:
    event_id: str
    event_name: str
    message_id: int
    channel_id: int
    expected_start: datetime
    locations: tuple[tuple[float, float, float], ...]
    state: str = "announced"
    started_confirmed_at: datetime | None = None
    delete_attempts: int = 0
    next_delete_attempt: datetime | None = None
    last_unknown_logged_at: datetime | None = None
    last_api_presence: bool | None = None


def _event_embed(
    event: dict[str, Any],
    scheduled: datetime,
) -> discord.Embed:
    name = str(event.get("name") or "Wynncraft World Event")
    lore = str(event.get("lore") or "A world event is starting now.")
    embed = discord.Embed(
        title=f"🌍 World Event: {name}",
        description=lore[:1000],
        color=discord.Color.gold(),
    )
    details = []
    if event.get("difficulty"):
        details.append(str(event["difficulty"]).title())
    if event.get("level") is not None:
        details.append(f"Level {event['level']}")
    if event.get("length"):
        details.append(f"{str(event['length']).title()} duration")

    embed.add_field(
        name="Starts",
        value=(
            f"{discord.utils.format_dt(scheduled, style='t')} "
            f"· {discord.utils.format_dt(scheduled, style='R')}"
        ),
        inline=False,
    )
    if details:
        embed.add_field(
            name="Event",
            value=" · ".join(details),
            inline=False,
        )

    locations = event.get("location")
    if isinstance(locations, list):
        location_lines = []
        for location in locations:
            if not isinstance(location, dict):
                continue
            point = location.get("event")
            if isinstance(point, dict) and all(
                isinstance(point.get(axis), (int, float)) for axis in ("x", "y", "z")
            ):
                location_lines.append(
                    f"X {point['x']} · Y {point['y']} · Z {point['z']}"
                )
        if location_lines:
            embed.add_field(
                name="Location",
                value=_clip("\n".join(location_lines[:10]), 1024),
                inline=False,
            )
    embed.set_footer(text="Wynncraft World Event")
    return embed


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


class WorldEventAnnouncements(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        api: WynncraftAPI,
        settings: Settings,
    ) -> None:
        self.bot = bot
        self.api = api
        self.settings = settings
        self.announcements: dict[
            tuple[str, str | None, tuple[tuple[float, float, float], ...]],
            EventAnnouncement,
        ] = {}

    async def cog_load(self) -> None:
        channel_id = self.settings.world_event_channel_id
        if channel_id is None:
            logger.info(
                "World event announcements disabled; "
                "WORLD_EVENT_CHANNEL_ID is not configured."
            )
            return
        self.poll_world_events.start()
        logger.info("World event announcements enabled for channel %s.", channel_id)

    def cog_unload(self) -> None:
        self.poll_world_events.cancel()

    @tasks.loop(seconds=POLL_INTERVAL_SECONDS)
    async def poll_world_events(self) -> None:
        await self.poll_once()

    @poll_world_events.before_loop
    async def before_poll_world_events(self) -> None:
        await self.bot.wait_until_ready()

    async def poll_once(self) -> None:
        channel_id = self.settings.world_event_channel_id
        if channel_id is None:
            return
        now = datetime.now(timezone.utc)
        try:
            events = await self.api.get_world_events()
        except WynncraftAPIError:
            logger.exception("Could not retrieve Wynncraft world events.")
            await self._retry_confirmed_deletions(now)
            return
        excluded = self.settings.world_event_excluded_events

        current_by_identity: dict[
            tuple[str, str | None, tuple[tuple[float, float, float], ...]],
            dict[str, Any],
        ] = {}
        upcoming: list[
            tuple[
                tuple[str, str | None, tuple[tuple[float, float, float], ...]],
                dict[str, Any],
                datetime,
                str,
            ]
        ] = []
        for event in events:
            name = str(event.get("name") or "")
            internal_name = str(event.get("internalName") or "")
            if name.casefold() in excluded or internal_name.casefold() in excluded:
                continue
            identity = _event_identity(event)
            if identity is None:
                logger.warning(
                    "Ignoring world event %r without a stable internalName.",
                    name,
                )
                continue
            current_by_identity[identity] = event
            scheduled = _scheduled_at(event.get("schedule"))
            status, status_source = _started_status(event, now)
            if (
                scheduled is not None
                and now < scheduled <= now + SCHEDULE_LOOKAHEAD
                and status is not True
            ):
                upcoming.append((identity, event, scheduled, status_source))

        for identity, announcement in self.announcements.items():
            if announcement.state != "announced":
                continue
            event, matched_by = self._match_current_event(
                identity,
                announcement,
                current_by_identity,
            )
            if event is None:
                if announcement.last_api_presence is not False:
                    logger.warning(
                        "World event transition event=%r id=%s "
                        "state=announced->unconfirmed_missing message_id=%s "
                        "expected_start=%s; retaining message without a state match.",
                        announcement.event_name,
                        announcement.event_id,
                        announcement.message_id,
                        announcement.expected_start.isoformat(),
                    )
                announcement.last_api_presence = False
                continue
            if announcement.last_api_presence is False:
                logger.info(
                    "World event transition event=%r id=%s "
                    "state=unconfirmed_missing->observed message_id=%s matched_by=%s",
                    announcement.event_name,
                    announcement.event_id,
                    announcement.message_id,
                    matched_by,
                )
            announcement.last_api_presence = True
            status, status_source = _started_status(event, now)
            if status is not True:
                if (
                    status is None
                    and (
                        announcement.last_unknown_logged_at is None
                        or now - announcement.last_unknown_logged_at
                        >= timedelta(minutes=5)
                    )
                ):
                    logger.warning(
                        "World event state remains unknown event=%r message_id=%s "
                        "expected_start=%s; schedule/disappearance is not treated "
                        "as start confirmation.",
                        announcement.event_name,
                        announcement.message_id,
                        announcement.expected_start.isoformat(),
                    )
                    announcement.last_unknown_logged_at = now
                continue
            announcement.state = "delete_pending"
            announcement.started_confirmed_at = now
            announcement.next_delete_attempt = now
            logger.info(
                "World event transition event=%r id=%s state=announced->started "
                "message_id=%s expected_start=%s confirmed_by=%s matched_by=%s",
                announcement.event_name,
                announcement.event_id,
                announcement.message_id,
                announcement.expected_start.isoformat(),
                status_source,
                matched_by,
            )

        await self._retry_confirmed_deletions(now)

        to_announce = [
            (identity, event, scheduled, status_source)
            for identity, event, scheduled, status_source in upcoming
            if identity not in self.announcements
        ]
        if not to_announce:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.exception(
                    "Could not access configured world event channel %s.",
                    channel_id,
                )
                return
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            logger.error(
                "Configured world event channel %s is not a text channel or thread.",
                channel_id,
            )
            return

        for identity, event, scheduled, status_source in to_announce:
            name = str(event.get("name") or "")
            internal_name = str(event.get("internalName") or "")
            try:
                message = await channel.send(
                    embed=_event_embed(event, scheduled)
                )
            except discord.HTTPException:
                logger.exception("Could not post world event %r.", name)
                continue
            self.announcements[identity] = EventAnnouncement(
                event_id=internal_name,
                event_name=name or internal_name,
                message_id=message.id,
                channel_id=channel_id,
                expected_start=scheduled,
                locations=identity[2],
            )
            logger.info(
                "World event transition event=%r id=%s state=upcoming->announced "
                "message_id=%s expected_start=%s status_source=%s",
                name or internal_name,
                internal_name,
                message.id,
                scheduled.isoformat(),
                status_source,
            )

    def _match_current_event(
        self,
        identity: tuple[str, str | None, tuple[tuple[float, float, float], ...]],
        announcement: EventAnnouncement,
        current: dict[
            tuple[str, str | None, tuple[tuple[float, float, float], ...]],
            dict[str, Any],
        ],
    ) -> tuple[dict[str, Any] | None, str]:
        exact = current.get(identity)
        if exact is not None:
            return exact, "event id, schedule, and locations"

        same_occurrence = [
            (key, event)
            for key, event in current.items()
            if key[0] == announcement.event_id.casefold()
            and key[1] == announcement.expected_start.isoformat()
        ]
        if len(same_occurrence) == 1:
            return same_occurrence[0][1], "unique event id and schedule"

        same_occurrence_without_schedule = [
            event
            for key, event in current.items()
            if key[0] == announcement.event_id.casefold()
            and key[1] is None
            and key[2] == announcement.locations
            and (actual_start := _actual_start_at(event)) is not None
            and abs(actual_start - announcement.expected_start) <= SCHEDULE_LOOKAHEAD
        ]
        if len(same_occurrence_without_schedule) == 1:
            return (
                same_occurrence_without_schedule[0],
                "event id, locations, and matching actual start",
            )
        return None, "no unambiguous match"

    async def _retry_confirmed_deletions(self, now: datetime) -> None:
        for announcement in self.announcements.values():
            if announcement.state != "delete_pending":
                continue
            if (
                announcement.next_delete_attempt is not None
                and now < announcement.next_delete_attempt
            ):
                continue
            channel = self.bot.get_channel(announcement.channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(announcement.channel_id)
                except discord.HTTPException as exc:
                    await self._record_delete_failure(announcement, now, exc)
                    continue
            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                error = TypeError(
                    f"Configured channel {announcement.channel_id} is not text-capable."
                )
                await self._record_delete_failure(announcement, now, error)
                continue
            try:
                message = await channel.fetch_message(announcement.message_id)
                await message.delete()
            except discord.NotFound:
                announcement.state = "deleted"
                logger.info(
                    "World event deletion complete event=%r message_id=%s "
                    "result=already_missing",
                    announcement.event_name,
                    announcement.message_id,
                )
            except (discord.Forbidden, discord.HTTPException) as exc:
                await self._record_delete_failure(announcement, now, exc)
                continue
            else:
                announcement.state = "deleted"
                logger.info(
                    "World event transition event=%r id=%s state=delete_pending->deleted "
                    "message_id=%s result=success",
                    announcement.event_name,
                    announcement.event_id,
                    announcement.message_id,
                )

    async def _record_delete_failure(
        self,
        announcement: EventAnnouncement,
        now: datetime,
        error: Exception,
    ) -> None:
        announcement.delete_attempts += 1
        delay_seconds = min(
            INITIAL_DELETE_RETRY.total_seconds()
            * (2 ** min(announcement.delete_attempts - 1, 16)),
            MAX_DELETE_RETRY.total_seconds(),
        )
        retry_after = getattr(error, "retry_after", None)
        if (
            isinstance(retry_after, (int, float))
            and isfinite(retry_after)
            and retry_after > 0
        ):
            delay_seconds = max(delay_seconds, retry_after)
        announcement.next_delete_attempt = now + timedelta(seconds=delay_seconds)
        logger.error(
            "World event deletion failed event=%r id=%s message_id=%s "
            "attempt=%s retry_in=%.1fs error=%s: %s",
            announcement.event_name,
            announcement.event_id,
            announcement.message_id,
            announcement.delete_attempts,
            delay_seconds,
            type(error).__name__,
            error,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        WorldEventAnnouncements(bot, bot.api, bot.settings)
    )
