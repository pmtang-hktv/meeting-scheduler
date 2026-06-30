"""Tests for the deterministic duration parser and weekday-consistency guardrail
added to ai.intent (bug fixes: '1 hour' duration edit + 'Tue (tomorrow)' → wrong day)."""
from __future__ import annotations
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from ai.intent import parse_duration_mins, _align_to_named_weekday

HKT = ZoneInfo("Asia/Hong_Kong")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1 hour", 60),
        ("1 hr", 60),
        ("1hr", 60),
        ("1h", 60),
        ("an hour", 60),
        ("one hour", 60),
        ("2 hours", 120),
        ("1.5 hours", 90),
        ("half an hour", 30),
        ("half hour", 30),
        ("hour and a half", 90),
        ("an hour and a half", 90),
        ("45", 45),
        ("45 minutes", 45),
        ("45 mins", 45),
        ("30m", 30),
        ("90 min", 90),
        ("1 hour 30 mins", 90),
        ("  1 hour  ", 60),
        ("Change to 1 hour", 60),
    ],
)
def test_parse_duration_mins_understood(text, expected):
    assert parse_duration_mins(text) == expected


@pytest.mark.parametrize("text", ["", "soon", "a while", "lunchtime", None])
def test_parse_duration_mins_unparseable(text):
    assert parse_duration_mins(text) is None


def test_align_weekday_corrects_off_by_one():
    """'Tue (tomorrow)' must not resolve to Wednesday."""
    wed = datetime(2026, 7, 1, 17, 30, tzinfo=HKT)  # a Wednesday
    out = _align_to_named_weekday(wed, "Tue 5:30-6pm (tomorrow), mainland catch up")
    assert out.weekday() == 1  # Tuesday
    assert out == datetime(2026, 6, 30, 17, 30, tzinfo=HKT)  # nudged back one day
    assert out.hour == 17 and out.minute == 30  # time-of-day preserved


def test_align_weekday_leaves_matching_date_untouched():
    tue = datetime(2026, 6, 30, 15, 0, tzinfo=HKT)  # a Tuesday
    assert _align_to_named_weekday(tue, "Tuesday 3pm") == tue


def test_align_weekday_ignores_when_no_weekday_named():
    dt = datetime(2026, 7, 1, 10, 0, tzinfo=HKT)
    assert _align_to_named_weekday(dt, "tomorrow at 10am") == dt


def test_align_weekday_ignores_ambiguous_multiple_weekdays():
    dt = datetime(2026, 7, 1, 10, 0, tzinfo=HKT)  # Wednesday
    # User offered two options — don't guess which one.
    assert _align_to_named_weekday(dt, "Monday or Tuesday works") == dt


def test_align_weekday_preserves_deliberate_week_offset():
    """A correct 'next Tuesday' already on a Tuesday is left alone even if it's a week out."""
    tue_next_week = datetime(2026, 7, 7, 9, 0, tzinfo=HKT)  # Tuesday, +1 week
    assert _align_to_named_weekday(tue_next_week, "next Tuesday 9am") == tue_next_week
