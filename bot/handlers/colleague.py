from __future__ import annotations
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler

from ai.claude_client import evaluate_location_reply
from ai.intent import process_turn, ConversationTurn
from bot.keyboards import slot_choice_keyboard
from calendar_integration.calendar_service import create_event, delete_event
from db import conversations as conv_db, meetings as meet_db, pending as pend_db, follow_ups as fu_db
from notifications import owner_notify
from scheduling.availability import check_slot, compute_free_blocks_for_day, find_next_available_slots
from scheduling.rules import is_business_day
from scheduling.travel import get_travel_minutes

logger = logging.getLogger(__name__)
HKT = ZoneInfo("Asia/Hong_Kong")

# Conversation states
GATHERING_INFO = 1
CHECKING_AVAILABILITY = 2
SUGGESTING_ALTERNATIVES = 3
CONFIRMING_WITH_REQUESTER = 4
AWAITING_OWNER_DECISION = 5
AWAITING_LOCATION = 6

# Per-chat rate limit: max messages per minute
_RATE_LIMIT = 10
_rate_counters: dict[int, list[float]] = {}


def _is_rate_limited(chat_id: int) -> bool:
    import time
    now = time.time()
    window = _rate_counters.setdefault(chat_id, [])
    # keep only timestamps within last 60s
    _rate_counters[chat_id] = [t for t in window if now - t < 60]
    if len(_rate_counters[chat_id]) >= _RATE_LIMIT:
        return True
    _rate_counters[chat_id].append(now)
    return False


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.effective_chat:
        return ConversationHandler.END
    chat_id = update.effective_chat.id
    text = update.message.text or ""

    if _is_rate_limited(chat_id):
        await update.message.reply_text("Please slow down — too many messages at once.")
        return GATHERING_INFO

    row = await conv_db.get_conversation(chat_id)
    state = row["state"] if row else "IDLE"
    ctx: dict = json.loads(row["context_json"]) if row else {}
    history: list[dict] = json.loads(row["history_json"]) if row else []

    # Location reply — requester is responding to a pre-meeting location chase message.
    if state == "AWAITING_LOCATION":
        meeting_id = ctx.get("awaiting_location_meeting_id")
        meeting = await meet_db.get_meeting(meeting_id) if meeting_id else None
        if meeting:
            start_local = datetime.fromisoformat(meeting["start_dt"]).astimezone(HKT).strftime("%a %d %b at %H:%M HKT")
            found, location, reply = await evaluate_location_reply(
                purpose=meeting.get("purpose", "meeting"),
                meeting_date=start_local,
                user_message=text,
            )
        else:
            found, location, reply = False, None, "Sorry, I couldn't find the meeting details. Please contact Simon directly."
        await update.message.reply_text(reply)
        if found and location and meeting_id:
            await meet_db.update_meeting(meeting_id, location_exact=location, location_confirmed=1)
            await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))
            return ConversationHandler.END
        # Location not confirmed yet — stay in AWAITING_LOCATION for the next reply.
        await conv_db.upsert_conversation(chat_id, "AWAITING_LOCATION", ctx, history)
        return AWAITING_LOCATION

    # Greet returning users and pre-fill their name so the bot doesn't ask again
    known_name = ctx.get("organizer_name")
    if known_name and not history:
        history = [
            {"role": "user", "content": f"My name is {known_name}."},
            {"role": "assistant", "content": f"Welcome back, {known_name}! How can I help you today?"},
        ]

    turn: ConversationTurn = await process_turn(history, text)

    # Update history (keep last 20 turns to avoid unbounded growth)
    history.append({"role": "user", "content": text})
    if turn.reply:
        history.append({"role": "assistant", "content": turn.reply})
    history = history[-40:]

    # Merge extracted fields into context
    if turn.organizer_name:
        ctx["organizer_name"] = turn.organizer_name
    if turn.purpose:
        ctx["purpose"] = turn.purpose
    if turn.duration_mins:
        ctx["duration_mins"] = turn.duration_mins
    if turn.proposed_dt:
        ctx["proposed_dt"] = turn.proposed_dt.isoformat()
    if turn.is_external:
        ctx["is_external"] = True
    elif ctx.get("is_external") and not ctx.get("location_area") and not turn.is_external:
        # Claude re-assessed as internal (e.g. user said "it's at the office").
        # Trust the correction since the full conversation history was passed.
        ctx["is_external"] = False
    if turn.location_area:
        ctx["location_area"] = turn.location_area
    ctx["is_vip"] = ctx.get("is_vip", False) or turn.is_vip
    ctx["is_urgent"] = ctx.get("is_urgent", False) or turn.is_urgent

    # Determine which fields are still missing
    required = ["organizer_name", "purpose", "duration_mins", "proposed_dt"]
    if ctx.get("is_external"):
        required.append("location_area")
    missing = [f for f in required if not ctx.get(f)]

    # All required fields collected → proceed to availability check.
    # Do this BEFORE the intent check: Claude occasionally misclassifies intent as "other"
    # even when it has extracted every field, which would cause a premature reply and no booking.
    if not missing and turn.intent != "cancel":
        logger.debug(
            "All fields collected (intent=%s), proceeding to availability check. ctx=%s",
            turn.intent, {k: v for k, v in ctx.items() if k != "history_json"},
        )
        return await _check_and_proceed(update, context, chat_id, ctx, history)

    # Explicit cancellation
    if turn.intent == "cancel":
        meeting = None
        meeting_id = ctx.get("meeting_id")
        if meeting_id:
            meeting = await meet_db.get_meeting(meeting_id)
            if meeting and meeting.get("status") != "confirmed":
                meeting = None

        if not meeting:
            meeting = await meet_db.get_latest_confirmed_meeting(chat_id)

        if meeting:
            cal_uid = meeting.get("calendar_uid")
            if cal_uid:
                await delete_event(cal_uid)
            await meet_db.update_meeting(meeting["id"], status="cancelled")
            start_dt = datetime.fromisoformat(meeting["start_dt"]).astimezone(HKT)
            local_start = start_dt.strftime("%A %d %B at %H:%M HKT")
            reply_msg = f"Done — your meeting on {local_start} has been cancelled."
        else:
            reply_msg = "No problem — feel free to message me whenever you'd like to schedule a meeting."

        await update.message.reply_text(reply_msg, parse_mode=ParseMode.HTML)
        await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))
        return ConversationHandler.END

    # When the user is in SUGGESTING_ALTERNATIVES and types a free-text message
    # (instead of clicking a button), keep them in that state rather than dropping to
    # GATHERING_INFO. This prevents Claude's conversational reply from being shown
    # without an actual calendar check (e.g. "how about 10am?" generating "I've
    # updated your request…" without ever calling check_slot).
    if state == "SUGGESTING_ALTERNATIVES":
        # If Claude understood a new time but didn't extract it via the structured tool,
        # show Claude's reply AND prompt the user to be specific so the next message
        # triggers a proper availability check.
        if turn.reply:
            await update.message.reply_text(_md_to_html(turn.reply), parse_mode=ParseMode.HTML)
        await update.message.reply_text(
            "Please tap one of the slot buttons above, or tell me a specific date and time "
            "(e.g. <b>10am tomorrow</b> or <b>Tuesday 3pm</b>) so I can check availability for you.",
            parse_mode=ParseMode.HTML,
        )
        await conv_db.upsert_conversation(chat_id, "SUGGESTING_ALTERNATIVES", ctx, history)
        return SUGGESTING_ALTERNATIVES

    # Not a scheduling intent and fields still missing — just reply conversationally
    if turn.intent not in ("schedule_request", "reschedule"):
        reply = _md_to_html(turn.reply or "How can I help you schedule a meeting?")
        await update.message.reply_text(reply, parse_mode=ParseMode.HTML)
        await conv_db.upsert_conversation(chat_id, "GATHERING_INFO", ctx, history)
        return GATHERING_INFO

    # Scheduling intent but still missing required fields — ask for the next one
    if turn.reply and turn.reply_type in ("ask_missing_info", "clarify_ambiguous"):
        reply = _md_to_html(turn.reply)
    else:
        field_label = missing[0].replace("_", " ")
        reply = f"Could you please provide the <b>{field_label}</b>?"
    await update.message.reply_text(reply, parse_mode=ParseMode.HTML)
    await conv_db.upsert_conversation(chat_id, "GATHERING_INFO", ctx, history)
    return GATHERING_INFO


