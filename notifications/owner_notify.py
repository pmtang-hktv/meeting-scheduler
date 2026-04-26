from __future__ import annotations
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Bot
from bot.keyboards import approval_keyboard

logger = logging.getLogger(__name__)
HKT = ZoneInfo("Asia/Hong_Kong")

_owner_id: int = 0
_bot: Bot | None = None


def configure(bot: Bot, owner_id: int) -> None:
    global _bot, _owner_id
    _bot = bot
    _owner_id = owner_id


def _format_dt(dt_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_iso).astimezone(HKT)
        return dt.strftime("%a %d %b %Y, %H:%M HKT")
    except Exception:
        return dt_iso


async def send_owner_confirmation_request(
    confirmation_id: int,
    meeting_id: int,
    organizer_name: str,
    purpose: str,
    start_dt: str,
    duration_mins: int,
    reasons: list[str],
    requester_chat_id: int,
    location_area: str | None = None,
) -> int | None:
    assert _bot is not None
    reason_labels = {
        "outside_hours": "Outside normal hours",
        "long_meeting": "Long meeting (≥2h)",
        "external": "External party",
        "vip_conflict": "VIP conflict",
        "urgent_conflict": "Urgent request — conflict",
    }
    reason_text = "\n".join(f"• {reason_labels.get(r, r)}" for r in reasons)
    loc_line = f"\nLocation area: {location_area}" if location_area else ""
    text = (
        f"Meeting approval required\n\n"
        f"From: {organizer_name} (chat {requester_chat_id})\n"
        f"Purpose: {purpose}\n"
        f"When: {_format_dt(start_dt)}\n"
        f"Duration: {duration_mins} min{loc_line}\n\n"
        f"Reason(s) for approval:\n{reason_text}\n\n"
        f"Confirmation ID: {confirmation_id}"
    )
    try:
        msg = await _bot.send_message(
            chat_id=_owner_id,
            text=text,
            reply_markup=approval_keyboard(confirmation_id),
        )
        return msg.message_id
    except Exception:
        logger.exception("Failed to send owner confirmation request")
        return None


async def send_owner_alert(
    organizer_name: str,
    purpose: str,
    start_dt: str,
    duration_mins: int,
    alert_type: str,
    requester_chat_id: int,
) -> None:
    assert _bot is not None
    labels = {
        "vip_conflict": "VIP meeting conflict",
        "urgent_conflict": "Urgent request — conflict",
    }
    label = labels.get(alert_type, alert_type)
    text = (
        f"Alert: {label}\n\n"
        f"Organizer: {organizer_name}\n"
        f"Purpose: {purpose}\n"
        f"Requested time: {_format_dt(start_dt)}\n"
        f"Duration: {duration_mins} min\n"
        f"Requester chat: {requester_chat_id}"
    )
    try:
        await _bot.send_message(chat_id=_owner_id, text=text)
    except Exception:
        logger.exception("Failed to send owner alert")
