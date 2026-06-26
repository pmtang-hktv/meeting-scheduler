from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo
from .database import get_db

HKT = ZoneInfo("Asia/Hong_Kong")


async def create_day_off(
    requester_chat_id: int,
    person_name: str,
    start_date: str,
    end_date: str,
    half_day: str | None = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO day_offs (requester_chat_id, person_name, start_date, end_date, half_day, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (requester_chat_id, person_name, start_date, end_date, half_day, now),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def set_calendar_uid(day_off_id: int, uid: str) -> None:
    async with get_db() as db:
        await db.execute("UPDATE day_offs SET calendar_uid = ? WHERE id = ?", (uid, day_off_id))
        await db.commit()


async def get_day_off(day_off_id: int) -> dict[str, Any] | None:
    async with get_db() as db:
        async with db.execute("SELECT * FROM day_offs WHERE id = ?", (day_off_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_upcoming_day_offs(requester_chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Return this person's confirmed day-offs that haven't fully passed, soonest first."""
    today = datetime.now(tz=HKT).date().isoformat()
    async with get_db() as db:
        async with db.execute(
            """
            SELECT * FROM day_offs
            WHERE requester_chat_id = ?
              AND status = 'confirmed'
              AND end_date >= ?
            ORDER BY start_date ASC
            LIMIT ?
            """,
            (requester_chat_id, today, limit),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def cancel_day_off(day_off_id: int) -> None:
    async with get_db() as db:
        await db.execute("UPDATE day_offs SET status = 'cancelled' WHERE id = ?", (day_off_id,))
        await db.commit()


def day_off_ref(day_off_id: int) -> str:
    return f"OFF-{day_off_id:04d}"
