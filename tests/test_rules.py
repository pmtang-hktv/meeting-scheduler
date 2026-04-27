"""
Unit tests for scheduling/rules.py — pure business rule functions.
No mocking needed; all functions are side-effect-free.

Key dates used throughout:
  Mon-Thu Apr 27-30, 2026  → normal business days
  Fri May 1, 2026          → HK Labour Day holiday (NOT a business day)
  Sat May 2, 2026          → weekend (NOT a business day)
  Sun May 3, 2026          → weekend (NOT a business day)
  Mon May 4, 2026          → normal business day
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scheduling.rules import (
    _overlaps_any,
    compute_schedulable_windows,
    daily_booked_minutes,
    find_candidate_slots,
    is_business_day,
    is_within_normal_hours,
    overlaps_lunch_block,
    slot_fits_in_window,
)

HKT = ZoneInfo("Asia/Hong_Kong")


def hkt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=HKT)


# ---------------------------------------------------------------------------
# is_business_day
# ---------------------------------------------------------------------------

class TestIsBusinessDay:
    def test_monday_is_business_day(self):
        assert is_business_day(date(2026, 4, 27)) is True

    def test_tuesday_is_business_day(self):
        assert is_business_day(date(2026, 4, 28)) is True

    def test_wednesday_is_business_day(self):
        assert is_business_day(date(2026, 4, 29)) is True

    def test_thursday_is_business_day(self):
        assert is_business_day(date(2026, 4, 30)) is True

    def test_labour_day_holiday_not_business(self):
        # May 1, 2026 is Labour Day — a Friday but a HK public holiday
        assert is_business_day(date(2026, 5, 1)) is False

    def test_saturday_not_business(self):
        assert is_business_day(date(2026, 5, 2)) is False

    def test_sunday_not_business(self):
        assert is_business_day(date(2026, 5, 3)) is False

    def test_monday_after_holiday_is_business(self):
        assert is_business_day(date(2026, 5, 4)) is True

    def test_new_years_day_2026_not_business(self):
        # Jan 1, 2026 is a Thursday but a public holiday
        assert is_business_day(date(2026, 1, 1)) is False

    def test_christmas_2026_not_business(self):
        assert is_business_day(date(2026, 12, 25)) is False


# ---------------------------------------------------------------------------
# is_within_normal_hours  (09:00–18:00 HKT)
# ---------------------------------------------------------------------------

class TestIsWithinNormalHours:
    def test_standard_morning_slot(self):
        assert is_within_normal_hours(hkt(2026, 4, 27, 9, 0), hkt(2026, 4, 27, 10, 0)) is True

    def test_exactly_on_normal_start(self):
        assert is_within_normal_hours(hkt(2026, 4, 27, 9, 0), hkt(2026, 4, 27, 9, 30)) is True

    def test_exactly_on_normal_end(self):
        assert is_within_normal_hours(hkt(2026, 4, 27, 17, 0), hkt(2026, 4, 27, 18, 0)) is True

    def test_starts_before_normal_hours(self):
        # 08:00 start is before 09:00 normal start
        assert is_within_normal_hours(hkt(2026, 4, 27, 8, 0), hkt(2026, 4, 27, 9, 0)) is False

    def test_ends_after_normal_hours(self):
        # Ends at 18:30 which is past 18:00
        assert is_within_normal_hours(hkt(2026, 4, 27, 17, 30), hkt(2026, 4, 27, 18, 30)) is False

    def test_7pm_slot_outside_hours(self):
        assert is_within_normal_hours(hkt(2026, 4, 27, 19, 0), hkt(2026, 4, 27, 20, 0)) is False

    def test_schedulable_start_8_30_is_outside_normal(self):
        # 08:30 is within schedulable window but before normal 09:00
        assert is_within_normal_hours(hkt(2026, 4, 27, 8, 30), hkt(2026, 4, 27, 9, 30)) is False

    def test_non_hkt_timezone_converted_correctly(self):
        from datetime import timezone
        # 01:00 UTC = 09:00 HKT
        utc = ZoneInfo("UTC")
        s = datetime(2026, 4, 27, 1, 0, tzinfo=utc)
        e = datetime(2026, 4, 27, 2, 0, tzinfo=utc)
        assert is_within_normal_hours(s, e) is True


# ---------------------------------------------------------------------------
# overlaps_lunch_block  (12:30–14:00 HKT)
# ---------------------------------------------------------------------------

class TestOverlapsLunchBlock:
    def test_slot_entirely_within_lunch(self):
        assert overlaps_lunch_block(hkt(2026, 4, 27, 12, 30), hkt(2026, 4, 27, 13, 30)) is True

    def test_slot_spanning_lunch_start(self):
        # 12:00-13:00 starts before lunch but ends inside it
        assert overlaps_lunch_block(hkt(2026, 4, 27, 12, 0), hkt(2026, 4, 27, 13, 0)) is True

    def test_slot_spanning_lunch_end(self):
        # 13:30-14:30 starts inside lunch and ends after it
        assert overlaps_lunch_block(hkt(2026, 4, 27, 13, 30), hkt(2026, 4, 27, 14, 30)) is True

    def test_slot_spanning_entire_lunch(self):
        assert overlaps_lunch_block(hkt(2026, 4, 27, 12, 0), hkt(2026, 4, 27, 15, 0)) is True

    def test_slot_before_lunch_no_overlap(self):
        assert overlaps_lunch_block(hkt(2026, 4, 27, 11, 0), hkt(2026, 4, 27, 12, 0)) is False

    def test_slot_ends_exactly_at_lunch_start_no_overlap(self):
        # Ends at 12:30 — does not cross into lunch (e > lunch_s requires strictly greater)
        assert overlaps_lunch_block(hkt(2026, 4, 27, 11, 30), hkt(2026, 4, 27, 12, 30)) is False

    def test_slot_starts_exactly_at_lunch_end_no_overlap(self):
        # Starts at 14:00 — lunch ends at 14:00 so s < lunch_e fails
        assert overlaps_lunch_block(hkt(2026, 4, 27, 14, 0), hkt(2026, 4, 27, 15, 0)) is False

    def test_slot_after_lunch_no_overlap(self):
        assert overlaps_lunch_block(hkt(2026, 4, 27, 14, 30), hkt(2026, 4, 27, 15, 30)) is False


# ---------------------------------------------------------------------------
# compute_schedulable_windows
# ---------------------------------------------------------------------------

class TestComputeSchedulableWindows:
    def test_returns_two_windows(self):
        windows = compute_schedulable_windows(date(2026, 4, 27))
        assert len(windows) == 2

    def test_morning_window_bounds(self):
        windows = compute_schedulable_windows(date(2026, 4, 27))
        morning_start, morning_end = windows[0]
        assert morning_start == hkt(2026, 4, 27, 8, 30)
        assert morning_end == hkt(2026, 4, 27, 12, 30)

    def test_afternoon_window_bounds(self):
        windows = compute_schedulable_windows(date(2026, 4, 27))
        afternoon_start, afternoon_end = windows[1]
        assert afternoon_start == hkt(2026, 4, 27, 14, 0)
        assert afternoon_end == hkt(2026, 4, 27, 18, 0)

    def test_windows_are_timezone_aware(self):
        windows = compute_schedulable_windows(date(2026, 4, 27))
        for ws, we in windows:
            assert ws.tzinfo is not None
            assert we.tzinfo is not None


# ---------------------------------------------------------------------------
# daily_booked_minutes
# ---------------------------------------------------------------------------

class TestDailyBookedMinutes:
    def test_empty_list(self):
        assert daily_booked_minutes([]) == 0

    def test_single_meeting(self):
        assert daily_booked_minutes([{"duration_mins": 60}]) == 60

    def test_multiple_meetings(self):
        events = [{"duration_mins": 30}, {"duration_mins": 60}, {"duration_mins": 45}]
        assert daily_booked_minutes(events) == 135

    def test_missing_duration_key_defaults_to_zero(self):
        assert daily_booked_minutes([{"title": "no duration"}]) == 0

    def test_mixed_with_and_without_duration(self):
        events = [{"duration_mins": 90}, {"title": "no duration"}]
        assert daily_booked_minutes(events) == 90


# ---------------------------------------------------------------------------
# slot_fits_in_window
# ---------------------------------------------------------------------------

class TestSlotFitsInWindow:
    def setup_method(self):
        self.window = (hkt(2026, 4, 27, 8, 30), hkt(2026, 4, 27, 12, 30))

    def test_slot_fits_exactly(self):
        assert slot_fits_in_window(
            hkt(2026, 4, 27, 8, 30), hkt(2026, 4, 27, 12, 30), self.window
        ) is True

    def test_slot_fits_inside(self):
        assert slot_fits_in_window(
            hkt(2026, 4, 27, 9, 0), hkt(2026, 4, 27, 10, 0), self.window
        ) is True

    def test_slot_starts_before_window(self):
        assert slot_fits_in_window(
            hkt(2026, 4, 27, 8, 0), hkt(2026, 4, 27, 9, 0), self.window
        ) is False

    def test_slot_ends_after_window(self):
        assert slot_fits_in_window(
            hkt(2026, 4, 27, 12, 0), hkt(2026, 4, 27, 13, 0), self.window
        ) is False

    def test_slot_completely_outside_window(self):
        assert slot_fits_in_window(
            hkt(2026, 4, 27, 14, 0), hkt(2026, 4, 27, 15, 0), self.window
        ) is False

    def test_slot_on_window_end_boundary(self):
        # End equals window end — should fit
        assert slot_fits_in_window(
            hkt(2026, 4, 27, 12, 0), hkt(2026, 4, 27, 12, 30), self.window
        ) is True


# ---------------------------------------------------------------------------
# _overlaps_any
# ---------------------------------------------------------------------------

class TestOverlapsAny:
    def test_no_events_no_overlap(self):
        assert _overlaps_any(
            hkt(2026, 4, 27, 10, 0), hkt(2026, 4, 27, 11, 0), []
        ) is False

    def test_slot_overlaps_single_event(self):
        events = [(hkt(2026, 4, 27, 10, 30), hkt(2026, 4, 27, 11, 30))]
        assert _overlaps_any(
            hkt(2026, 4, 27, 10, 0), hkt(2026, 4, 27, 11, 0), events
        ) is True

    def test_slot_adjacent_to_event_no_overlap(self):
        # Slot ends exactly when event starts — no overlap
        events = [(hkt(2026, 4, 27, 11, 0), hkt(2026, 4, 27, 12, 0))]
        assert _overlaps_any(
            hkt(2026, 4, 27, 10, 0), hkt(2026, 4, 27, 11, 0), events
        ) is False

    def test_slot_adjacent_after_event_no_overlap(self):
        # Slot starts exactly when event ends — no overlap
        events = [(hkt(2026, 4, 27, 9, 0), hkt(2026, 4, 27, 10, 0))]
        assert _overlaps_any(
            hkt(2026, 4, 27, 10, 0), hkt(2026, 4, 27, 11, 0), events
        ) is False

    def test_slot_contained_within_event(self):
        events = [(hkt(2026, 4, 27, 9, 0), hkt(2026, 4, 27, 12, 0))]
        assert _overlaps_any(
            hkt(2026, 4, 27, 10, 0), hkt(2026, 4, 27, 11, 0), events
        ) is True

    def test_event_contained_within_slot(self):
        events = [(hkt(2026, 4, 27, 10, 30), hkt(2026, 4, 27, 10, 45))]
        assert _overlaps_any(
            hkt(2026, 4, 27, 10, 0), hkt(2026, 4, 27, 11, 0), events
        ) is True

    def test_no_overlap_with_multiple_non_conflicting_events(self):
        events = [
            (hkt(2026, 4, 27, 8, 30), hkt(2026, 4, 27, 9, 30)),
            (hkt(2026, 4, 27, 11, 0), hkt(2026, 4, 27, 12, 0)),
        ]
        assert _overlaps_any(
            hkt(2026, 4, 27, 9, 30), hkt(2026, 4, 27, 10, 30), events
        ) is False

    def test_overlap_with_one_of_multiple_events(self):
        events = [
            (hkt(2026, 4, 27, 8, 30), hkt(2026, 4, 27, 9, 30)),
            (hkt(2026, 4, 27, 10, 0), hkt(2026, 4, 27, 11, 0)),
        ]
        assert _overlaps_any(
            hkt(2026, 4, 27, 9, 30), hkt(2026, 4, 27, 10, 30), events
        ) is True


# ---------------------------------------------------------------------------
# find_candidate_slots
# ---------------------------------------------------------------------------

class TestFindCandidateSlots:
    def test_free_day_returns_slots(self):
        slots = find_candidate_slots(date(2026, 4, 27), 30, [])
        # Should have morning slots (8:30–12:30) and afternoon slots (14:00–18:00)
        assert len(slots) > 0

    def test_free_day_no_slots_outside_windows(self):
        slots = find_candidate_slots(date(2026, 4, 27), 30, [])
        for s in slots:
            local = s.astimezone(HKT)
            # Must be in morning or afternoon window
            in_morning = (
                local.time() >= __import__("datetime").time(8, 30)
                and (local + timedelta(minutes=30)).astimezone(HKT).time()
                    <= __import__("datetime").time(12, 30)
            )
            in_afternoon = (
                local.time() >= __import__("datetime").time(14, 0)
                and (local + timedelta(minutes=30)).astimezone(HKT).time()
                    <= __import__("datetime").time(18, 0)
            )
            assert in_morning or in_afternoon, f"Slot {local} is outside schedulable windows"

    def test_occupied_slot_excluded(self):
        # Block 9:00–10:00, slot at 09:00 should not appear
        occupied = [(hkt(2026, 4, 27, 9, 0), hkt(2026, 4, 27, 10, 0))]
        slots = find_candidate_slots(date(2026, 4, 27), 60, occupied)
        assert hkt(2026, 4, 27, 9, 0) not in slots

    def test_partially_blocked_slot_excluded(self):
        # Block 9:30–10:30; a 60-min slot starting at 9:00 would end at 10:00
        # which overlaps. A slot starting at 10:00 ends at 11:00 — also overlaps.
        # A slot starting at 10:30 ends at 11:30 — no overlap.
        occupied = [(hkt(2026, 4, 27, 9, 30), hkt(2026, 4, 27, 10, 30))]
        slots = find_candidate_slots(date(2026, 4, 27), 60, occupied)
        assert hkt(2026, 4, 27, 9, 0) not in slots
        assert hkt(2026, 4, 27, 10, 0) not in slots
        assert hkt(2026, 4, 27, 10, 30) in slots

    def test_duration_longer_than_window_produces_no_slots(self):
        # Morning window is 4h (08:30–12:30); afternoon is 4h (14:00–18:00)
        # A 5-hour meeting cannot fit in either window
        slots = find_candidate_slots(date(2026, 4, 27), 300, [])
        assert slots == []

    def test_slot_step_respected(self):
        slots = find_candidate_slots(date(2026, 4, 27), 30, [], slot_step_mins=60)
        # With 60-min steps, only hourly starts should appear in the morning
        morning_slots = [s for s in slots if s.astimezone(HKT).hour < 12]
        for s in morning_slots:
            assert s.astimezone(HKT).minute == 30  # starts at 8:30, 9:30, 10:30, 11:30

    def test_first_slot_is_8_30(self):
        slots = find_candidate_slots(date(2026, 4, 27), 30, [])
        assert slots[0] == hkt(2026, 4, 27, 8, 30)

    def test_fully_booked_day_returns_empty(self):
        # Block the entire schedulable day
        occupied = [
            (hkt(2026, 4, 27, 8, 30), hkt(2026, 4, 27, 12, 30)),
            (hkt(2026, 4, 27, 14, 0), hkt(2026, 4, 27, 18, 0)),
        ]
        slots = find_candidate_slots(date(2026, 4, 27), 30, occupied)
        assert slots == []
