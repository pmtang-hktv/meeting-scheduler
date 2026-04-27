from __future__ import annotations
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from calendar_integration.calendar_service import get_events
from db.meetings import get_confirmed_meetings_in_range

logger = logging.getLogger(__name__)
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
    "lunch_block",
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

    # Lunch block — requires owner approval
    if overlaps_lunch_block(start_dt, end_dt):
        return {
            "available": False,
            "requires_owner": True,
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

    # Fail-safe: if AppleScript failed we cannot verify calendar conflicts — block the slot.
    if cal_events is None:
        logger.warning("Calendar read failed for %s — treating slot as unavailable", local_date)
        return {
            "available": False,
            "requires_owner": False,
            "reasons": ["calendar_unavailable"],
            "conflict": True,
        }

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
    proposed_dt: datetime,
    duration_mins: int,
    max_results: int = 5,
) -> list[datetime]:
    """
    Find up to max_results free slots relative to proposed_dt.

    Priority order:
    1. Same day: earlier slots before proposed time
    2. Same day: later slots after proposed time
    3. Ensure opposite AM/PM coverage on same day is near the front
    4. Subsequent business days if more slots needed
    """
    now = datetime.now(tz=HKT)
    proposed_local = proposed_dt.astimezone(HKT)
    proposed_date = proposed_local.date()
    results: list[datetime] = []

    async def _day_intervals(d: date) -> list[tuple[datetime, datetime]] | None:
        """Return occupied intervals for the day, or None if the calendar is unreadable."""
        ds = datetime.combine(d, datetime.min.time(), tzinfo=HKT)
        de = ds + timedelta(days=1)
        cal = await get_events(ds, de)
        if cal is None:
            logger.warning("Calendar read failed for %s — skipping day in slot search", d)
            return None
        intervals = [(e.start, e.end) for e in cal]
        db_mtgs = await get_confirmed_meetings_in_range(
            ds.astimezone(timezone.utc).isoformat(),
            de.astimezone(timezone.utc).isoformat(),
        )
        for m in db_mtgs:
            ms = datetime.fromisoformat(m["start_dt"]).astimezone(HKT)
            me = datetime.fromisoformat(m["end_dt"]).astimezone(HKT)
            if (ms, me) not in intervals:
                intervals.append((ms, me))
        return intervals

    # --- Same day ---
    if is_business_day(proposed_date):
        intervals = await _day_intervals(proposed_date)
        if intervals is None:
            intervals = []  # calendar unreadable — skip same-day candidates
        candidates = find_candidate_slots(proposed_date, duration_mins, intervals)
        valid = [
            c for c in candidates
            if c != proposed_local
            and c > now + timedelta(minutes=15)
            and not overlaps_lunch_block(c, c + timedelta(minutes=duration_mins))
        ]

        before = sorted([c for c in valid if c < proposed_local], reverse=True)  # nearest first
        after  = sorted([c for c in valid if c > proposed_local])                 # nearest first

        # Interleave after/before so we get a mix of times around the proposed slot
        interleaved: list[datetime] = []
        ai, bi = 0, 0
        while ai < len(after) or bi < len(before):
            if ai < len(after):
                interleaved.append(after[ai]); ai += 1
            if bi < len(before):
                interleaved.append(before[bi]); bi += 1

        # Ensure at least one slot from the opposite half-day (AM vs PM) is near the top
        proposed_is_am = proposed_local.hour < 13
        opposite = [s for s in interleaved if (s.hour < 12) != proposed_is_am]
        if opposite and interleaved and opposite[0] != interleaved[0]:
            interleaved.remove(opposite[0])
            interleaved.insert(0, opposite[0])

        results.extend(interleaved)

    # --- Subsequent days ---
    current_date = proposed_date + timedelta(days=1)
    for _ in range(30):
        if len(results) >= max_results:
            break
        if not is_business_day(current_date):
            current_date += timedelta(days=1)
            continue
        intervals = await _day_intervals(current_date)
        if intervals is None:
            current_date += timedelta(days=1)
            continue  # calendar unreadable — skip this day
        candidates = find_candidate_slots(current_date, duration_mins, intervals)
        for c in candidates:
            if not overlaps_lunch_block(c, c + timedelta(minutes=duration_mins)):
                results.append(c)
                if len(results) >= max_results:
                    break
        current_date += timedelta(days=1)

    return results[:max_results]
