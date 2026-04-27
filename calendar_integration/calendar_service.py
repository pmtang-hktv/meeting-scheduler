from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from .applescript import (
    run_applescript,
    get_events_script,
    create_event_script,
    delete_event_script,
    find_event_script,
)

logger = logging.getLogger(__name__)
HKT = ZoneInfo("Asia/Hong_Kong")
_calendar_name: str = "HKTV"


def configure(calendar_name: str) -> None:
    global _calendar_name
    _calendar_name = calendar_name


@dataclass
class CalendarEvent:
    uid: str
    start: datetime
    end: datetime


# In-memory cache for get_events. The HKTV calendar is slow (~36s per query),
# and a single booking flow may query the same day repeatedly via check_slot
# and find_next_available_slots. Caching for 60s avoids paying that cost over
# and over within one user interaction. Cache is invalidated on create/delete.
_CACHE_TTL = 60.0
_events_cache: dict[tuple[str, str], tuple[float, list["CalendarEvent"]]] = {}
_cache_lock = asyncio.Lock()


def _invalidate_events_cache() -> None:
    _events_cache.clear()


async def get_events(start_dt: datetime, end_dt: datetime) -> list[CalendarEvent] | None:
    """Return calendar events in the range, or None if the calendar could not be read."""
    key = (start_dt.isoformat(), end_dt.isoformat())
    now = time.monotonic()

    cached = _events_cache.get(key)
    if cached and now - cached[0] < _CACHE_TTL:
        return list(cached[1])

    # Lock per-call to prevent thundering herd (concurrent requesters won't all
    # fire 36s queries — they'll wait for the in-flight one to populate the cache).
    async with _cache_lock:
        cached = _events_cache.get(key)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL:
            return list(cached[1])

        script = get_events_script(start_dt, end_dt)
        raw = await run_applescript(script)
        if raw is None:
            return None  # AppleScript failed — caller must treat calendar as unreadable
        events: list[CalendarEvent] = []
        for line in raw.splitlines():
            if not line.startswith("|||"):
                continue
            parts = line.split("|")
            if len(parts) < 6:
                continue
            uid = parts[3]
            try:
                start = datetime.fromisoformat(parts[4]).astimezone(HKT)
                end = datetime.fromisoformat(parts[5]).astimezone(HKT)
            except ValueError:
                continue
            events.append(CalendarEvent(uid=uid, start=start, end=end))

        _events_cache[key] = (time.monotonic(), list(events))
        logger.debug("Cached %d events for %s..%s", len(events), key[0], key[1])
        return events


async def create_event(
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    location: str = "",
    notes: str = "",
) -> str:
    script = create_event_script(_calendar_name, title, start_dt, end_dt, location, notes)
    uid = await run_applescript(script)
    _invalidate_events_cache()  # new event must be visible on next read
    return uid or ""


async def delete_event(uid: str) -> bool:
    script = delete_event_script(uid)
    result = await run_applescript(script)
    _invalidate_events_cache()
    return result == "deleted"


async def find_event(uid: str) -> CalendarEvent | None:
    script = find_event_script(uid)
    raw = await run_applescript(script)
    if not raw:
        return None
    parts = raw.split("|")
    if len(parts) < 3:
        return None
    try:
        start = datetime.fromisoformat(parts[1]).astimezone(HKT)
        end = datetime.fromisoformat(parts[2]).astimezone(HKT)
        return CalendarEvent(uid=parts[0], start=start, end=end)
    except ValueError:
        return None
