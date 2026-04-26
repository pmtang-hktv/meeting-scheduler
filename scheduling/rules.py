from __future__ import annotations
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from config.hk_holidays import HK_HOLIDAYS

HKT = ZoneInfo("Asia/Hong_Kong")

NORMAL_START = time(9, 0)
NORMAL_END = time(18, 0)
LUNCH_START = time(12, 30)
LUNCH_END = time(14, 0)
SCHEDULABLE_START = time(8, 30)

MAX_DAILY_MEETING_MINS = 360  # 6 hours


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HK_HOLIDAYS


def is_within_normal_hours(start: datetime, end: datetime) -> bool:
    s = start.astimezone(HKT)
    e = end.astimezone(HKT)
    return s.time() >= NORMAL_START and e.time() <= NORMAL_END


def overlaps_lunch_block(start: datetime, end: datetime) -> bool:
    s = start.astimezone(HKT)
    e = end.astimezone(HKT)
    lunch_s = s.replace(hour=LUNCH_START.hour, minute=LUNCH_START.minute, second=0, microsecond=0)
    lunch_e = s.replace(hour=LUNCH_END.hour, minute=LUNCH_END.minute, second=0, microsecond=0)
    return s < lunch_e and e > lunch_s


def compute_schedulable_windows(d: date) -> list[tuple[datetime, datetime]]:
    """Returns free schedulable windows for a day (before lunch + after lunch)."""
    morning_start = datetime.combine(d, SCHEDULABLE_START, tzinfo=HKT)
    morning_end = datetime.combine(d, LUNCH_START, tzinfo=HKT)
    afternoon_start = datetime.combine(d, LUNCH_END, tzinfo=HKT)
    afternoon_end = datetime.combine(d, NORMAL_END, tzinfo=HKT)
    return [(morning_start, morning_end), (afternoon_start, afternoon_end)]


def daily_booked_minutes(events: list[dict]) -> int:
    """Sum of duration_mins for confirmed meetings on a given day."""
    return sum(e.get("duration_mins", 0) for e in events)


def slot_fits_in_window(start: datetime, end: datetime, window: tuple[datetime, datetime]) -> bool:
    ws, we = window
    return start >= ws and end <= we


def find_candidate_slots(
    d: date,
    duration_mins: int,
    existing_events: list[tuple[datetime, datetime]],
    slot_step_mins: int = 30,
) -> list[datetime]:
    """Return possible start times on date d that fit duration without overlapping existing events."""
    windows = compute_schedulable_windows(d)
    candidates: list[datetime] = []
    for ws, we in windows:
        current = ws
        slot_duration = timedelta(minutes=duration_mins)
        while current + slot_duration <= we:
            slot_end = current + slot_duration
            if not _overlaps_any(current, slot_end, existing_events):
                candidates.append(current)
            current += timedelta(minutes=slot_step_mins)
    return candidates


def _overlaps_any(
    start: datetime, end: datetime, events: list[tuple[datetime, datetime]]
) -> bool:
    for es, ee in events:
        if start < ee and end > es:
            return True
    return False
