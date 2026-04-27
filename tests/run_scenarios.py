#!/usr/bin/env python
"""
Standalone scenario runner for the meeting scheduler business rules.

Usage:
    python tests/run_scenarios.py

Outputs a human-readable pass/fail report for each scenario.
No pytest dependency required — uses asyncio.run() directly.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure the project root is on sys.path when the script is run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from calendar_integration.calendar_service import CalendarEvent

HKT = ZoneInfo("Asia/Hong_Kong")


def hkt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=HKT)


def _make_event(start: datetime, end: datetime) -> CalendarEvent:
    return CalendarEvent(uid="test-uid", start=start, end=end)


def _no_events_mocks():
    return AsyncMock(return_value=[]), AsyncMock(return_value=[])


# ---------------------------------------------------------------------------
# Individual scenario runners
# ---------------------------------------------------------------------------

async def scenario_normal_free_internal() -> tuple[bool, str]:
    """Normal slot (free, internal) → auto-confirm"""
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        r = await check_slot(hkt(2026, 4, 27, 10, 0), 60, is_external=False)
    ok = r["available"] is True and r["requires_owner"] is False and r["reasons"] == []
    return ok, "auto-confirm"


async def scenario_outside_hours_7pm() -> tuple[bool, str]:
    """Outside hours (7pm) → owner approval required"""
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        r = await check_slot(hkt(2026, 4, 27, 19, 0), 60)
    ok = r["requires_owner"] is True and "outside_hours" in r["reasons"]
    return ok, "owner approval required"


async def scenario_weekend() -> tuple[bool, str]:
    """Weekend day (Sat) → owner approval required"""
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        r = await check_slot(hkt(2026, 5, 2, 10, 0), 60)  # Saturday
    ok = r["requires_owner"] is True and "outside_hours" in r["reasons"]
    return ok, "owner approval required"


async def scenario_lunch_block() -> tuple[bool, str]:
    """Lunch block (12:30-13:30) → owner approval required"""
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        r = await check_slot(hkt(2026, 4, 27, 12, 30), 60)
    ok = (r["available"] is False
          and r["requires_owner"] is True
          and "lunch_block" in r["reasons"])
    return ok, "owner approval required (lunch blocked)"


async def scenario_long_meeting() -> tuple[bool, str]:
    """Long meeting (≥2h) → owner approval required"""
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        r = await check_slot(hkt(2026, 4, 27, 9, 0), 120)
    ok = r["requires_owner"] is True and "long_meeting" in r["reasons"]
    return ok, "owner approval required"


async def scenario_external_party() -> tuple[bool, str]:
    """External party → owner approval required"""
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        r = await check_slot(hkt(2026, 4, 27, 10, 0), 60, is_external=True)
    ok = r["requires_owner"] is True and "external" in r["reasons"]
    return ok, "owner approval required"


async def scenario_conflict_not_vip() -> tuple[bool, str]:
    """Conflict (not VIP/urgent) → not available, no owner escalation"""
    from scheduling.availability import check_slot
    event = _make_event(hkt(2026, 4, 27, 10, 0), hkt(2026, 4, 27, 11, 0))
    mock_ge = AsyncMock(return_value=[event])
    mock_db = AsyncMock(return_value=[])
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        r = await check_slot(hkt(2026, 4, 27, 10, 0), 60)
    ok = r["available"] is False and r["requires_owner"] is False
    return ok, "not available, suggest alternatives"


async def scenario_conflict_vip() -> tuple[bool, str]:
    """Conflict + VIP → owner approval required (vip_conflict)"""
    from scheduling.availability import check_slot
    event = _make_event(hkt(2026, 4, 27, 10, 0), hkt(2026, 4, 27, 11, 0))
    mock_ge = AsyncMock(return_value=[event])
    mock_db = AsyncMock(return_value=[])
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        r = await check_slot(hkt(2026, 4, 27, 10, 0), 60, is_vip=True)
    ok = (r["available"] is False
          and r["requires_owner"] is True
          and "vip_conflict" in r["reasons"])
    return ok, "owner approval required (vip_conflict)"


async def scenario_conflict_urgent() -> tuple[bool, str]:
    """Conflict + urgent → owner approval required (urgent_conflict)"""
    from scheduling.availability import check_slot
    event = _make_event(hkt(2026, 4, 27, 10, 0), hkt(2026, 4, 27, 11, 0))
    mock_ge = AsyncMock(return_value=[event])
    mock_db = AsyncMock(return_value=[])
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        r = await check_slot(hkt(2026, 4, 27, 10, 0), 60, is_urgent=True)
    ok = (r["available"] is False
          and r["requires_owner"] is True
          and "urgent_conflict" in r["reasons"])
    return ok, "owner approval required (urgent_conflict)"


async def scenario_multiple_reasons() -> tuple[bool, str]:
    """Multiple reasons (external + long + outside hours) → all reasons present"""
    from scheduling.availability import check_slot
    mock_ge, mock_db = _no_events_mocks()
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        r = await check_slot(hkt(2026, 4, 27, 19, 0), 180, is_external=True)
    ok = (r["requires_owner"] is True
          and "outside_hours" in r["reasons"]
          and "long_meeting" in r["reasons"]
          and "external" in r["reasons"])
    return ok, "owner approval required (outside_hours + long_meeting + external)"


async def scenario_calendar_unavailable() -> tuple[bool, str]:
    """Calendar unreadable → slot blocked (calendar_unavailable)"""
    from scheduling.availability import check_slot
    mock_ge = AsyncMock(return_value=None)
    mock_db = AsyncMock(return_value=[])
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        r = await check_slot(hkt(2026, 4, 27, 10, 0), 60)
    ok = r["available"] is False and "calendar_unavailable" in r["reasons"]
    return ok, "blocked (calendar_unavailable)"


async def scenario_find_slots_free_day() -> tuple[bool, str]:
    """find_next_available_slots — free day returns slots"""
    from scheduling.availability import find_next_available_slots
    mock_ge = AsyncMock(return_value=[])
    mock_db = AsyncMock(return_value=[])
    with patch("scheduling.availability.get_events", mock_ge), \
         patch("scheduling.availability.get_confirmed_meetings_in_range", mock_db):
        slots = await find_next_available_slots(hkt(2026, 4, 27, 10, 0), 30, max_results=5)
    ok = len(slots) > 0
    return ok, f"found {len(slots)} slot(s)"


# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------

SCENARIOS = [
    ("Normal slot (free, internal)",           scenario_normal_free_internal),
    ("Outside hours (7pm)",                    scenario_outside_hours_7pm),
    ("Weekend day (Saturday)",                 scenario_weekend),
    ("Lunch block (12:30-13:30)",              scenario_lunch_block),
    ("Long meeting (≥2h)",                     scenario_long_meeting),
    ("External party",                         scenario_external_party),
    ("Conflict (not VIP/urgent)",              scenario_conflict_not_vip),
    ("Conflict + VIP",                         scenario_conflict_vip),
    ("Conflict + urgent",                      scenario_conflict_urgent),
    ("Multiple reasons combined",              scenario_multiple_reasons),
    ("Calendar unavailable",                   scenario_calendar_unavailable),
    ("find_next_available_slots — free day",   scenario_find_slots_free_day),
]


async def run_all() -> int:
    """Run all scenarios and print a report. Returns number of failures."""
    print()
    print("MEETING SCHEDULER — BUSINESS RULE SCENARIOS")
    print("=" * 44)

    label_width = max(len(name) for name, _ in SCENARIOS) + 2
    passed = 0
    failed = 0

    for name, fn in SCENARIOS:
        try:
            ok, outcome = await fn()
        except Exception as exc:
            ok = False
            outcome = f"ERROR: {exc}"

        status = "✓" if ok else "✗"
        print(f"{status} {name:<{label_width}} → {outcome}")
        if ok:
            passed += 1
        else:
            failed += 1

    total = passed + failed
    print()
    print(f"PASSED: {passed}/{total}")
    if failed:
        print(f"FAILED: {failed}/{total}")
    return failed


if __name__ == "__main__":
    failures = asyncio.run(run_all())
    sys.exit(0 if failures == 0 else 1)
