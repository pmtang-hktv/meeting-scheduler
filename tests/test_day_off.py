"""Tests for the day-off / leave flow."""
from __future__ import annotations
from datetime import date
from unittest.mock import AsyncMock, call, patch

import pytest

from ai.intent import parse_explicit_dates


_TODAY = date(2026, 7, 2)


def _spans(text):
    return [(s["start"], s["end"]) for s in parse_explicit_dates(text, _TODAY)]


@pytest.mark.parametrize("text, expected", [
    # The exact messages from the reported chat that Claude mis-read.
    ("Jul 3, 6,10 13 in 2026",
     [("2026-07-03", None), ("2026-07-06", None), ("2026-07-10", None), ("2026-07-13", None)]),
    ("and Jul 3 and Jul 6 in 2026", [("2026-07-03", None), ("2026-07-06", None)]),
    ("Jul 3 and Jul 6 in 2026", [("2026-07-03", None), ("2026-07-06", None)]),
    # Ranges, day-first and month-first.
    ("6-8 Jul", [("2026-07-06", "2026-07-08")]),
    ("Jul 6-8", [("2026-07-06", "2026-07-08")]),
    ("6 to 8 Jul", [("2026-07-06", "2026-07-08")]),
    # Ordinals and multiple months.
    ("3rd Jul", [("2026-07-03", None)]),
    ("Jul 3 and Aug 6", [("2026-07-03", None), ("2026-08-06", None)]),
    # No explicit month → leave it to the LLM.
    ("next Friday", []),
    ("10/7", []),
    ("Jul 2026", []),
    # Invalid calendar date is dropped, not guessed.
    ("Feb 30 2026", []),
    # A bare month/year without a year rolls a past date into next year.
    ("Jan 5", [("2027-01-05", None)]),
])
def test_parse_explicit_dates(text, expected):
    assert _spans(text) == expected


def test_merge_recovers_dropped_dates():
    """The screenshot bug: Claude kept only 10 & 13; the parser adds back 3 & 6."""
    import bot.handlers.day_off as do
    llm = [{"start": "2026-07-10", "end": None, "half": None},
           {"start": "2026-07-13", "end": None, "half": None}]
    merged = do._merge_explicit("Jul 3, 6,10 13 in 2026", llm)
    assert [(s["start"], s["end"]) for s in merged] == [
        ("2026-07-03", None), ("2026-07-06", None), ("2026-07-10", None), ("2026-07-13", None)
    ]


def test_merge_preserves_llm_relative_date():
    """A relative date the parser can't see is kept alongside the explicit one."""
    import bot.handlers.day_off as do
    llm = [{"start": "2026-07-10", "end": None, "half": None}]  # LLM's "next Friday"
    merged = do._merge_explicit("next Friday and Jul 6", llm)
    starts = sorted(s["start"] for s in merged)
    assert starts == ["2026-07-06", "2026-07-10"]


def test_merge_keeps_half_day_from_llm():
    import bot.handlers.day_off as do
    llm = [{"start": "2026-07-03", "end": None, "half": "pm"}]
    merged = do._merge_explicit("off Jul 3 pm", llm)
    assert merged == [{"start": "2026-07-03", "end": None, "half": "pm"}]


def test_merge_falls_back_when_no_explicit_date():
    import bot.handlers.day_off as do
    llm = [{"start": "2026-07-10", "end": None, "half": None}]
    assert do._merge_explicit("next Friday", llm) is llm


def _patches(do, all_day_fn):
    return [
        patch.object(do.do_db, "create_day_off", AsyncMock(side_effect=[7, 8, 9])),
        patch.object(do.do_db, "set_calendar_uid", AsyncMock()),
        patch.object(do.do_db, "cancel_day_off", AsyncMock()),
        patch.object(do.cal_svc, "create_all_day_event", all_day_fn),
        patch.object(do.owner_notify, "send_owner_message", AsyncMock()),
        patch.object(do.conv_db, "reset_conversation", AsyncMock()),
    ]


@pytest.mark.asyncio
async def test_single_day_uses_exclusive_end():
    import bot.handlers.day_off as do
    calls = []

    async def fake_all_day(title, start_date, end_date, notes=""):
        calls.append((title, start_date, end_date))
        return "UID"

    import contextlib
    with contextlib.ExitStack() as st:
        for p in _patches(do, fake_all_day):
            st.enter_context(p)
        ctx = {"organizer_name": "Peter", "pending_dayoff_segments": [{"start": "2099-07-03", "end": "2099-07-03"}]}
        await do._create_day_off(AsyncMock(), 555, ctx)

    assert calls == [("Day Off — Peter", "2099-07-03", "2099-07-04")]


