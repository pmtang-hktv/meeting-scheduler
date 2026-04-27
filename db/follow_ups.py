from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from .database import get_db


async def create_follow_up(meeting_id: int, trigger_dt: str, job_type: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO follow_up_jobs (meeting_id, trigger_dt, job_type, created_at) VALUES (?, ?, ?, ?)",
            (meeting_id, trigger_dt, job_type, now),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def set_apscheduler_id(follow_up_id: int, apscheduler_id: str) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE follow_up_jobs SET apscheduler_id = ? WHERE id = ?",
            (apscheduler_id, follow_up_id),
        )
        await db.commit()


async def mark_sent(follow_up_id: int) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE follow_up_jobs SET status = 'sent' WHERE id = ?", (follow_up_id,)
        )
        await db.commit()


async def mark_skipped(follow_up_id: int) -> None:
    async with get_db() as db:
        await db.execute(
            "UPDATE follow_up_jobs SET status = 'skipped' WHERE id = ?", (follow_up_id,)
        )
        await db.commit()


async def get_pending_jobs_for_meeting(meeting_id: int) -> list[dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM follow_up_jobs WHERE meeting_id = ? AND status = 'pending'",
            (meeting_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
