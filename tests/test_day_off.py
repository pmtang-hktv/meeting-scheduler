"""Tests for the day-off / leave flow."""
from __future__ import annotations
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_create_day_off_uses_exclusive_end_and_notifies_owner():
    """A single-day off on 03 Jul must create an all-day event ending 04 Jul
    (Google's exclusive end), and ping the owner."""
    import bot.handlers.day_off as do

    query = AsyncMock()
    captured = {}

    async def fake_all_day(title, start_date, end_date, notes=""):
        captured["title"] = title
        captured["start"] = start_date
        captured["end"] = end_date
        return "UID-OFF"

    notify = AsyncMock()
    with patch.object(do.do_db, "create_day_off", AsyncMock(return_value=7)), \
         patch.object(do.do_db, "set_calendar_uid", AsyncMock()), \
         patch.object(do.cal_svc, "create_all_day_event", fake_all_day), \
         patch.object(do.owner_notify, "send_owner_message", notify), \
         patch.object(do.conv_db, "reset_conversation", AsyncMock()):
        ctx = {
            "organizer_name": "Peter Tang",
            "pending_dayoff_start": "2099-07-03",
            "pending_dayoff_end": "2099-07-03",
        }
        await do._create_day_off(query, 555, ctx)

    assert captured["title"] == "Day Off — Peter Tang"
    assert captured["start"] == "2099-07-03"
    assert captured["end"] == "2099-07-04"   # exclusive
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_multi_day_range_end_is_last_day_plus_one():
    import bot.handlers.day_off as do

    captured = {}

    async def fake_all_day(title, start_date, end_date, notes=""):
        captured["end"] = end_date
        return "UID"

    with patch.object(do.do_db, "create_day_off", AsyncMock(return_value=8)), \
         patch.object(do.do_db, "set_calendar_uid", AsyncMock()), \
         patch.object(do.cal_svc, "create_all_day_event", fake_all_day), \
         patch.object(do.owner_notify, "send_owner_message", AsyncMock()), \
         patch.object(do.conv_db, "reset_conversation", AsyncMock()):
        ctx = {"organizer_name": "X", "pending_dayoff_start": "2099-07-06", "pending_dayoff_end": "2099-07-08"}
        await do._create_day_off(AsyncMock(), 1, ctx)

    assert captured["end"] == "2099-07-09"   # last day 08 Jul + 1


@pytest.mark.asyncio
async def test_past_date_is_rejected_and_reprompts():
    import bot.handlers.day_off as do

    update = AsyncMock()
    with patch.object(do.conv_db, "upsert_conversation", AsyncMock()) as up:
        # 2000-01-01 is firmly in the past
        ret = await do._offer(update, 555, {}, [], "2000-01-01", None, "Peter")

    # Re-prompts for a date and persists the AWAITING_DAYOFF_DATE state; no booking made.
    up.assert_awaited()
    assert up.await_args.args[1] == "AWAITING_DAYOFF_DATE"


@pytest.mark.asyncio
async def test_delete_rejects_other_users_day_off():
    import bot.handlers.day_off as do

    d = {"id": 7, "requester_chat_id": 555, "status": "confirmed", "calendar_uid": "U",
         "start_date": "2099-07-03", "end_date": "2099-07-03", "person_name": "Peter"}
    delete = AsyncMock()
    cancel = AsyncMock()
    with patch.object(do.do_db, "get_day_off", AsyncMock(return_value=d)), \
         patch.object(do.do_db, "cancel_day_off", cancel), \
         patch.object(do.cal_svc, "delete_event", delete):
        await do._do_delete(AsyncMock(), 999, {}, 7)  # wrong chat_id

    delete.assert_not_awaited()
    cancel.assert_not_awaited()