@pytest.mark.asyncio
async def test_multi_day_range_end_is_last_day_plus_one():
    import bot.handlers.day_off as do
    calls = []

    async def fake_all_day(title, start_date, end_date, notes=""):
        calls.append(end_date)
        return "UID"

    import contextlib
    with contextlib.ExitStack() as st:
        for p in _patches(do, fake_all_day):
            st.enter_context(p)
        ctx = {"organizer_name": "X", "pending_dayoff_segments": [{"start": "2099-07-06", "end": "2099-07-08"}]}
        await do._create_day_off(AsyncMock(), 1, ctx)

    assert calls == ["2099-07-09"]


@pytest.mark.asyncio
async def test_two_separate_days_create_two_events():
    """'tomorrow and next Wed' = two distinct single-day events, not one range."""
    import bot.handlers.day_off as do
    starts = []

    async def fake_all_day(title, start_date, end_date, notes=""):
        starts.append((start_date, end_date))
        return "UID"

    import contextlib
    notify = AsyncMock()
    with contextlib.ExitStack() as st:
        for p in _patches(do, fake_all_day):
            st.enter_context(p)
        st.enter_context(patch.object(do.owner_notify, "send_owner_message", notify))
        ctx = {
            "organizer_name": "Manson",
            "pending_dayoff_segments": [
                {"start": "2099-06-26", "end": "2099-06-26"},
                {"start": "2099-07-01", "end": "2099-07-01"},
            ],
        }
        await do._create_day_off(AsyncMock(), 1, ctx)

    assert starts == [("2099-06-26", "2099-06-27"), ("2099-07-01", "2099-07-02")]
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_normalize_drops_past_and_keeps_future():
    import bot.handlers.day_off as do
    segs = [{"start": "2000-01-01", "end": None}, {"start": "2099-07-03", "end": None}]
    norm = do._normalize(segs)
    assert norm == [{"start": "2099-07-03", "end": "2099-07-03", "half": None}]


@pytest.mark.asyncio
async def test_normalize_keeps_half_on_single_day_drops_on_range():
    import bot.handlers.day_off as do
    norm = do._normalize([
        {"start": "2099-07-03", "end": None, "half": "pm"},
        {"start": "2099-07-06", "end": "2099-07-08", "half": "am"},  # range → half dropped
    ])
    assert norm == [
        {"start": "2099-07-03", "end": "2099-07-03", "half": "pm"},
        {"start": "2099-07-06", "end": "2099-07-08", "half": None},
    ]


@pytest.mark.asyncio
async def test_half_day_button_override_sets_title_and_stores_half():
    """Tapping 'Afternoon only' overrides the entry and labels the calendar event."""
    import bot.handlers.day_off as do
    calls = []
    stored = []

    async def fake_all_day(title, start_date, end_date, notes=""):
        calls.append((title, start_date, end_date))
        return "UID"

    async def fake_create(chat_id, name, start, end, half_day=None):
        stored.append(half_day)
        return 7

    import contextlib
    with contextlib.ExitStack() as st:
        for p in _patches(do, fake_all_day):
            st.enter_context(p)
        st.enter_context(patch.object(do.do_db, "create_day_off", fake_create))
        ctx = {"organizer_name": "Peter", "pending_dayoff_segments": [{"start": "2099-07-03", "end": "2099-07-03", "half": None}]}
        await do._create_day_off(AsyncMock(), 555, ctx, half_override="pm")

    assert calls == [("Day Off (PM) — Peter", "2099-07-03", "2099-07-04")]
    assert stored == ["pm"]


@pytest.mark.asyncio
async def test_half_from_entry_used_when_no_override():
    """A half extracted from natural language is honoured without a button tap."""
    import bot.handlers.day_off as do
    calls = []

    async def fake_all_day(title, start_date, end_date, notes=""):
        calls.append(title)
        return "UID"

    import contextlib
    with contextlib.ExitStack() as st:
        for p in _patches(do, fake_all_day):
            st.enter_context(p)
        ctx = {"organizer_name": "Amy", "pending_dayoff_segments": [{"start": "2099-07-03", "end": "2099-07-03", "half": "am"}]}
        await do._create_day_off(AsyncMock(), 555, ctx)

    assert calls == ["Day Off (AM) — Amy"]


@pytest.mark.asyncio
async def test_all_past_dates_reprompt():
    import bot.handlers.day_off as do
    update = AsyncMock()
    with patch.object(do.conv_db, "upsert_conversation", AsyncMock()) as up:
        await do._offer(update, 555, {}, [], [{"start": "2000-01-01", "end": None}], "Peter")
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
