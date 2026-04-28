"""
Async tests for scheduling.availability.find_next_available_slots().

Both external dependencies are always patched:
  - scheduling.availability.get_events
  - scheduling.availability.get_confirmed_meetings_in_range

Key dates used (all Mon-Thu Apr 27-30 2026 are normal business days):
  Mon Apr 27 2026 → proposed day
  Tue Apr 28 2026 → next business day
  Wed Apr 29 2026 → day after
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from calendar_integration.calendar_service import CalendarEvent

HKT = ZoneInfo("Asia/Hong_Kong")

BUSINESS_START = time(8, 30)
BUSINESS_END = time(18, 0)
LUNCH_START = time(12, 30)
LUNCH_END = time(14, 0)


def hkt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=HKT)


def _make_event(start: datetime, end: datetime) -> CalendarEvent:
    return CalendarEvent(uid="test-uid", start=start, end=end)


def _in_lunch(slot: datetime, duration_mins: int) -> bool:
    """Return True if a slot overlaps 12:30–14:00 HKT."""
    s = slot.astimezone(HKT)
    e = (slot + timedelta(minutes=duration_mins)).astimezone(HKT)
    lunch_s = s.replace(hour=12, minute=30, second=0, microsecond=0)
    lunch_e = s.replace(hour=14, minute=0, second=0, microsecond=0)
    return s < lunch_e and e > lunch_s


# ---------------------------------------------------------------------------
# Test 1 — All day free → returns slots near proposed time
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_free_day_returns_slots():
    from scheduling.availability import find_next_available_slots
    mock_ge = AsyncMock(return_value=[])
    mock_db = AsyncMock(return_value=[])
    proposed = hkt(2026, 4, 27, 10, 0)
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        slots = await find_next_available_slots(proposed, duration_mins=30, max_results=5)

    assert len(slots) > 0
    # None of the returned slots should equal the proposed time
    assert proposed not in slots


# ---------------------------------------------------------------------------
# Test 2 — Proposed time blocked, alternatives exist same day
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_proposed_blocked_alternatives_same_day():
    from datetime import date
    from scheduling.availability import find_next_available_slots
    from scheduling.rules import is_business_day

    # Use a future business day so the "c > now + 15min" filter never excludes same-day slots.
    future = datetime.now(HKT) + timedelta(days=2)
    while not is_business_day(future.date()):
        future += timedelta(days=1)
    proposal_day = future.date()

    proposed = datetime(proposal_day.year, proposal_day.month, proposal_day.day, 10, 0, tzinfo=HKT)
    blocking_event = _make_event(
        start=proposed,
        end=proposed + timedelta(hours=1),
    )
    mock_ge = AsyncMock(return_value=[blocking_event])
    mock_db = AsyncMock(return_value=[])

    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        slots = await find_next_available_slots(proposed, duration_mins=30, max_results=3)

    assert len(slots) > 0
    # Proposed itself must not be returned
    assert proposed not in slots
    # At least one slot should be on the same day
    same_day = [s for s in slots if s.astimezone(HKT).date() == proposal_day]
    assert len(same_day) > 0


# ---------------------------------------------------------------------------
# Test 3 — Calendar unreadable (get_events returns None) → skips that day
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendar_unreadable_skips_to_next_day():
    from scheduling.availability import find_next_available_slots

    call_count = 0

    async def selective_get_events(start, end):
        nonlocal call_count
        call_count += 1
        # Fail for the proposed day (Apr 27), succeed empty for subsequent days
        if start.date().day == 27:
            return None
        return []

    mock_db = AsyncMock(return_value=[])
    proposed = hkt(2026, 4, 27, 10, 0)

    with patch("scheduling.availability.get_events", selective_get_events), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        slots = await find_next_available_slots(proposed, duration_mins=30, max_results=3)

    # Should still find slots on subsequent days
    assert len(slots) > 0
    # All returned slots must be on days after Apr 27
    for s in slots:
        assert s.astimezone(HKT).date() > proposed.astimezone(HKT).date()


# ---------------------------------------------------------------------------
# Test 4 — Two consecutive calendar failures → bails out early
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_consecutive_calendar_failures_bail_early():
    from scheduling.availability import find_next_available_slots

    fail_count = 0

    async def always_fail(start, end):
        nonlocal fail_count
        # Proposed day (Apr 27) isn't a subsequent-day loop iteration,
        # but to keep this simple always return None so both the same-day
        # check and the subsequent-day loop fail immediately.
        fail_count += 1
        return None

    mock_db = AsyncMock(return_value=[])
    proposed = hkt(2026, 4, 27, 10, 0)

    with patch("scheduling.availability.get_events", always_fail), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        slots = await find_next_available_slots(proposed, duration_mins=30, max_results=5)

    # With MAX_CONSECUTIVE_FAILURES=2 the loop must bail; at most a small
    # number of calendar calls should have been made (≤ 1 same-day + 2 loop days).
    assert slots == []
    # Verify we stopped early: same-day + at most MAX_CONSECUTIVE_FAILURES=2 subsequent days
    assert fail_count <= 3


# ---------------------------------------------------------------------------
# Test 5 — Lunch slots excluded from alternatives
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lunch_slots_excluded():
    from scheduling.availability import find_next_available_slots

    mock_ge = AsyncMock(return_value=[])
    mock_db = AsyncMock(return_value=[])
    # Propose 11:00 so alternatives both before and after are searched,
    # which means the 12:30–14:00 region would naturally appear as a candidate
    proposed = hkt(2026, 4, 27, 11, 0)

    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        slots = await find_next_available_slots(proposed, duration_mins=60, max_results=10)

    for s in slots:
        assert not _in_lunch(s, 60), (
            f"Slot {s.astimezone(HKT).strftime('%H:%M')} overlaps the lunch block"
        )


# ---------------------------------------------------------------------------
# Test 6 — Returned slots respect business hours (all between 08:30–18:00)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returned_slots_within_business_hours():
    from scheduling.availability import find_next_available_slots

    mock_ge = AsyncMock(return_value=[])
    mock_db = AsyncMock(return_value=[])
    proposed = hkt(2026, 4, 27, 9, 0)

    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        slots = await find_next_available_slots(proposed, duration_mins=30, max_results=10)

    assert len(slots) > 0
    for s in slots:
        local = s.astimezone(HKT)
        slot_end = (s + timedelta(minutes=30)).astimezone(HKT)
        assert local.time() >= BUSINESS_START, (
            f"Slot {local.strftime('%H:%M')} starts before business hours"
        )
        assert slot_end.time() <= BUSINESS_END, (
            f"Slot ending at {slot_end.strftime('%H:%M')} exceeds business hours"
        )