async def _check_and_proceed(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    ctx: dict,
    history: list[dict],
) -> int:
    start_dt = datetime.fromisoformat(ctx["proposed_dt"])
    duration_mins = ctx["duration_mins"]
    is_external = ctx.get("is_external", False)
    is_vip = ctx.get("is_vip", False)
    is_urgent = ctx.get("is_urgent", False)
    location_area = ctx.get("location_area")

    # For external meetings, fetch travel time upfront so check_slot can enforce the buffer.
    travel_mins = 0
    settings = context_settings()
    if is_external and location_area and settings and settings.google_maps_api_key:
        travel_mins = await get_travel_minutes(
            settings.office_address, location_area, settings.google_maps_api_key
        ) or 0

    result = await check_slot(
        start_dt=start_dt,
        duration_mins=duration_mins,
        is_external=is_external,
        is_vip=is_vip,
        is_urgent=is_urgent,
        travel_mins=travel_mins,
    )

    # Notify requesters whose meetings were auto-cancelled because Simon deleted the
    # calendar event (e.g. to make room for a VIP meeting).
    for displaced in result.get("displaced_meetings", []):
        requester = displaced.get("requester_chat_id")
        if not requester:
            continue
        start_local = datetime.fromisoformat(displaced["start_dt"]).astimezone(HKT).strftime("%A %d %B at %H:%M HKT")
        owner_name = (context_settings().owner_name if context_settings() else None) or "Simon"
        try:
            await context.bot.send_message(
                chat_id=requester,
                text=(
                    f"Your meeting on {start_local} has been cancelled as the time slot "
                    f"is no longer available. Please contact {owner_name} to reschedule."
                ),
            )
        except Exception:
            logger.exception("Failed to notify displaced requester %s", requester)

    # Calendar temporarily unreadable — don't risk a double-booking
    if "calendar_unavailable" in result["reasons"]:
        await update.message.reply_text(
            "Sorry, I'm having trouble reading the calendar right now. "
            "Please try again in a moment."
        )
        ctx.pop("proposed_dt", None)
        await conv_db.upsert_conversation(chat_id, "GATHERING_INFO", ctx, history)
        return GATHERING_INFO

    # Slot is free, no special rules → auto-confirm
    if result["available"] and not result["requires_owner"]:
        return await _confirm_meeting(update, chat_id, ctx, history, start_dt, duration_mins, location_area, travel_mins)

    # Slot is free but requires owner approval
    if result["available"] and result["requires_owner"]:
        return await _request_owner_approval(
            update, chat_id, ctx, history, start_dt, duration_mins, location_area, result["reasons"], travel_mins=travel_mins
        )

    # Slot is physically blocked — no approval can override a time clash.
    if not result["available"]:
        ctx.pop("proposed_dt", None)
        if any(r in ("vip_conflict", "urgent_conflict") for r in result["reasons"]):
            # Notify Simon and show alternatives so the VIP can self-serve a nearby slot.
            alert_type = "vip_conflict" if "vip_conflict" in result["reasons"] else "urgent_conflict"
            owner_name = (context_settings().owner_name if context_settings() else None) or "Simon"
            await owner_notify.send_owner_alert(
                organizer_name=ctx["organizer_name"],
                purpose=ctx["purpose"],
                start_dt=start_dt.astimezone(timezone.utc).isoformat(),
                duration_mins=duration_mins,
                alert_type=alert_type,
                requester_chat_id=chat_id,
            )
            intro = (
                f"That time slot is not available. I've sent a message to <b>{owner_name}</b> "
                f"and he will get back to you as soon as possible. "
                f"In the meantime, here are some other available slots:"
            )
            return await _suggest_alternatives(
                update, chat_id, ctx, history,
                proposed_dt=start_dt,
                duration_mins=duration_mins,
                travel_mins=travel_mins,
                intro_text=intro,
            )
        # All other conflicts (including external meetings): offer alternatives.
        return await _suggest_alternatives(update, chat_id, ctx, history, proposed_dt=start_dt, duration_mins=duration_mins, travel_mins=travel_mins)

    return GATHERING_INFO


