"""Day-off / leave flow: a team member marks (or removes) their own day off,
which is written to the owner's calendar as an informational all-day event.

Entry points:
- Natural language ("I'm off next Friday") → colleague delegates via start_from_intent.
- /menu → 🌴 Mark a day off button → handle_dayoff_callback("menu:dayoff").

Typed replies during collection are routed back here from colleague.handle_message
by the persisted DB state (AWAITING_DAYOFF_DATE / _NAME / _CONFIRM), same pattern
as the edit flow.
"""
from __future__ import annotations
import html
import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes, ConversationHandler

from ai.intent import process_turn, parse_explicit_dates
from bot.keyboards import (
    cancel_dayoff_keyboard,
    dayoff_confirm_keyboard,
    dayoff_del_confirm_keyboard,
    dayoff_list_keyboard,
)
from calendar_integration import calendar_service as cal_svc
from db import conversations as conv_db, day_offs as do_db
from notifications import owner_notify

logger = logging.getLogger(__name__)
HKT = ZoneInfo("Asia/Hong_Kong")

_ASK_DATE = (
    "Which day(s) will you be off? e.g. <b>next Friday</b> or <b>6–8 Jul</b>."
)


def _half_suffix(half: str | None) -> str:
    return {"am": " (AM)", "pm": " (PM)"}.get(half or "", "")


def _format_range(start: str, end: str | None, half: str | None = None) -> str:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end) if end else s
    if e <= s:
        return s.strftime("%a %d %b %Y") + _half_suffix(half)
    return f"{s.strftime('%a %d %b')} – {e.strftime('%a %d %b %Y')}"


def _format_segments(pending: list[dict]) -> str:
    return ", ".join(_format_range(seg["start"], seg["end"], seg.get("half")) for seg in pending)


def _all_single_day(pending: list[dict]) -> bool:
    return bool(pending) and all(seg["end"] == seg["start"] for seg in pending)


def _normalize(segments) -> list[dict]:
    """Validate, drop past entries, clip a partly-past range to today, and sort.
    Returns a list of {"start": iso, "end": iso} with inclusive end."""
    today = datetime.now(tz=HKT).date()
    out: list[tuple[date, date, str | None]] = []
    for seg in segments or []:
        try:
            sd = date.fromisoformat(seg["start"])
        except (KeyError, TypeError, ValueError):
            continue
        ed = None
        if seg.get("end"):
            try:
                ed = date.fromisoformat(seg["end"])
            except (TypeError, ValueError):
                ed = None
        if ed is None or ed < sd:
            ed = sd
        if ed < today:          # whole entry already passed
            continue
        if sd < today:          # started in the past but still ongoing → clip
            sd = today
        half = seg.get("half") if seg.get("half") in ("am", "pm") else None
        # A half day only makes sense for a single day; drop it on a multi-day span.
        if ed != sd:
            half = None
        out.append((sd, ed, half))
    out.sort(key=lambda t: (t[0], t[1]))
    return [{"start": s.isoformat(), "end": e.isoformat(), "half": h} for s, e, h in out]


def _segments_from_turn(turn) -> list:
    segs = list(turn.day_off_dates or [])
    if not segs and turn.proposed_dt:
        segs = [{"start": turn.proposed_dt.date().isoformat(), "end": None}]
    return segs


def _merge_explicit(text: str, llm_segments: list) -> list:
    """Combine deterministically-parsed explicit dates with the LLM's segments.

    Claude (Haiku) reliably mis-reads terse date lists like "Jul 3, 6,10 13" or a
    fragment starting with "and", silently dropping dates. We re-derive any explicit
    month-name dates ourselves and treat them as authoritative, while keeping LLM
    segments the parser can't see (relative dates like "next Friday", and any half-day
    it detected on a matching single day). Falls back to the LLM verbatim when the
    message has no explicit month-name date.
    """
    explicit = parse_explicit_dates(text)
    if not explicit:
        return llm_segments

    def _covers(seg: dict, iso: str) -> bool:
        start = seg["start"]
        end = seg.get("end") or start
        return start <= iso <= end

    # Preserve a half-day the LLM found on a single day the parser also produced.
    for seg in explicit:
        if seg["end"] is None:
            for other in llm_segments:
                if other.get("start") == seg["start"] and not other.get("end") and other.get("half"):
                    seg["half"] = other["half"]
                    break

    merged = list(explicit)
    for other in llm_segments:
        start = other.get("start")
        if start and not any(_covers(seg, start) for seg in explicit):
            merged.append(other)
    return merged


# --------------------------------------------------------------------------- #
# Entry from colleague.handle_message                                          #
# --------------------------------------------------------------------------- #

