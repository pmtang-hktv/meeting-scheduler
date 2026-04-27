from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from .database import get_db


async def create_meeting(
    requester_chat_id: int,
    organizer_name: str,
    purpose: str,
    start_dt: str,
    end_dt: str,
    duration_mins: int,
    is_external: bool = False,
    location_area: str | None = None,
    travel_mins: int | None = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            """
            INSERT INTO meetings
                (requester_chat_id, organizer_name, purpose, start_dt, end_dt,
                 duration_mins, is_external, location_area, travel_mins, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                requester_chat_id, organizer_name, purpose, start_dt, end_dt,
                duration_mins, int(is_external), location_area, travel_mins, now, now,
            ),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def get_meeting(meeting_id: int) -> dict[str, Any] | None:
    async with get_db() as db:
        async with db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_meeting(meeting_id: int, **fields: Any) -> None:
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [meeting_id]
    async with get_db() as db:
        await db.execute(f"UPDATE meetings SET {set_clause} WHERE id = ?", values)
        await db.commit()


async def get_unconfirmed_location_meetings() -> list[dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM meetings WHERE location_confirmed = 0 AND status = 'confirmed'"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_confirmed_meetings_in_range(start_iso: str, end_iso: str) -> list[dict[str, Any]]:
    """Return confirmed meetings whose time overlaps [start_iso, end_iso)."""
    async with get_db() as db:
        async with db.execute(
            """
            SELECT * FROM meetings
            WHERE status = 'confirmed'
              AND start_dt < ? AND end_dt > ?
            """,
            (end_iso, start_iso),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
