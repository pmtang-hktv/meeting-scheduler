from __future__ import annotations
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


async def get_events(start_dt: datetime, end_dt: datetime) -> list[CalendarEvent] | None:
    """Return calendar events in the range, or None if the calendar could not be read."""
    script = get_events_script(start_dt, end_dt)
    raw = run_applescript(script)
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
    return events


async def create_event(
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    location: str = "",
    notes: str = "",
) -> str:
    script = create_event_script(_calendar_name, title, start_dt, end_dt, location, notes)
    uid = run_applescript(script)
    return uid


async def delete_event(uid: str) -> bool:
    script = delete_event_script(uid)
    result = run_applescript(script)
    return result == "deleted"


async def find_event(uid: str) -> CalendarEvent | None:
    script = find_event_script(uid)
    raw = run_applescript(script)
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