async def start_from_intent(update: Update, chat_id: int, ctx: dict, history: list[dict], turn) -> int:
    name = ctx.get("organizer_name") or turn.day_off_person or turn.organizer_name
    text = update.message.text if update.message else ""
    segments = _merge_explicit(text or "", _segments_from_turn(turn))
    return await _offer(update, chat_id, ctx, history, segments, name)


async def handle_followup(update: Update, chat_id: int, ctx: dict, history: list[dict], text: str, state: str) -> int:
    if state == "AWAITING_DAYOFF_CONFIRM":
        pending = ctx.get("pending_dayoff_segments")
        name = ctx.get("organizer_name")
        if pending and name:
            await update.message.reply_text(
                f"Please tap a button below: mark <b>{html.escape(name)}</b> off on "
                f"<b>{_format_segments(pending)}</b>?",
                parse_mode=ParseMode.HTML,
                reply_markup=dayoff_confirm_keyboard(offer_halves=_all_single_day(pending)),
            )
            return ConversationHandler.END
        return await _offer(update, chat_id, ctx, history, pending or [], name)

    if state == "AWAITING_DAYOFF_NAME":
        name = text.strip()
        if not name:
            await update.message.reply_text("Please type your name.", reply_markup=cancel_dayoff_keyboard())
            return ConversationHandler.END
        return await _offer(update, chat_id, ctx, history, ctx.get("pending_dayoff_segments") or [], name)

    # AWAITING_DAYOFF_DATE — re-parse the typed date(s) with leave context for reliability.
    parsed = await process_turn([], f"I am taking a day off / on leave on these date(s): {text}")
    segments = _merge_explicit(text, _segments_from_turn(parsed))
    return await _offer(update, chat_id, ctx, history, segments, ctx.get("organizer_name"))


# --------------------------------------------------------------------------- #
# Core: collect missing pieces, then offer a confirmation                      #
# --------------------------------------------------------------------------- #

async def _offer(update: Update, chat_id: int, ctx: dict, history: list[dict],
                 segments: list, name: str | None) -> int:
    pending = _normalize(segments)
    if not pending:
        ctx.pop("pending_dayoff_segments", None)
        await update.message.reply_text(
            _ASK_DATE if not segments else
            "Those dates have already passed (or I couldn't read them). Please give a future date — e.g. <b>next Friday</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_dayoff_keyboard(),
        )
        await conv_db.upsert_conversation(chat_id, "AWAITING_DAYOFF_DATE", ctx, history)
        return ConversationHandler.END

    ctx["pending_dayoff_segments"] = pending

    if not name:
        await update.message.reply_text(
            "Got it. What's your <b>name</b>? (so I can label the day off on Simon's calendar)",
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_dayoff_keyboard(),
        )
        await conv_db.upsert_conversation(chat_id, "AWAITING_DAYOFF_NAME", ctx, history)
        return ConversationHandler.END

    ctx["organizer_name"] = name
    await update.message.reply_text(
        f"Mark <b>{html.escape(name)}</b> as off on <b>{_format_segments(pending)}</b>? "
        f"This adds an all-day event to Simon's calendar and notifies him.",
        parse_mode=ParseMode.HTML,
        reply_markup=dayoff_confirm_keyboard(offer_halves=_all_single_day(pending)),
    )
    await conv_db.upsert_conversation(chat_id, "AWAITING_DAYOFF_CONFIRM", ctx, history)
    return ConversationHandler.END


# --------------------------------------------------------------------------- #
# Callback router (buttons)                                                     #
# --------------------------------------------------------------------------- #

async def handle_dayoff_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_chat:
        return
    try:
        await query.answer()
    except Exception:
        return
    chat_id = update.effective_chat.id
    data = query.data or ""
    row = await conv_db.get_conversation(chat_id)
    ctx: dict = json.loads(row["context_json"]) if row else {}
    history: list[dict] = json.loads(row["history_json"]) if row else []

    try:
        if data == "menu:dayoff":
            await _show_dayoff_menu(query, chat_id, ctx, history)
        elif data == "dayoff:add":
            await conv_db.upsert_conversation(chat_id, "AWAITING_DAYOFF_DATE", ctx, history)
            await query.edit_message_text(_ASK_DATE, parse_mode=ParseMode.HTML)
        elif data == "dayoff:yes" or data.startswith("dayoff:yes:"):
            half = data.split(":")[2] if data.count(":") == 2 else None
            await _create_day_off(query, chat_id, ctx, half_override=half if half in ("am", "pm") else None)
        elif data == "dayoff:no":
            await query.edit_message_text("Okay — nothing changed. Type /menu anytime.")
            await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))
        elif data.startswith("dayoffdelyes:"):
            await _do_delete(query, chat_id, ctx, int(data.split(":", 1)[1]))
        elif data.startswith("dayoffdel:"):
            await _confirm_delete(query, chat_id, ctx, history, int(data.split(":", 1)[1]))
    except BadRequest as e:
        # Re-tapping a button re-renders an identical message; Telegram rejects that with
        # "Message is not modified" — harmless, so swallow it instead of surfacing an error.
        if "not modified" not in str(e).lower():
            raise


