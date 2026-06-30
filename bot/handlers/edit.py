"""Handlers for the 'New booking / Change a booking' menu and the edit flow.

The menu is driven by inline buttons; the per-chat state is persisted in the
`conversations` table (same pattern as the rest of the bot) so the text handler
in ``colleague.handle_message`` can pick up a typed field value via the
``EDITING_FIELD`` state. Callback handlers here are registered globally (after
the ConversationHandler), exactly like the owner approve/reject callbacks.
"""
from __future__ import annotations
import html
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from ai.intent import process_turn, parse_duration_mins
from bot.handlers import colleague
from bot.keyboards import (
    booking_list_keyboard,
    cancel_confirm_keyboard,
    cancel_edit_keyboard,
    edit_fields_keyboard,
    main_menu_keyboard,
)
from calendar_integration import calendar_service as cal_svc
from db import conversations as conv_db, meetings as meet_db
from scheduling.availability import check_slot

logger = logging.getLogger(__name__)
HKT = ZoneInfo("Asia/Hong_Kong")

_NEW_BOOKING_PROMPT = (
    "Great — let's set up a new meeting with Simon. Please tell me:\n\n"
    "1. <b>What is the meeting about?</b> (the purpose)\n"
    "2. <b>When</b> would you like to meet? (date and time)\n"
    "3. <b>How long</b> will it take? (duration in minutes)\n"
    "4. Are you <b>internal</b> (HKTV colleague) or <b>external</b>? "
    "(if external, which area/district?)"
)

_FIELD_PROMPTS = {
    "datetime": "What's the new <b>date and time</b>? (e.g. <b>Tuesday 3pm</b> or <b>30 Jun 15:00</b>)",
    "duration": "What's the new <b>duration</b>? (e.g. <b>45 minutes</b> or <b>1 hour</b>)",
    "location": "What's the new <b>location</b>? (e.g. <b>Office</b> or <b>Causeway Bay</b>)",
    "purpose": "What's the meeting now <b>about</b>?",
    "organiser": "Who is the <b>organiser</b> now? (full name)",
}

# Appended to every prompt/retry shown while waiting for a typed value, so a user
# who changes their mind (or types something unrelated) always has a way out.
_ESCAPE_HINT = "\n\n<i>Changed your mind? Tap ✖ Cancel editing below, or type /menu.</i>"


async def _retry(update: Update, text_html: str) -> int:
    """Re-prompt for the current field, keeping an escape hatch visible."""
    await update.message.reply_text(
        text_html + _ESCAPE_HINT,
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_edit_keyboard(),
    )
    # DB state stays EDITING_FIELD, so the next message retries this same field.
    return ConversationHandler.END


