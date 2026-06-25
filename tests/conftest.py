"""
conftest.py — environment stubs for the test suite.

aiosqlite is an optional runtime dependency that may not be installed in CI.
We stub it (and the db layer that depends on it) so that the async tests for
scheduling.availability can import cleanly.  The real db calls are always
replaced by AsyncMock in every test anyway, so no real DB is needed.

We also stub google_cal_client so that importing calendar_integration does
not require a live Google credential file.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock


def _make_stub_module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


# ---------------------------------------------------------------------------
# aiosqlite stub (only needed when the package is absent)
# ---------------------------------------------------------------------------
if "aiosqlite" not in sys.modules:
    _aiosqlite = _make_stub_module("aiosqlite")
    _aiosqlite.Row = None  # type: ignore[attr-defined]

    class _FakeConnection:
        row_factory = None

        async def execute(self, *a, **kw):
            return MagicMock()

        async def executescript(self, *a, **kw):
            pass

        async def commit(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

    class _FakeConnectCtx:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return _FakeConnection()

        async def __aexit__(self, *a):
            pass

    def _connect(*a, **kw):
        return _FakeConnectCtx()

    _aiosqlite.connect = _connect  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# db.database / db.meetings stubs
# ---------------------------------------------------------------------------
if "db.database" not in sys.modules:
    _db_database = _make_stub_module("db.database")
    _db_database.get_db = MagicMock()      # type: ignore[attr-defined]
    _db_database.configure = MagicMock()   # type: ignore[attr-defined]
    _db_database.init_db = AsyncMock()     # type: ignore[attr-defined]

if "db.meetings" not in sys.modules:
    _db_meetings = _make_stub_module("db.meetings")
    # these are patched per-test; stub as no-ops so imports succeed
    _db_meetings.get_confirmed_meetings_in_range = AsyncMock(return_value=[])  # type: ignore[attr-defined]
    _db_meetings.update_meeting = AsyncMock()  # type: ignore[attr-defined]
    _db_meetings.get_meeting = AsyncMock(return_value=None)  # type: ignore[attr-defined]
    _db_meetings.get_upcoming_confirmed_meetings = AsyncMock(return_value=[])  # type: ignore[attr-defined]
    _db_meetings.booking_ref = lambda mid: f"BK-{mid:04d}"  # type: ignore[attr-defined]

if "db" not in sys.modules:
    _db_pkg = _make_stub_module("db")

# Other db submodules imported by the bot handlers. Stubbed so that importing a
# handler module (e.g. bot.handlers.edit) doesn't require a real database; the
# individual calls are patched per-test.
if "db.conversations" not in sys.modules:
    _db_conv = _make_stub_module("db.conversations")
    _db_conv.get_conversation = AsyncMock(return_value=None)    # type: ignore[attr-defined]
    _db_conv.upsert_conversation = AsyncMock()                  # type: ignore[attr-defined]
    _db_conv.reset_conversation = AsyncMock()                   # type: ignore[attr-defined]

if "db.pending" not in sys.modules:
    _make_stub_module("db.pending")

if "db.follow_ups" not in sys.modules:
    _make_stub_module("db.follow_ups")

if "db.day_offs" not in sys.modules:
    _db_dayoffs = _make_stub_module("db.day_offs")
    _db_dayoffs.create_day_off = AsyncMock(return_value=1)       # type: ignore[attr-defined]
    _db_dayoffs.set_calendar_uid = AsyncMock()                   # type: ignore[attr-defined]
    _db_dayoffs.get_day_off = AsyncMock(return_value=None)       # type: ignore[attr-defined]
    _db_dayoffs.get_upcoming_day_offs = AsyncMock(return_value=[])  # type: ignore[attr-defined]
    _db_dayoffs.cancel_day_off = AsyncMock()                     # type: ignore[attr-defined]
    _db_dayoffs.day_off_ref = lambda i: f"OFF-{i:04d}"           # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# google_cal_client stub (avoids needing live credentials at import time)
# ---------------------------------------------------------------------------
if "calendar_integration.google_cal_client" not in sys.modules:
    _gcal = _make_stub_module("calendar_integration.google_cal_client")
    _gcal.api_list_calendars = AsyncMock(return_value=[])    # type: ignore[attr-defined]
    _gcal.api_get_events = AsyncMock(return_value=[])        # type: ignore[attr-defined]
    _gcal.api_create_event = AsyncMock(return_value="uid")   # type: ignore[attr-defined]
    _gcal.api_delete_event = AsyncMock(return_value=True)    # type: ignore[attr-defined]
    _gcal.api_get_event = AsyncMock(return_value=None)       # type: ignore[attr-defined]
