from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any
from .database import get_db


async def get_conversation(chat_id: int) -> dict[str, Any] | None:
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM conversations WHERE chat_id = ?", (chat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return dict(row)


async def upsert_conversation(
    chat_id: int,
    state: str,
    context: dict[str, Any],
    history: list[dict[str, Any]],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO conversations (chat_id, state, context_json, history_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                state        = excluded.state,
                context_json = excluded.context_json,
                history_json = excluded.history_json,
                updated_at   = excluded.updated_at
            """,
            (chat_id, state, json.dumps(context), json.dumps(history), now),
        )
        await db.commit()


async def reset_conversation(chat_id: int) -> None:
    await upsert_conversation(chat_id, "IDLE", {}, [])
