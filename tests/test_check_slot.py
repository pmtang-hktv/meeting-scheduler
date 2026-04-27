"""
Async tests for scheduling.availability.check_slot().

Both external dependencies are always patched:
  - scheduling.availability.get_events
  - scheduling.availability.get_confirmed_meetings_in_range

All tests use fixed HKT dates in the Apr-May 2026 window.

Key dates:
  Mon Apr 27 2026 → normal business day
  Sat May 2 2026  → weekend
  May 1 2026      → HK Labour Day holiday
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from calendar_integration.calendar_service import CalendarEvent

HKT = ZoneInfo("Asia/Hong_Kong")


def hkt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=HKT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(start: datetime, end: datetime) -> CalendarEvent:
    """Create a CalendarEvent dataclass instance for conflict testing."""
    return CalendarEvent(uid="test-uid", start=start, end=end)


def _no_events_mocks():
    """Return (patched get_events, patched get_confirmed_meetings_in_range) with empty results."""
    mock_get_events = AsyncMock(return_value=[])
    mock_get_db_meetings = AsyncMock(return_value=[])
    return mock_get_events, mock_get_db_meetings


# ---------------------------------------------------------------------------
# Test 1 — Normal slot, free, internal → available=True, requires_owner=False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_normal_free_internal_slot():
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        result = await check_slot(
            start_dt=hkt(2026, 4, 27, 10, 0),
            duration_mins=60,
            is_external=False,
        )

    assert result["available"] is True
    assert result["requires_owner"] is False
    assert result["reasons"] == []
    assert result["conflict"] is False


# ---------------------------------------------------------------------------
# Test 2 — Outside normal hours (7 pm) → requires_owner=True, "outside_hours"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_outside_normal_hours_7pm():
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        result = await check_slot(
            start_dt=hkt(2026, 4, 27, 19, 0),
            duration_mins=60,
        )

    assert result["requires_owner"] is True
    assert "outside_hours" in result["reasons"]


# ---------------------------------------------------------------------------
# Test 3 — Weekend day → requires_owner=True, "outside_hours"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_weekend_day():
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        result = await check_slot(
            start_dt=hkt(2026, 5, 2, 10, 0),  # Saturday
            duration_mins=60,
        )

    assert result["requires_owner"] is True
    assert "outside_hours" in result["reasons"]


# ---------------------------------------------------------------------------
# Test 4 — Lunch block (12:30–13:30) → available=False, requires_owner=True,
#           "lunch_block" in reasons
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lunch_block():
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        result = await check_slot(
            start_dt=hkt(2026, 4, 27, 12, 30),
            duration_mins=60,  # 12:30–13:30
        )

    assert result["available"] is False
    assert result["requires_owner"] is True
    assert "lunch_block" in result["reasons"]


# ---------------------------------------------------------------------------
# Test 5 — Long meeting ≥ 2 h → requires_owner=True, "long_meeting"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_long_meeting_requires_owner():
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        result = await check_slot(
            start_dt=hkt(2026, 4, 27, 9, 0),
            duration_mins=120,  # exactly 2 hours → threshold
        )

    assert result["requires_owner"] is True
    assert "long_meeting" in result["reasons"]


# ---------------------------------------------------------------------------
# Test 6 — External party → requires_owner=True, "external"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_external_party_requires_owner():
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        result = await check_slot(
            start_dt=hkt(2026, 4, 27, 10, 0),
            duration_mins=60,
            is_external=True,
        )

    assert result["requires_owner"] is True
    assert "external" in result["reasons"]


# ---------------------------------------------------------------------------
# Test 7 — Conflict, not VIP/urgent → available=False, requires_owner=False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conflict_not_vip_not_urgent():
    from scheduling.availability import check_slot
    conflicting_event = _make_event(
        start=hkt(2026, 4, 27, 10, 0),
        end=hkt(2026, 4, 27, 11, 0),
    )
    mock_ge = AsyncMock(return_value=[conflicting_event])
    mock_db = AsyncMock(return_value=[])
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        result = await check_slot(
            start_dt=hkt(2026, 4, 27, 10, 0),
            duration_mins=60,
            is_external=False,
            is_vip=False,
            is_urgent=False,
        )

    assert result["available"] is False
    assert result["requires_owner"] is False


# ---------------------------------------------------------------------------
# Test 8 — Conflict + VIP → available=False, requires_owner=True, "vip_conflict"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conflict_vip():
    from scheduling.availability import check_slot
    conflicting_event = _make_event(
        start=hkt(2026, 4, 27, 10, 0),
        end=hkt(2026, 4, 27, 11, 0),
    )
    mock_ge = AsyncMock(return_value=[conflicting_event])
    mock_db = AsyncMock(return_value=[])
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        result = await check_slot(
            start_dt=hkt(2026, 4, 27, 10, 0),
            duration_mins=60,
            is_vip=True,
        )

    assert result["available"] is False
    assert result["requires_owner"] is True
    assert "vip_conflict" in result["reasons"]


# ---------------------------------------------------------------------------
# Test 9 — Conflict + urgent → available=False, requires_owner=True, "urgent_conflict"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conflict_urgent():
    from scheduling.availability import check_slot
    conflicting_event = _make_event(
        start=hkt(2026, 4, 27, 10, 0),
        end=hkt(2026, 4, 27, 11, 0),
    )
    mock_ge = AsyncMock(return_value=[conflicting_event])
    mock_db = AsyncMock(return_value=[])
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        result = await check_slot(
            start_dt=hkt(2026, 4, 27, 10, 0),
            duration_mins=60,
            is_urgent=True,
        )

    assert result["available"] is False
    assert result["requires_owner"] is True
    assert "urgent_conflict" in result["reasons"]


# ---------------------------------------------------------------------------
# Test 10 — Multiple reasons combined: external + long meeting + outside hours
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_reasons_combined():
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        result = await check_slot(
            start_dt=hkt(2026, 4, 27, 19, 0),   # 7pm → outside_hours
            duration_mins=180,                    # 3h → long_meeting
            is_external=True,                     # → external
        )

    assert result["requires_owner"] is True
    assert "outside_hours" in result["reasons"]
    assert "long_meeting" in result["reasons"]
    assert "external" in result["reasons"]


# ---------------------------------------------------------------------------
# Test 11 — Overlap check: event starts before slot but overlaps
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conflict_event_starts_before_slot():
    """An event that begins before the slot but ends inside it must count as a conflict."""
    from scheduling.availability import check_slot
    # Event: 09:30 → 10:30; Slot: 10:00 → 11:00 — they overlap by 30 min
    overlapping_event = _make_event(
        start=hkt(2026, 4, 27, 9, 30),
        end=hkt(2026, 4, 27, 10, 30),
    )
    mock_ge = AsyncMock(return_value=[overlapping_event])
    mock_db = AsyncMock(return_value=[])
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        result = await check_slot(
            start_dt=hkt(2026, 4, 27, 10, 0),
            duration_mins=60,
        )

    assert result["conflict"] is True
    assert result["available"] is False


# ---------------------------------------------------------------------------
# Test 12 — Calendar read failure → available=False, "calendar_unavailable"
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_calendar_unavailable():
    from scheduling.availability import check_slot
    mock_ge = AsyncMock(return_value=None)   # None signals calendar read failure
    mock_db = AsyncMock(return_value=[])
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        result = await check_slot(
            start_dt=hkt(2026, 4, 27, 10, 0),
            duration_mins=60,
        )

    assert result["available"] is False
    assert "calendar_unavailable" in result["reasons"]