# --------------------------------------------------------------------------- #
# Menu commands                                                               #
# --------------------------------------------------------------------------- #

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show the two-button menu (New booking / Change a booking)."""
    if not update.message or not update.effective_chat:
        return ConversationHandler.END
    chat_id = update.effective_chat.id
    # Clear any half-finished flow (e.g. a pending edit awaiting a typed value) so the
    # next message isn't captured as a field value instead of a fresh request.
    row = await conv_db.get_conversation(chat_id)
    name = json.loads(row["context_json"]).get("organizer_name") if row else None
    await conv_db.reset_conversation(chat_id, known_name=name)
    await update.message.reply_text(
        "What would you like to do?",
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


# --------------------------------------------------------------------------- #
# Callback router                                                             #
# --------------------------------------------------------------------------- #

async def handle_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_chat:
        return
    try:
        await query.answer()
    except Exception:
        # Callback expired (bot restarted after the button was sent) — ignore.
        return
    chat_id = update.effective_chat.id
    data = query.data or ""

    row = await conv_db.get_conversation(chat_id)
    ctx: dict = json.loads(row["context_json"]) if row else {}
    history: list[dict] = json.loads(row["history_json"]) if row else []

    if data == "menu:new":
        await _start_new_booking(query, chat_id, ctx)
    elif data == "menu:change":
        await _show_booking_list(query, chat_id, ctx, history)
    elif data == "editcancel":
        await _finish(query, chat_id, ctx)
    elif data.startswith("editpick:"):
        await _show_edit_menu_callback(query, chat_id, ctx, history, int(data.split(":", 1)[1]))
    elif data.startswith("editfield:"):
        _, mid, field = data.split(":", 2)
        await _prompt_for_field(query, chat_id, ctx, history, int(mid), field)
    elif data.startswith("editdelete:"):
        await _confirm_cancel(query, chat_id, ctx, history, int(data.split(":", 1)[1]))
    elif data.startswith("editdelyes:"):
        await _do_cancel(query, chat_id, ctx, int(data.split(":", 1)[1]))


async def _start_new_booking(query, chat_id: int, ctx: dict) -> None:
    name = ctx.get("organizer_name")
    await conv_db.upsert_conversation(
        chat_id, "GATHERING_INFO", {"organizer_name": name} if name else {}, []
    )
    await query.edit_message_text(_NEW_BOOKING_PROMPT, parse_mode=ParseMode.HTML)


async def _show_booking_list(query, chat_id: int, ctx: dict, history: list[dict]) -> None:
    meetings = await meet_db.get_upcoming_confirmed_meetings(chat_id)
    if not meetings:
        await query.edit_message_text(
            "You don't have any upcoming bookings to change. "
            "Type /menu and choose <b>New booking</b> to make one.",
            parse_mode=ParseMode.HTML,
        )
        await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))
        return
    labelled = [(m, _button_label(m)) for m in meetings]
    await conv_db.upsert_conversation(chat_id, "CHOOSING_BOOKING", ctx, history)
    await query.edit_message_text(
        "Which booking would you like to change?",
        reply_markup=booking_list_keyboard(labelled),
    )


async def _show_edit_menu_callback(query, chat_id: int, ctx: dict, history: list[dict], meeting_id: int) -> None:
    meeting = await meet_db.get_meeting(meeting_id)
    if not _owns(meeting, chat_id):
        await query.edit_message_text("Sorry, I can't find that booking any more.")
        await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))
        return
    ctx["edit_meeting_id"] = meeting_id
    ctx.pop("edit_field", None)
    await conv_db.upsert_conversation(chat_id, "EDIT_MENU", ctx, history)
    await query.edit_message_text(
        _summary_text(meeting) + "\n\nWhat would you like to change?",
        reply_markup=edit_fields_keyboard(meeting_id),
        parse_mode=ParseMode.HTML,
    )


async def _prompt_for_field(query, chat_id: int, ctx: dict, history: list[dict], meeting_id: int, field: str) -> None:
    meeting = await meet_db.get_meeting(meeting_id)
    if not _owns(meeting, chat_id) or field not in _FIELD_PROMPTS:
        await query.edit_message_text("Sorry, I can't find that booking any more.")
        await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))
        return
    ctx["edit_meeting_id"] = meeting_id
    ctx["edit_field"] = field
    await conv_db.upsert_conversation(chat_id, "EDITING_FIELD", ctx, history)
    await query.edit_message_text(
        _FIELD_PROMPTS[field] + _ESCAPE_HINT,
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_edit_keyboard(),
    )


async def _finish(query, chat_id: int, ctx: dict) -> None:
    await query.edit_message_text("All done. Type /menu anytime to make or change a booking.")
    await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))


async def _confirm_cancel(query, chat_id: int, ctx: dict, history: list[dict], meeting_id: int) -> None:
    meeting = await meet_db.get_meeting(meeting_id)
    if not _owns(meeting, chat_id):
        await query.edit_message_text("Sorry, I can't find that booking any more.")
        await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))
        return
    start = datetime.fromisoformat(meeting["start_dt"]).astimezone(HKT)
    ref = meet_db.booking_ref(meeting_id)
    await conv_db.upsert_conversation(chat_id, "EDIT_MENU", ctx, history)
    await query.edit_message_text(
        f"Cancel booking <b>{ref}</b> on {start.strftime('%a %d %b %Y at %H:%M')} HKT? "
        f"This removes it from Simon's calendar and can't be undone.",
        reply_markup=cancel_confirm_keyboard(meeting_id),
        parse_mode=ParseMode.HTML,
    )


async def _do_cancel(query, chat_id: int, ctx: dict, meeting_id: int) -> None:
    meeting = await meet_db.get_meeting(meeting_id)
    if not _owns(meeting, chat_id):
        await query.edit_message_text("Sorry, I can't find that booking any more.")
        await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))
        return
    cal_uid = meeting.get("calendar_uid")
    if cal_uid:
        await cal_svc.delete_event(cal_uid)
    await meet_db.update_meeting(meeting_id, status="cancelled")
    start = datetime.fromisoformat(meeting["start_dt"]).astimezone(HKT)
    ref = meet_db.booking_ref(meeting_id)
    await query.edit_message_text(
        f"🗑 Booking <b>{ref}</b> on {start.strftime('%a %d %b at %H:%M')} HKT has been cancelled.",
        parse_mode=ParseMode.HTML,
    )
    await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))


# --------------------------------------------------------------------------- #
# Applying a typed field value (called from colleague.handle_message)          #
# --------------------------------------------------------------------------- #

async def apply_field_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    ctx: dict,
    history: list[dict],
    text: str,
) -> int:
    """Apply the new value the user typed for the field they chose to edit."""
    meeting_id = ctx.get("edit_meeting_id")
    field = ctx.get("edit_field")
    meeting = await meet_db.get_meeting(meeting_id) if meeting_id else None
    if not _owns(meeting, chat_id) or field not in _FIELD_PROMPTS:
        await update.message.reply_text("Sorry, I can't find that booking any more. Type /menu to start over.")
        await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))
        return ConversationHandler.END

    if field in ("datetime", "duration"):
        return await _apply_time_change(update, chat_id, ctx, history, meeting, field, text)
    return await _apply_metadata_change(update, chat_id, ctx, history, meeting, field, text)


async def _apply_metadata_change(update, chat_id, ctx, history, meeting, field, text) -> int:
    value = text.strip()
    if not value:
        return await _retry(update, "Please type the new value.")

    cal_uid = meeting.get("calendar_uid")
    if field == "purpose":
        await meet_db.update_meeting(meeting["id"], purpose=value)
        if cal_uid:
            await cal_svc.update_event(
                cal_uid,
                title=colleague._event_title(value, meeting["organizer_name"]),
                notes=value,
            )
    elif field == "organiser":
        await meet_db.update_meeting(meeting["id"], organizer_name=value)
        if cal_uid:
            await cal_svc.update_event(
                cal_uid, title=colleague._event_title(meeting["purpose"], value)
            )
    elif field == "location":
        await meet_db.update_meeting(meeting["id"], location_area=value)
        if cal_uid:
            await cal_svc.update_event(cal_uid, location=value)

    await update.message.reply_text("✅ Updated.")
    return await _reshow_menu(update, chat_id, ctx, history, meeting["id"])


async def _apply_time_change(update, chat_id, ctx, history, meeting, field, text) -> int:
    duration = meeting["duration_mins"]
    new_start = datetime.fromisoformat(meeting["start_dt"]).astimezone(HKT)

    if field == "duration":
        # A bare duration like "1 hour" or "45" is parsed deterministically — it must
        # never depend on the LLM correctly classifying a contextless message. Fall back
        # to the LLM only if the plain parse fails (e.g. an oddly phrased duration).
        new_duration = parse_duration_mins(text)
        if new_duration is None:
            new_duration = (await process_turn([], text)).duration_mins
        if not new_duration:
            return await _retry(
                update,
                "Sorry, I couldn't understand that duration. Please give a number of "
                "minutes — e.g. <b>45</b> or <b>1 hour</b>.",
            )
        duration = new_duration
    else:  # datetime
        turn = await process_turn([], text)
        if not turn.proposed_dt:
            return await _retry(
                update,
                "Sorry, I couldn't understand that date/time. Please try again — "
                "e.g. <b>Tuesday 3pm</b> or <b>30 Jun 15:00</b>.",
            )
        new_start = turn.proposed_dt
        # If the user's message also implies a new length (e.g. a "12:00-12:30" range),
        # honour it — otherwise we'd re-check the booking's old duration at the new start
        # and wrongly reject a slot the user meant to be shorter.
        if turn.duration_mins:
            duration = turn.duration_mins

    if new_start < datetime.now(tz=HKT) - timedelta(hours=1):
        return await _retry(update, "That time has already passed. Please choose a future date and time.")

    new_end = new_start + timedelta(minutes=duration)
    result = await check_slot(
        start_dt=new_start,
        duration_mins=duration,
        is_external=bool(meeting.get("is_external")),
        travel_mins=meeting.get("travel_mins") or 0,
        exclude_uid=meeting.get("calendar_uid"),
    )

    if "calendar_unavailable" in result["reasons"]:
        return await _retry(
            update, "I'm having trouble reading the calendar right now. Please try again in a moment."
        )
    if not result["available"]:
        window = f"{new_start.strftime('%a %d %b %H:%M')}–{new_end.strftime('%H:%M')} ({duration} min)"
        return await _retry(
            update,
            f"That time isn't available — {window} clashes with something on Simon's calendar. "
            "Please suggest a different time.",
        )

    cal_uid = meeting.get("calendar_uid")
    if cal_uid:
        ok = await cal_svc.update_event(cal_uid, start_dt=new_start, end_dt=new_end)
        if not ok:
            logger.error("Calendar update failed for meeting %d", meeting["id"])
            return await _retry(
                update, "Sorry, I couldn't update the calendar event just now. Please try again in a moment."
            )

    await meet_db.update_meeting(
        meeting["id"],
        start_dt=new_start.astimezone(timezone.utc).isoformat(),
        end_dt=new_end.astimezone(timezone.utc).isoformat(),
        duration_mins=duration,
    )
    local = new_start.strftime("%A %d %B %Y at %H:%M HKT")
    await update.message.reply_text(f"✅ Updated — your meeting is now {local} ({duration} min).")
    return await _reshow_menu(update, chat_id, ctx, history, meeting["id"])


async def _reshow_menu(update, chat_id, ctx, history, meeting_id) -> int:
    """After an edit, re-display the field menu so the user can change more or finish."""
    meeting = await meet_db.get_meeting(meeting_id)
    ctx["edit_meeting_id"] = meeting_id
    ctx.pop("edit_field", None)
    await conv_db.upsert_conversation(chat_id, "EDIT_MENU", ctx, history)
    if meeting:
        await update.message.reply_text(
            _summary_text(meeting) + "\n\nAnything else to change?",
            reply_markup=edit_fields_keyboard(meeting_id),
            parse_mode=ParseMode.HTML,
        )
    return ConversationHandler.END


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _owns(meeting: dict | None, chat_id: int) -> bool:
    """A booking can only be viewed/edited by the requester who created it."""
    return bool(
        meeting
        and meeting.get("requester_chat_id") == chat_id
        and meeting.get("status") == "confirmed"
    )


def _button_label(meeting: dict) -> str:
    start = datetime.fromisoformat(meeting["start_dt"]).astimezone(HKT)
    purpose = (meeting.get("purpose") or "Meeting").strip()
    if len(purpose) > 25:
        purpose = purpose[:24] + "…"
    return f"{start.strftime('%a %d %b %H:%M')} — {purpose}"


def _summary_text(meeting: dict) -> str:
    start = datetime.fromisoformat(meeting["start_dt"]).astimezone(HKT)
    ref = meet_db.booking_ref(meeting["id"])
    if meeting.get("location_area"):
        loc = meeting["location_area"]
    elif meeting.get("is_external"):
        loc = "Off-site (to be confirmed)"
    else:
        loc = "Office"
    return "\n".join([
        f"<b>Booking {ref}</b>",
        f"📅 {start.strftime('%a %d %b %Y, %H:%M')} HKT ({meeting['duration_mins']} min)",
        f"📍 {html.escape(loc)}",
        f"📝 {html.escape(meeting['purpose'])}",
        f"👤 {html.escape(meeting['organizer_name'])}",
    ])