async def _confirm_meeting(
    update: Update,
    chat_id: int,
    ctx: dict,
    history: list[dict],
    start_dt: datetime,
    duration_mins: int,
    location_area: str | None,
    travel_mins: int = 0,
) -> int:

    end_dt = start_dt + timedelta(minutes=duration_mins)
    event_title = _event_title(ctx["purpose"], ctx["organizer_name"])
    event_location = _event_location(ctx.get("is_external", False), location_area)
    uid = await create_event(
        title=event_title,
        start_dt=start_dt,
        end_dt=end_dt,
        location=event_location,
        notes=ctx.get("purpose", ""),
    )

    meeting_id = await meet_db.create_meeting(
        requester_chat_id=chat_id,
        organizer_name=ctx["organizer_name"],
        purpose=ctx["purpose"],
        start_dt=start_dt.astimezone(timezone.utc).isoformat(),
        end_dt=end_dt.astimezone(timezone.utc).isoformat(),
        duration_mins=duration_mins,
        is_external=ctx.get("is_external", False),
        location_area=location_area,
        travel_mins=travel_mins,
    )
    if uid:
        await meet_db.update_meeting(meeting_id, calendar_uid=uid, status="confirmed")
    else:
        await meet_db.update_meeting(meeting_id, status="confirmed")

    await _schedule_location_followups(meeting_id, start_dt, ctx.get("is_external", False))

    local_start = start_dt.astimezone(HKT).strftime("%A %d %B %Y at %H:%M")
    await update.message.reply_text(
        f"Your meeting has been confirmed for {local_start} HKT "
        f"({duration_mins} min). We will follow up if exact location details are needed."
        if ctx.get("is_external")
        else f"Your meeting has been confirmed for {local_start} HKT ({duration_mins} min)."
    )
    await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))
    return ConversationHandler.END


