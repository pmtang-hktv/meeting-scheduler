from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import google_cal_client

logger = logging.getLogger(__name__)
HKT = ZoneInfo("Asia/Hong_Kong")

_calendar_name: str = "HKTV"
_write_calendar_id: str | None = None
_all_calendar_ids: list[str] | None = None

# Cache calendar reads for 60s — avoids hitting the API multiple times
# during a single booking flow (check_slot, find_next_available_slots, etc.)
_CACHE_TTL = 60.0
_events_cache: dict[tuple[str, str], tuple[float, list["CalendarEvent"]]] = {}
_cache_lock = asyncio.Lock()


def configure(calendar_name: str) -> None:
    global _calendar_name, _write_calendar_id, _all_calendar_ids
    _calendar_name = calendar_name
    _write_calendar_id = None
    _all_calendar_ids = None


def _invalidate_events_cache() -> None:
    _events_cache.clear()


async def _get_write_calendar_id() -> str:
    global _write_calendar_id
    if _write_calendar_id:
        return _write_calendar_id
    cals = await google_cal_client.api_list_calendars()
    for cal in cals:
        if cal.get("summary") == _calendar_name:
            _write_calendar_id = cal["id"]
            logger.info("Write calendar '%s' → %s", _calendar_name, _write_calendar_id)
            return _write_calendar_id
    logger.warning("Calendar '%s' not found — defaulting to 'primary'", _calendar_name)
    _write_calendar_id = "primary"
    return _write_calendar_id


async def _get_all_calendar_ids() -> list[str]:
    global _all_calendar_ids
    if _all_calendar_ids is not None:
        return _all_calendar_ids
    cals = await google_cal_client.api_list_calendars()
    if cals:
        for cal in cals:
            logger.info("Calendar available: %s (id=%s, role=%s)",
                        cal.get("summary"), cal.get("id"), cal.get("accessRole"))
        # Use calendars the account owns OR has writer access to.
        # Service accounts see shared calendars as "writer" (not "owner"), so
        # we accept both roles to support both OAuth and service account auth.
        accessible_cals = [c for c in cals if c.get("accessRole") in ("owner", "writer")]
        if accessible_cals:
            _all_calendar_ids = [c["id"] for c in accessible_cals]
        else:
            _all_calendar_ids = [await _get_write_calendar_id()]
    else:
        _all_calendar_ids = [await _get_write_calendar_id()]
    logger.info("Monitoring %d owned calendar(s) for conflicts: %s",
                len(_all_calendar_ids), _all_calendar_ids)
    return _all_calendar_ids


@dataclass
class CalendarEvent:
    uid: str
    start: datetime
    end: datetime


def _parse_dt(item_dt: dict) -> datetime | None:
    """Parse a Google Calendar event start/end dict to a HKT datetime."""
    raw = item_dt.get("dateTime") or item_dt.get("date")
    if not raw:
        return None
    if "T" not in raw:
        raw += "T00:00:00+08:00"
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(HKT)
    except ValueError:
        return None


async def get_events(start_dt: datetime, end_dt: datetime) -> list[CalendarEvent] | None:
    """Return events across all writable calendars. Returns None only if every calendar failed."""
    key = (start_dt.isoformat(), end_dt.isoformat())
    now = time.monotonic()

    cached = _events_cache.get(key)
    if cached and now - cached[0] < _CACHE_TTL:
        return list(cached[1])

    async with _cache_lock:
        cached = _events_cache.get(key)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL:
            return list(cached[1])

        time_min = start_dt.astimezone(timezone.utc).isoformat()
        time_max = end_dt.astimezone(timezone.utc).isoformat()
        cal_ids = await _get_all_calendar_ids()

        seen_uids: set[str] = set()
        events: list[CalendarEvent] = []
        any_success = False

        for cal_id in cal_ids:
            items = await google_cal_client.api_get_events(cal_id, time_min, time_max)
            if items is None:
                continue
            any_success = True
            if items:
                logger.info(
                    "Calendar %s: %d event(s): %s", cal_id, len(items),
                    [(i.get("summary", "(no title)"),
                      i.get("start", {}).get("dateTime") or i.get("start", {}).get("date"))
                     for i in items],
                )
            for item in items:
                uid = item.get("id", "")
                if not uid or uid in seen_uids:
                    continue
                seen_uids.add(uid)
                # Skip all-day events (date only, no dateTime). These are typically
                # informational entries — other people's annual leave, multi-day trips,
                # public holidays — not blocks on the executive's own time.
                if "dateTime" not in item.get("start", {}):
                    continue
                s = _parse_dt(item.get("start", {}))
                e = _parse_dt(item.get("end", {}))
                if s and e:
                    events.append(CalendarEvent(uid=uid, start=s, end=e))

        if not any_success:
            return None

        _events_cache[key] = (time.monotonic(), list(events))
        logger.debug("Cached %d events for %s..%s", len(events), start_dt.date(), end_dt.date())
        return events


async def create_event(
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    location: str = "",
    notes: str = "",
) -> str:
    cal_id = await _get_write_calendar_id()
    body = {
        "summary": title,
        "location": location,
        "description": notes,
        "start": {"dateTime": start_dt.astimezone(timezone.utc).isoformat(), "timeZone": "Asia/Hong_Kong"},
        "end": {"dateTime": end_dt.astimezone(timezone.utc).isoformat(), "timeZone": "Asia/Hong_Kong"},
    }
    uid = await google_cal_client.api_create_event(cal_id, body)
    if uid:
        _invalidate_events_cache()
    return uid


async def delete_event(uid: str) -> bool:
    cal_id = await _get_write_calendar_id()
    ok = await google_cal_client.api_delete_event(cal_id, uid)
    if ok:
        _invalidate_events_cache()
    return ok


async def find_event(uid: str) -> CalendarEvent | None:
    cal_id = await _get_write_calendar_id()
    item = await google_cal_client.api_get_event(cal_id, uid)
    if not item:
        return None
    s = _parse_dt(item.get("start", {}))
    e = _parse_dt(item.get("end", {}))
    if not s or not e:
        return None
    return CalendarEvent(uid=item["id"], start=s, end=e)
