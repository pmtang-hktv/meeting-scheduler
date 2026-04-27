from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from calendar_integration.calendar_service import create_event
from db import conversations as conv_db, meetings as meet_db, pending as pend_db
from notifications import owner_notify
from scheduling.availability import find_next_available_slots

logger = logging.getLogger(__name__)
HKT = ZoneInfo("Asia/Hong_Kong")

_bot = None
_settings = None


def configure(bot, settings) -> None:
    global _bot, _settings
    _bot = bot
    _settings = settings


async def handle_owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""
    if not (data.startswith("approve:") or data.startswith("reject:")):
        return

    action, conf_id_str = data.split(":", 1)
    confirmation_id = int(conf_id_str)

    confirmation = await pend_db.get_confirmation(confirmation_id)
    if not confirmation or confirmation["status"] != "pending":
        await query.edit_message_text("This request has already been resolved.")
        return

    meeting = await meet_db.get_meeting(confirmation["meeting_id"])
    if not meeting:
        await query.edit_message_text("Meeting not found.")
        return

    if action == "approve":
        await _approve_meeting(query, confirmation, meeting)
    else:
        await _reject_meeting(query, confirmation, meeting)


async def _approve_meeting(query, confirmation: dict, meeting: dict) -> None:
    start_dt = datetime.fromisoformat(meeting["start_dt"]).astimezone(HKT)
    end_dt = datetime.fromisoformat(meeting["end_dt"]).astimezone(HKT)

    from bot.handlers.colleague import _event_title, _event_location
    event_title = _event_title(meeting.get("purpose") or "Meeting", meeting.get("organizer_name") or "")
    event_location = _event_location(bool(meeting.get("is_external")), meeting.get("location_area"))
    uid = await create_event(
        title=event_title,
        start_dt=start_dt,
        end_dt=end_dt,
        location=event_location,
        notes=meeting.get("purpose") or "",
    )
    await meet_db.update_meeting(
        meeting["id"],
        calendar_uid=uid or None,
        status="confirmed",
    )
    await pend_db.resolve_confirmation(confirmation["id"], "approved")

    local_start = start_dt.strftime("%a %d %b %Y at %H:%M HKT")
    await query.edit_message_text(f"Approved. Event created for {local_start}.")

    if _bot:
        msg = (
            f"Great news! Your meeting request has been approved.\n"
            f"Confirmed for {local_start} ({meeting['duration_mins']} min)."
        )
        if meeting.get("is_external"):
            msg += "\nWe'll follow up to confirm the exact location closer to the time."
        try:
            await _bot.send_message(chat_id=meeting["requester_chat_id"], text=msg)
        except Exception:
            logger.exception("Failed to notify requester of approval")

    # Schedule location follow-ups for external meetings
    from bot.handlers.colleague import _schedule_location_followups
    await _schedule_location_followups(
        meeting["id"],
        datetime.fromisoformat(meeting["start_dt"]),
        bool(meeting.get("is_external")),
    )
    await conv_db.reset_conversation(meeting["requester_chat_id"], known_name=meeting.get("organizer_name"))


async def _reject_meeting(query, confirmation: dict, meeting: dict) -> None:
    await meet_db.update_meeting(meeting["id"], status="cancelled")
    await pend_db.resolve_confirmation(confirmation["id"], "rejected")

    start_dt = datetime.fromisoformat(meeting["start_dt"]).astimezone(HKT)
    local_start = start_dt.strftime("%a %d %b %Y at %H:%M HKT")
    await query.edit_message_text(f"Rejected request for {local_start}.")

    if _bot:
        # Find alternatives to offer
        slots = await find_next_available_slots(
            datetime.fromisoformat(meeting["start_dt"]),
            meeting["duration_mins"],
            max_results=5,
        )
        if slots:
            formatted = "\n".join(
                f"• {s.astimezone(HKT).strftime('%a %d %b, %H:%M HKT')}" for s in slots
            )
            msg = (
                f"Unfortunately your meeting request for {local_start} could not be accommodated.\n\n"
                f"Here are some alternative times that might work:\n{formatted}\n\n"
                f"Please reply with your preferred time."
            )
        else:
            msg = (
                f"Unfortunately your meeting request for {local_start} could not be accommodated. "
                f"Please propose a different time."
            )
        try:
            await _bot.send_message(chat_id=meeting["requester_chat_id"], text=msg)
        except Exception:
            logger.exception("Failed to notify requester of rejection")

    # Reset requester conversation to IDLE
    row = await conv_db.get_conversation(meeting["requester_chat_id"])
    if row:
        ctx = json.loads(row["context_json"])
        ctx.pop("confirmation_id", None)
        ctx.pop("meeting_id", None)
        # Clear meeting-time fields so the next message must supply a fresh time —
        # otherwise the rejected time persists and re-triggers the same approval flow.
        ctx.pop("proposed_dt", None)
        ctx.pop("alternative_slots", None)
        ctx.pop("is_vip", None)
        ctx.pop("is_urgent", None)
        await conv_db.upsert_conversation(
            meeting["requester_chat_id"], "GATHERING_INFO", ctx,
            json.loads(row["history_json"])
        )
