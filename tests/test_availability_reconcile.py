"""A confirmed meeting missing from its day must be reconciled, not blindly cancelled."""
from __future__ import annotations
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

HKT = ZoneInfo("Asia/Hong_Kong")


class FakeEvent:
    def __init__(self, start, end):
        self.start = start
        self.end = end


@pytest.mark.asyncio
async def test_moved_event_syncs_db_and_is_not_cancelled():
    import scheduling.availability as av

    # DB has the meeting on 25 Jun 17:30; the calendar event now lives 26 Jun 10:00.
    m = {
        "id": 88, "calendar_uid": "db498",
        "start_dt": "2026-06-25T09:30:00+00:00",
        "end_dt": "2026-06-25T10:00:00+00:00",
    }
    moved = FakeEvent(
        datetime(2026, 6, 26, 10, 0, tzinfo=HKT),
        datetime(2026, 6, 26, 10, 30, tzinfo=HKT),
    )
    upd = AsyncMock()
    with patch.object(av, "find_event", AsyncMock(return_value=moved)), \
         patch.object(av, "update_meeting", upd):
        result = await av._resolve_missing_event(m)

    assert result == "moved"
    # DB synced to the calendar's new time — NOT cancelled.
    _, kwargs = upd.await_args
    assert kwargs["start_dt"] == "2026-06-26T02:00:00+00:00"   # 10:00 HKT in UTC
    assert kwargs["end_dt"] == "2026-06-26T02:30:00+00:00"
    assert "status" not in kwargs


@pytest.mark.asyncio
async def test_truly_deleted_event_is_cancelled():
    import scheduling.availability as av

    m = {"id": 88, "calendar_uid": "db498", "start_dt": "x", "end_dt": "y"}
    upd = AsyncMock()
    with patch.object(av, "find_event", AsyncMock(return_value=None)), \
         patch.object(av, "update_meeting", upd):
        result = await av._resolve_missing_event(m)

    assert result == "deleted"
    upd.assert_awaited_once_with(88, status="cancelled")
