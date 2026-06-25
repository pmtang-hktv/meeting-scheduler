"""Regression: is_vip must not be sticky across turns."""
from __future__ import annotations
import json
from unittest.mock import AsyncMock, patch

import pytest

from ai.intent import ConversationTurn


def _turn(is_vip: bool) -> ConversationTurn:
    # An "other"-intent turn with no meeting fields → handle_message takes the
    # conversational reply branch (which persists the merged context).
    return ConversationTurn(
        intent="other",
        organizer_name="Winnie AY",
        purpose=None,
        duration_mins=None,
        proposed_dt=None,
        is_external=False,
        location_area=None,
        is_vip=is_vip,
        is_urgent=False,
        missing_fields=["purpose", "duration_mins", "proposed_dt"],
        reply="How can I help?",
        reply_type=None,
    )


@pytest.mark.asyncio
async def test_is_vip_is_not_sticky():
    import bot.handlers.colleague as col

    # Existing conversation already has is_vip/is_urgent=True latched from a prior turn.
    existing_ctx = {"organizer_name": "Winnie AY", "is_vip": True, "is_urgent": True}
    row = {
        "state": "GATHERING_INFO",
        "context_json": json.dumps(existing_ctx),
        "history_json": json.dumps([]),
    }

    update = AsyncMock()
    update.effective_chat.id = 7584050363
    update.message.text = "ok"

    captured = {}

    async def fake_upsert(chat_id, state, ctx, history):
        captured["ctx"] = ctx

    with patch.object(col, "process_turn", AsyncMock(return_value=_turn(is_vip=False))), \
         patch.object(col.conv_db, "get_conversation", AsyncMock(return_value=row)), \
         patch.object(col.conv_db, "upsert_conversation", fake_upsert):
        await col.handle_message(update, None)

    # The current turn said not-VIP / not-urgent, so the persisted context must be
    # False, not the latched True from before.
    assert captured["ctx"]["is_vip"] is False
    assert captured["ctx"]["is_urgent"] is False
