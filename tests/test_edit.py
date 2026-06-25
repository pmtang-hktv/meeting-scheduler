"""Tests for the edit-booking feature: reschedule self-exclusion + helpers."""
from __future__ import annotations
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

HKT = ZoneInfo("Asia/Hong_Kong")


def hkt(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=HKT)


class FakeEvent:
    def __init__(self, uid, start, end):
        self.uid = uid
        self.start = start
        self.end = end


@pytest.mark.asyncio
async def test_check_slot_excludes_own_event_so_overlapping_move_is_free():
    """Rescheduling onto a window overlapping the booking's own current time must
    not be reported as a conflict against itself."""
    from scheduling.availability import check_slot

    start = hkt(2099, 6, 30, 15, 0)  # far-future weekday to stay in business hours
    own = FakeEvent("OWN-UID", start, start + timedelta(minutes=30))

    mock_events = AsyncMock(return_value=[own])
    mock_db = AsyncMock(return_value=[])
    with patch("scheduling.availability.get_events", mock_events), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        # Move 15 min later (overlaps the old slot) while excluding our own event.
        result = await check_slot(
            start_dt=start + timedelta(minutes=15),
            duration_mins=30,
            exclude_uid="OWN-UID",
        )
    assert result["available"] is True


@pytest.mark.asyncio
async def test_check_slot_without_exclusion_sees_the_conflict():
    """Same overlap, but without exclusion, is a genuine conflict (sanity check)."""
    from scheduling.availability import check_slot

    start = hkt(2099, 6, 30, 15, 0)
    other = FakeEvent("SOMEONE-ELSE", start, start + timedelta(minutes=30))

    mock_events = AsyncMock(return_value=[other])
    mock_db = AsyncMock(return_value=[])
    with patch("scheduling.availability.get_events", mock_events), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        result = await check_slot(start_dt=start + timedelta(minutes=15), duration_mins=30)
    assert result["available"] is False
