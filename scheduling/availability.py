from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from calendar_integration.calendar_service import get_events
from db.meetings import get_confirmed_meetings_in_range
from scheduling.rules import (
    HKT,
    is_business_day,
    is_within_normal_hours,
    overlaps_lunch_block,
    daily_booked_minutes,
    find_candidate_slots,
    MAX_DAILY_MEETING_MINS,
    _overlaps_any,
)

OWNER_REQUIRES_APPROVAL_REASONS = {
    "outside_hours",
    "long_meeting",
    "external",
    "vip_conflict",
    "urgent_conflict",
}


async def check_slot(
    start_dt: datetime,
    duration_mins: int,
    is_external: bool = False,
    is_vip: bool = False,
    is_urgent: bool = False,
) -> dict:
    """
    Returns:
      {
        "available": bool,
        "requires_owner": bool,
        "reasons": list[str],   # from OWNER_REQUIRES_APPROVAL_REASONS
        "conflict": bool,       # slot is physically occupied
      }
    """
    end_dt = start_dt + timedelta(minutes=duration_mins)
    reasons: list[str] = []

    # Check business day
    local_date = start_dt.astimezone(HKT).date()
    if not is_business_day(local_date):
        reasons.append("outside_hours")

    # Normal hours check
    if not is_within_normal_hours(start_dt, end_dt):
        if "outside_hours" not in reasons:
            reasons.append("outside_hours")

    # Lunch block — hard stop
    if overlaps_lunch_block(start_dt, end_dt):
        return {
            "available": False,
            "requires_owner": False,
            "reasons": ["lunch_block"],
            "conflict": True,
        }

    # Long meeting
    if duration_mins >= 120:
        reasons.append("long_meeting")

    # External party
    if is_external:
        reasons.append("external")

    # Get existing events: Apple Calendar + bot DB (DB is authoritative for bot meetings)
    day_start = datetime.combine(local_date, datetime.min.time(), tzinfo=HKT)
    day_end = day_start + timedelta(days=1)
    cal_events = await get_events(day_start, day_end)
    event_intervals: list[tuple[datetime, datetime]] = [(e.start, e.end) for e in cal_events]

    # Always check DB-confirmed meetings (reliable even when AppleScript fails)
    db_meetings = await get_confirmed_meetings_in_range(
        start_dt.astimezone(timezone.utc).isoformat(),
        end_dt.astimezone(timezone.utc).isoformat(),
    )
    for m in db_meetings:
        ms = datetime.fromisoformat(m["start_dt"]).astimezone(HKT)
        me = datetime.fromisoformat(m["end_dt"]).astimezone(HKT)
        if (ms, me) not in event_intervals:
            event_intervals.append((ms, me))

    conflict = _overlaps_any(start_dt, end_dt, event_intervals)

    if conflict:
        if is_vip:
            reasons.append("vip_conflict")
        elif is_urgent:
            reasons.append("urgent_conflict")

    # Daily cap check (skip for VIP/urgent overrides)
    booked = daily_booked_minutes([{"duration_mins": int((e[1] - e[0]).total_seconds()) // 60} for e in event_intervals])
    if booked + duration_mins > MAX_DAILY_MEETING_MINS and not (is_vip or is_urgent):
        conflict = True

    requires_owner = bool(reasons)
    available = not conflict

    return {
        "available": available,
        "requires_owner": requires_owner,
        "reasons": reasons,
        "conflict": conflict,
    }


async def find_next_available_slots(
    after: datetime,
    duration_mins: int,
    max_results: int = 3,
) -> list[datetime]:
    """Find the next N free slots of given duration starting after `after`."""
    results: list[datetime] = []
    current_date = after.astimezone(HKT).date()
    max_days = 30

    for _ in range(max_days):
        if not is_business_day(current_date):
            current_date += timedelta(days=1)
            continue

        day_start = datetime.combine(current_date, datetime.min.time(), tzinfo=HKT)
        day_end = day_start + timedelta(days=1)
        cal_events = await get_events(day_start, day_end)
        event_intervals = [(e.start, e.end) for e in cal_events]
        db_meetings = await get_confirmed_meetings_in_range(
            day_start.astimezone(timezone.utc).isoformat(),
            day_end.astimezone(timezone.utc).isoformat(),
        )
        for m in db_meetings:
            ms = datetime.fromisoformat(m["start_dt"]).astimezone(HKT)
            me = datetime.fromisoformat(m["end_dt"]).astimezone(HKT)
            if (ms, me) not in event_intervals:
                event_intervals.append((ms, me))

        candidates = find_candidate_slots(current_date, duration_mins, event_intervals)
        for c in candidates:
            if c > after and not overlaps_lunch_block(c, c + timedelta(minutes=duration_mins)):
                results.append(c)
                if len(results) >= max_results:
                    return results

        current_date += timedelta(days=1)

    return results
