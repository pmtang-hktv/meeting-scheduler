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
from telegram.ext import ContextTypes, ConversationHandler

from ai.intent import process_turn
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


def _format_range(start: str, end: str | None) -> str:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end) if end else s
    if e <= s:
        return s.strftime("%a %d %b %Y")
    return f"{s.strftime('%a %d %b')} – {e.strftime('%a %d %b %Y')}"


# --------------------------------------------------------------------------- #
# Entry from colleague.handle_message                                          #
# --------------------------------------------------------------------------- #

async def start_from_intent(update: Update, chat_id: int, ctx: dict, history: list[dict], turn) -> int:
    start = turn.day_off_start
    if not start and turn.proposed_dt:
        start = turn.proposed_dt.date().isoformat()
    end = turn.day_off_end
    name = ctx.get("organizer_name") or turn.day_off_person or turn.organizer_name
    return await _offer(update, chat_id, ctx, history, start, end, name)


async def handle_followup(update: Update, chat_id: int, ctx: dict, history: list[dict], text: str, state: str) -> int:
    if state == "AWAITING_DAYOFF_CONFIRM":
        start = ctx.get("pending_dayoff_start")
        end = ctx.get("pending_dayoff_end")
        name = ctx.get("organizer_name")
        if start and name:
            label = _format_range(start, end)
            await update.message.reply_text(
                f"Please tap a button below: mark <b>{html.escape(name)}</b> off on <b>{label}</b>?",
                parse_mode=ParseMode.HTML,
                reply_markup=dayoff_confirm_keyboard(),
            )
            return ConversationHandler.END
        return await _offer(update, chat_id, ctx, history, start, end, name)

    if state == "AWAITING_DAYOFF_NAME":
        name = text.strip()
        if not name:
            await update.message.reply_text("Please type your name.", reply_markup=cancel_dayoff_keyboard())
            return ConversationHandler.END
        return await _offer(
            update, chat_id, ctx, history,
            ctx.get("pending_dayoff_start"), ctx.get("pending_dayoff_end"), name,
        )

    # AWAITING_DAYOFF_DATE — re-parse the typed date(s) with leave context for reliability.
    parsed = await process_turn([], f"I am taking a day off / on leave on these date(s): {text}")
    start = parsed.day_off_start
    if not start and parsed.proposed_dt:
        start = parsed.proposed_dt.date().isoformat()
    return await _offer(update, chat_id, ctx, history, start, parsed.day_off_end, ctx.get("organizer_name"))


# --------------------------------------------------------------------------- #
# Core: collect missing pieces, then offer a confirmation                      #
# --------------------------------------------------------------------------- #

async def _offer(update: Update, chat_id: int, ctx: dict, history: list[dict],
                 start: str | None, end: str | None, name: str | None) -> int:
    if not start:
        await update.message.reply_text(_ASK_DATE, parse_mode=ParseMode.HTML, reply_markup=cancel_dayoff_keyboard())
        await conv_db.upsert_conversation(chat_id, "AWAITING_DAYOFF_DATE", ctx, history)
        return ConversationHandler.END

    try:
        start_d = date.fromisoformat(start)
    except ValueError:
        start_d = None
    if start_d is None or start_d < datetime.now(tz=HKT).date():
        ctx.pop("pending_dayoff_start", None)
        ctx.pop("pending_dayoff_end", None)
        await update.message.reply_text(
            "That date has already passed (or I couldn't read it). Please give a future date — e.g. <b>next Friday</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_dayoff_keyboard(),
        )
        await conv_db.upsert_conversation(chat_id, "AWAITING_DAYOFF_DATE", ctx, history)
        return ConversationHandler.END

    end_d = None
    if end:
        try:
            end_d = date.fromisoformat(end)
        except ValueError:
            end_d = None
    if end_d and end_d < start_d:
        end_d = None
    end_iso = (end_d or start_d).isoformat()

    ctx["pending_dayoff_start"] = start_d.isoformat()
    ctx["pending_dayoff_end"] = end_iso

    if not name:
        await update.message.reply_text(
            "Got it. What's your <b>name</b>? (so I can label the day off on Simon's calendar)",
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_dayoff_keyboard(),
        )
        await conv_db.upsert_conversation(chat_id, "AWAITING_DAYOFF_NAME", ctx, history)
        return ConversationHandler.END

    ctx["organizer_name"] = name
    label = _format_range(start_d.isoformat(), end_iso)
    await update.message.reply_text(
        f"Mark <b>{html.escape(name)}</b> as off on <b>{label}</b>? "
        f"This adds an all-day event to Simon's calendar and notifies him.",
        parse_mode=ParseMode.HTML,
        reply_markup=dayoff_confirm_keyboard(),
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

    if data == "menu:dayoff":
        await _show_dayoff_menu(query, chat_id, ctx, history)
    elif data == "dayoff:add":
        await conv_db.upsert_conversation(chat_id, "AWAITING_DAYOFF_DATE", ctx, history)
        await query.edit_message_text(_ASK_DATE, parse_mode=ParseMode.HTML)
    elif data == "dayoff:yes":
        await _create_day_off(query, chat_id, ctx)
    elif data == "dayoff:no":
        await query.edit_message_text("Okay — nothing changed. Type /menu anytime.")
        await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))
    elif data.startswith("dayoffdelyes:"):
        await _do_delete(query, chat_id, ctx, int(data.split(":", 1)[1]))
    elif data.startswith("dayoffdel:"):
        await _confirm_delete(query, chat_id, ctx, history, int(data.split(":", 1)[1]))