async def _show_dayoff_menu(query, chat_id: int, ctx: dict, history: list[dict]) -> None:
    offs = await do_db.get_upcoming_day_offs(chat_id)
    if not offs:
        await conv_db.upsert_conversation(chat_id, "AWAITING_DAYOFF_DATE", ctx, history)
        await query.edit_message_text(
            "You have no upcoming days off recorded.\n\n" + _ASK_DATE,
            parse_mode=ParseMode.HTML,
        )
        return
    items = [(d, _format_range(d["start_date"], d["end_date"], d.get("half_day"))) for d in offs]
    await conv_db.upsert_conversation(chat_id, "DAYOFF_MENU", ctx, history)
    await query.edit_message_text(
        "Your upcoming days off — tap 🗑 to remove one, or add another:",
        reply_markup=dayoff_list_keyboard(items),
    )


async def _confirm_delete(query, chat_id: int, ctx: dict, history: list[dict], day_off_id: int) -> None:
    d = await do_db.get_day_off(day_off_id)
    if not _owns(d, chat_id):
        await query.edit_message_text("Sorry, I can't find that day off any more.")
        return
    label = _format_range(d["start_date"], d["end_date"], d.get("half_day"))
    await conv_db.upsert_conversation(chat_id, "DAYOFF_MENU", ctx, history)
    await query.edit_message_text(
        f"Remove the day off for <b>{html.escape(d['person_name'])}</b> on <b>{label}</b>?",
        parse_mode=ParseMode.HTML,
        reply_markup=dayoff_del_confirm_keyboard(day_off_id),
    )


async def _do_delete(query, chat_id: int, ctx: dict, day_off_id: int) -> None:
    d = await do_db.get_day_off(day_off_id)
    if not _owns(d, chat_id):
        await query.edit_message_text("Sorry, I can't find that day off any more.")
        return
    if d.get("calendar_uid"):
        await cal_svc.delete_event(d["calendar_uid"])
    await do_db.cancel_day_off(day_off_id)
    label = _format_range(d["start_date"], d["end_date"], d.get("half_day"))
    ref = do_db.day_off_ref(day_off_id)
    await query.edit_message_text(
        f"🗑 Removed day off <b>{ref}</b> ({html.escape(d['person_name'])} — {label}).",
        parse_mode=ParseMode.HTML,
    )
    await owner_notify.send_owner_message(f"{d['person_name']} removed their day off on {label}.")
    await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))


async def _create_day_off(query, chat_id: int, ctx: dict, half_override: str | None = None) -> None:
    name = ctx.get("organizer_name")
    pending = ctx.get("pending_dayoff_segments") or []
    if not (name and pending):
        await query.edit_message_text("Something went wrong — please type /menu and try again.")
        await conv_db.reset_conversation(chat_id, known_name=name)
        return

    created: list[tuple[int, str, str, str | None]] = []
    for seg in pending:
        start, end = seg["start"], seg["end"]
        # A tapped Morning/Afternoon button overrides any half already on the entry;
        # a half only applies to a single day, so ignore it on a multi-day span.
        half = half_override if half_override is not None else seg.get("half")
        if end != start:
            half = None
        title = f"Day Off{_half_suffix(half)} — {name}"
        end_exclusive = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        day_off_id = await do_db.create_day_off(chat_id, name, start, end, half_day=half)
        uid = await cal_svc.create_all_day_event(title, start, end_exclusive, notes="Marked via scheduling bot")
        if uid:
            await do_db.set_calendar_uid(day_off_id, uid)
            created.append((day_off_id, start, end, half))
        else:
            await do_db.cancel_day_off(day_off_id)

    if created:
        lines = "\n".join(
            f"• {_format_range(s, e, h)} (<b>{do_db.day_off_ref(i)}</b>)" for i, s, e, h in created
        )
        await query.edit_message_text(
            f"✅ Day off recorded for <b>{html.escape(name)}</b>:\n{lines}\n\n"
            f"Type /menu → 🌴 to view or remove.",
            parse_mode=ParseMode.HTML,
        )
        summary = ", ".join(_format_range(s, e, h) for _, s, e, h in created)
        await owner_notify.send_owner_message(f"{name} marked {summary} as day(s) off.")
    else:
        await query.edit_message_text(
            "Sorry, I couldn't add the calendar event(s) just now. Please try again in a moment."
        )
    ctx.pop("pending_dayoff_segments", None)
    await conv_db.reset_conversation(chat_id, known_name=name)


def _owns(day_off: dict | None, chat_id: int) -> bool:
    return bool(
        day_off
        and day_off.get("requester_chat_id") == chat_id
        and day_off.get("status") == "confirmed"
    )