async def _request_owner_approval(
    update: Update,
    chat_id: int,
    ctx: dict,
    history: list[dict],
    start_dt: datetime,
    duration_mins: int,
    location_area: str | None,
    reasons: list[str],
    travel_mins: int = 0,
) -> int:
    start_utc = start_dt.astimezone(timezone.utc).isoformat()
    end_dt = start_dt + timedelta(minutes=duration_mins)
    meeting_id = await meet_db.create_meeting(
        requester_chat_id=chat_id,
        organizer_name=ctx["organizer_name"],
        purpose=ctx["purpose"],
        start_dt=start_utc,
        end_dt=end_dt.astimezone(timezone.utc).isoformat(),
        duration_mins=duration_mins,
        is_external=ctx.get("is_external", False),
        location_area=location_area,
        travel_mins=travel_mins,
    )
    confirmation_id = await pend_db.create_confirmation(meeting_id, ",".join(reasons))
    ctx["meeting_id"] = meeting_id
    ctx["confirmation_id"] = confirmation_id

    msg_id = await owner_notify.send_owner_confirmation_request(
        confirmation_id=confirmation_id,
        meeting_id=meeting_id,
        organizer_name=ctx["organizer_name"],
        purpose=ctx["purpose"],
        start_dt=start_utc,
        duration_mins=duration_mins,
        reasons=reasons,
        requester_chat_id=chat_id,
        location_area=location_area,
    )
    if msg_id:
        await pend_db.set_owner_message_id(confirmation_id, msg_id)
    else:
        # Notification failed — cancel the pending records so they don't hang forever.
        logger.error("Owner notification failed for confirmation %d — cancelling meeting %d", confirmation_id, meeting_id)
        await meet_db.update_meeting(meeting_id, status="cancelled")
        await pend_db.resolve_confirmation(confirmation_id, "rejected")
        ctx.pop("meeting_id", None)
        ctx.pop("confirmation_id", None)
        await update.message.reply_text(
            "Sorry, I was unable to reach the approver right now. "
            "Please try submitting your request again in a few minutes."
        )
        await conv_db.upsert_conversation(chat_id, "GATHERING_INFO", ctx, history)
        return GATHERING_INFO

    owner_name = (context_settings().owner_name if context_settings() else None) or "Simon"
    await update.message.reply_text(
        f"Your request has been forwarded to {owner_name} for approval. "
        "You will be notified once a decision is made."
    )
    await conv_db.upsert_conversation(chat_id, "AWAITING_OWNER_DECISION", ctx, history)
    return AWAITING_OWNER_DECISION


async def _suggest_alternatives(
    update: Update,
    chat_id: int,
    ctx: dict,
    history: list[dict],
    proposed_dt: datetime,
    duration_mins: int,
    travel_mins: int = 0,
    intro_text: str | None = None,
) -> int:
    slots = await find_next_available_slots(proposed_dt, duration_mins, max_results=5, travel_mins=travel_mins)
    if not slots:
        await update.message.reply_text(
            "That time is not available and I couldn't find a free slot nearby. "
            "Please suggest a different date or time."
        )
        await conv_db.upsert_conversation(chat_id, "GATHERING_INFO", ctx, history)
        return GATHERING_INFO

    formatted = [s.astimezone(HKT).strftime("%a %d %b, %H:%M HKT") for s in slots]
    ctx["alternative_slots"] = [s.isoformat() for s in slots]

    await update.message.reply_text(
        intro_text or "That time is not available. Here are some alternative slots:",
        parse_mode=ParseMode.HTML,
        reply_markup=slot_choice_keyboard(formatted),
    )
    await conv_db.upsert_conversation(chat_id, "SUGGESTING_ALTERNATIVES", ctx, history)
    return SUGGESTING_ALTERNATIVES