async def _show_dayoff_menu(query, chat_id: int, ctx: dict, history: list[dict]) -> None:
    offs = await do_db.get_upcoming_day_offs(chat_id)
    if not offs:
        await conv_db.upsert_conversation(chat_id, "AWAITING_DAYOFF_DATE", ctx, history)
        await query.edit_message_text(
            "You have no upcoming days off recorded.\n\n" + _ASK_DATE,
            parse_mode=ParseMode.HTML,
        )
        return
    items = [(d, _format_range(d["start_date"], d["end_date"])) for d in offs]
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
    label = _format_range(d["start_date"], d["end_date"])
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
    label = _format_range(d["start_date"], d["end_date"])
    ref = do_db.day_off_ref(day_off_id)
    await query.edit_message_text(
        f"🗑 Removed day off <b>{ref}</b> ({html.escape(d['person_name'])} — {label}).",
        parse_mode=ParseMode.HTML,
    )
    await owner_notify.send_owner_message(f"{d['person_name']} removed their day off on {label}.")
    await conv_db.reset_conversation(chat_id, known_name=ctx.get("organizer_name"))


async def _create_day_off(query, chat_id: int, ctx: dict) -> None:
    name = ctx.get("organizer_name")
    start = ctx.get("pending_dayoff_start")
    end = ctx.get("pending_dayoff_end") or start
    if not (name and start):
        await query.edit_message_text("Something went wrong — please type /menu and try again.")
        await conv_db.reset_conversation(chat_id, known_name=name)
        return

    end_exclusive = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    title = f"Day Off — {name}"
    day_off_id = await do_db.create_day_off(chat_id, name, start, end)
    uid = await cal_svc.create_all_day_event(title, start, end_exclusive, notes="Marked via scheduling bot")
    label = _format_range(start, end)
    ref = do_db.day_off_ref(day_off_id)
    if uid:
        await do_db.set_calendar_uid(day_off_id, uid)
        await query.edit_message_text(
            f"✅ Day off recorded for <b>{html.escape(name)}</b> on <b>{label}</b>.\n"
            f"Reference <b>{ref}</b>. Type /menu → 🌴 to view or remove it.",
            parse_mode=ParseMode.HTML,
        )
        await owner_notify.send_owner_message(f"{name} marked {label} as a day off.")
    else:
        await do_db.cancel_day_off(day_off_id)
        await query.edit_message_text(
            "Sorry, I couldn't add the calendar event just now. Please try again in a moment."
        )
    for k in ("pending_dayoff_start", "pending_dayoff_end"):
        ctx.pop(k, None)
    await conv_db.reset_conversation(chat_id, known_name=name)


def _owns(day_off: dict | None, chat_id: int) -> bool:
    return bool(
        day_off
        and day_off.get("requester_chat_id") == chat_id
        and day_off.get("status") == "confirmed"
    )
