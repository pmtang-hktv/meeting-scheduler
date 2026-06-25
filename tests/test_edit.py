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


@pytest.mark.asyncio
async def test_datetime_edit_adopts_duration_from_a_time_range():
    """Rescheduling a 60-min booking to a '12:00-12:30' range must re-check 30 min,
    not the old 60 min — otherwise a valid short slot is wrongly rejected."""
    import bot.handlers.edit as edit

    meeting = {
        "id": 91, "requester_chat_id": 555, "status": "confirmed",
        "calendar_uid": "UID91", "is_external": 0, "travel_mins": 0,
        "organizer_name": "Pat", "purpose": "Testing",
        "start_dt": hkt(2099, 6, 26, 9, 0).astimezone(ZoneInfo("UTC")).isoformat(),
        "end_dt": hkt(2099, 6, 26, 10, 0).astimezone(ZoneInfo("UTC")).isoformat(),
        "duration_mins": 60,
    }

    class Turn:  # mimics ConversationTurn for the fields we read
        proposed_dt = hkt(2099, 6, 26, 12, 0)
        duration_mins = 30

    update = AsyncMock()
    captured = {}

    async def fake_update_meeting(mid, **fields):
        captured.update(fields)

    with patch.object(edit, "process_turn", AsyncMock(return_value=Turn())), \
         patch.object(edit, "check_slot", AsyncMock(return_value={"available": True, "reasons": [], "requires_owner": False})), \
         patch.object(edit.meet_db, "get_meeting", AsyncMock(return_value=meeting)), \
         patch.object(edit.meet_db, "update_meeting", fake_update_meeting), \
         patch.object(edit.cal_svc, "update_event", AsyncMock(return_value=True)), \
         patch.object(edit.conv_db, "upsert_conversation", AsyncMock()):
        ctx = {"edit_meeting_id": 91, "edit_field": "datetime", "organizer_name": "Pat"}
        await edit.apply_field_edit(update, None, 555, ctx, [], "tomorrow 12:00-12:30pm")

    assert captured.get("duration_mins") == 30


@pytest.mark.asyncio
async def test_cancel_deletes_event_and_marks_cancelled():
    import bot.handlers.edit as edit

    meeting = {
        "id": 91, "requester_chat_id": 555, "status": "confirmed",
        "calendar_uid": "UID91",
        "start_dt": hkt(2099, 6, 26, 9, 0).astimezone(ZoneInfo("UTC")).isoformat(),
        "organizer_name": "Pat",
    }
    query = AsyncMock()
    captured = {}

    async def fake_update_meeting(mid, **fields):
        captured["mid"] = mid
        captured.update(fields)

    delete = AsyncMock(return_value=True)
    with patch.object(edit.meet_db, "get_meeting", AsyncMock(return_value=meeting)), \
         patch.object(edit.meet_db, "update_meeting", fake_update_meeting), \
         patch.object(edit.cal_svc, "delete_event", delete), \
         patch.object(edit.conv_db, "reset_conversation", AsyncMock()):
        await edit._do_cancel(query, 555, {"organizer_name": "Pat"}, 91)

    delete.assert_awaited_once_with("UID91")
    assert captured == {"mid": 91, "status": "cancelled"}


@pytest.mark.asyncio
async def test_cancel_rejects_other_users_booking():
    """Ownership guard: a different chat_id must not be able to cancel the booking."""
    import bot.handlers.edit as edit

    meeting = {
        "id": 91, "requester_chat_id": 555, "status": "confirmed", "calendar_uid": "UID91",
        "start_dt": hkt(2099, 6, 26, 9, 0).astimezone(ZoneInfo("UTC")).isoformat(),
        "organizer_name": "Pat",
    }
    delete = AsyncMock()
    update = AsyncMock()
    with patch.object(edit.meet_db, "get_meeting", AsyncMock(return_value=meeting)), \
         patch.object(edit.meet_db, "update_meeting", update), \
         patch.object(edit.cal_svc, "delete_event", delete), \
         patch.object(edit.conv_db, "reset_conversation", AsyncMock()):
        await edit._do_cancel(AsyncMock(), 999, {}, 91)  # wrong chat_id

    delete.assert_not_awaited()
    update.assert_not_awaited()