async def handle_slot_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not update.effective_chat:
        return ConversationHandler.END
    try:
        await query.answer()
    except Exception:
        # Callback query expired (bot restarted after the button was sent) — ignore silently.
        return ConversationHandler.END
    chat_id = update.effective_chat.id

    data = query.data or ""
    if data == "slot:cancel":
        await query.edit_message_text("Cancelled. Feel free to propose a different time.")
        row = await conv_db.get_conversation(chat_id)
        name = json.loads(row["context_json"]).get("organizer_name") if row else None
        await conv_db.reset_conversation(chat_id, known_name=name)
        return ConversationHandler.END

    if data == "slot:other_date":
        await query.edit_message_text(
            "No problem — please suggest another date and time that works for you."
        )
        row = await conv_db.get_conversation(chat_id)
        if row:
            ctx = json.loads(row["context_json"])
            history = json.loads(row["history_json"])
            ctx.pop("proposed_dt", None)
            ctx.pop("alternative_slots", None)
            await conv_db.upsert_conversation(chat_id, "GATHERING_INFO", ctx, history)
        return GATHERING_INFO

    parts = data.split(":", 2)
    if len(parts) < 3:
        return ConversationHandler.END
    idx = int(parts[1])

    row = await conv_db.get_conversation(chat_id)
    if not row:
        return ConversationHandler.END
    ctx: dict = json.loads(row["context_json"])
    history: list[dict] = json.loads(row["history_json"])

    slots = ctx.get("alternative_slots", [])
    if idx >= len(slots):
        return ConversationHandler.END

    ctx["proposed_dt"] = slots[idx]
    await query.edit_message_text(f"Selected: {parts[2]}")
    return await _check_and_proceed(query, context, chat_id, ctx, history)


async def _schedule_location_followups(
    meeting_id: int, start_dt: datetime, is_external: bool
) -> None:
    if not is_external:
        return
    for delta_h, job_type in [
        (12, "location_t12h"),
        (3, "location_t3h"),
        (0.25, "location_t15m"),
    ]:
        trigger_dt = start_dt - timedelta(hours=delta_h)
        if trigger_dt > datetime.now(tz=timezone.utc):
            fu_id = await fu_db.create_follow_up(
                meeting_id=meeting_id,
                trigger_dt=trigger_dt.astimezone(timezone.utc).isoformat(),
                job_type=job_type,
            )
            from scheduler.jobs import schedule_location_followup
            await schedule_location_followup(fu_id, meeting_id, trigger_dt, job_type)


def _md_to_html(text: str) -> str:
    """Convert **markdown bold** to <b>HTML bold</b> so Telegram renders it correctly."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def _event_title(purpose: str, organizer_name: str) -> str:
    """Format: 'AI Discussion (Simon Tang)'"""
    clean = purpose.strip().rstrip(".")
    clean = clean[:1].upper() + clean[1:] if clean else "Meeting"
    return f"{clean} ({organizer_name})"


def _event_location(is_external: bool, location_area: str | None) -> str:
    if not is_external:
        return "Office"
    return location_area or "TBC"


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """List free time blocks for the next 7 business days."""
    if not update.message:
        return ConversationHandler.END

    today = datetime.now(tz=HKT).date()
    lines: list[str] = []
    found = 0
    d = today
    # Walk forward through calendar days until we've reported 7 business days.
    for _ in range(30):
        if found >= 7:
            break
        if not is_business_day(d):
            d += timedelta(days=1)
            continue
        blocks = await compute_free_blocks_for_day(d)
        label = d.strftime("%a %d %b")
        if blocks is None:
            lines.append(f"<b>{label}</b>: (calendar unavailable)")
        elif not blocks:
            lines.append(f"<b>{label}</b>: no available time slot")
        else:
            spans = ", ".join(
                f"{s.astimezone(HKT).strftime('%H:%M')}–{e.astimezone(HKT).strftime('%H:%M')}"
                for s, e in blocks
            )
            lines.append(f"<b>{label}</b>: {spans}")
        found += 1
        d += timedelta(days=1)

    body = "\n".join(lines) if lines else "No business days found in the next 30 days."
    owner_name = (context_settings().owner_name if context_settings() else None) or "Simon"
    await update.message.reply_text(
        f"{owner_name}'s available time slots over the next 7 business days:\n\n{body}",
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


# Module-level settings accessor (injected at startup)
_settings = None


def set_settings(s) -> None:
    global _settings
    _settings = s


def context_settings():
    return _settings
