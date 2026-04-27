from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from .database import get_db


async def create_confirmation(meeting_id: int, reason: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO owner_confirmations (meeting_id, reason, created_at) VALUES (?, ?, ?)",
            (meeting_id, reason, now),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def get_confirmation(confirmation_id: int) -> dict[str, Any] | None:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM owner_confirmations WHERE id = ?", (confirmation_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_pending_confirmation_for_meeting(meeting_id: int) -> dict[str, Any] | None:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM owner_confirmations WHERE meeting_id = ? AND status = 'pending'",
            (meeting_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def resolve_confirmation(confirmation_id: int, status: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute(
            "UPDATE owner_confirmations SET status = ?, resolved_at = ? WHERE id = ?",
            (status, now, confirmation_id),
        )
        await db.commit()


async def set_owner_message_id(confirmation_id: int, message_id: int) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE owner_confirmations SET owner_message_id = ? WHERE id = ?",
            (message_id, confirmation_id),
        )
        await db.commit()
