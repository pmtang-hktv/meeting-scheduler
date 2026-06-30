from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from ai.claude_client import run_conversation
from ai.tool_executor import ToolResults

HKT = ZoneInfo("Asia/Hong_Kong")
logger = logging.getLogger(__name__)

# Weekday name/abbreviation → Python weekday() index (Monday=0). Used to sanity-check
# the LLM's resolved date against a weekday the user named explicitly.
_WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "weds": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def parse_duration_mins(text: str) -> int | None:
    """Parse a free-text duration into minutes, e.g. '1 hour'→60, '45'→45, '1.5 hrs'→90.

    Deterministic so a bare duration like '1 hour' never depends on the LLM correctly
    classifying intent. Returns None if no duration can be confidently extracted.
    """
    if not text:
        return None
    s = " " + text.strip().lower() + " "

    # Common spoken phrases first.
    if re.search(r"\b(an?\s+)?hours?\s+and\s+a\s+half\b", s):
        return 90
    if re.search(r"\bhalf\s+an?\s+hours?\b|\bhalf\s+hours?\b", s):
        return 30

    total = 0.0
    matched = False

    # Hours: "1 hour", "1.5 hrs", "2h", or "an/one hour".
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", s)
    if m:
        total += float(m.group(1)) * 60
        matched = True
    elif re.search(r"\b(an?|one)\s+(?:hours?|hrs?|h)\b", s):
        total += 60
        matched = True

    # Minutes: "30 min", "30 minutes", "30m".
    m = re.search(r"(\d+)\s*(?:minutes?|mins?|m)\b", s)
    if m:
        total += int(m.group(1))
        matched = True

    if not matched:
        # A bare number on its own means minutes (e.g. the user typed just "45").
        m = re.fullmatch(r"\s*(\d+)\s*", s)
        if m:
            return int(m.group(1))
        return None

    mins = int(round(total))
    return mins if mins > 0 else None


def _named_weekday(text: str) -> int | None:
    """Return the weekday index if the message names exactly one weekday, else None.

    If the user lists several different weekdays (ambiguous), we don't try to correct.
    """
    found = {wd for word, wd in _WEEKDAYS.items() if re.search(rf"\b{word}\b", text, re.IGNORECASE)}
    return next(iter(found)) if len(found) == 1 else None


def _align_to_named_weekday(dt: datetime, text: str) -> datetime:
    """Guard against the LLM resolving a date to the wrong weekday.

    When the user explicitly names a weekday (e.g. 'Tue') but the resolved date lands on
    a different one, snap to the nearest date with the named weekday (within ±3 days, so
    a deliberate week offset like 'next Tuesday' is preserved). Never moves into the past.
    """
    target = _named_weekday(text)
    if target is None or dt.weekday() == target:
        return dt
    diff = (target - dt.weekday()) % 7  # 0..6 forward
    if diff > 3:
        diff -= 7  # closer going backward
    corrected = dt + timedelta(days=diff)
    if corrected.date() < datetime.now(tz=HKT).date():
        corrected += timedelta(days=7)
    logger.info(
        "Corrected proposed_dt weekday: %s → %s (user named %s)",
        dt.isoformat(), corrected.isoformat(), target,
    )
    return corrected


@dataclass
class ConversationTurn:
    intent: str
    organizer_name: str | None
    purpose: str | None
    duration_mins: int | None
    proposed_dt: datetime | None
    is_external: bool
    location_area: str | None
    is_vip: bool
    is_urgent: bool
    missing_fields: list[str]
    reply: str | None
    reply_type: str | None
    day_off_dates: list | None = None
    day_off_person: str | None = None


def _parse_dt(dt_str: str) -> datetime | None:
    """Parse ISO8601 datetime robustly — handles Python 3.9 fromisoformat limitations."""
    if not dt_str:
        return None
    # Normalise Z → +00:00
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    # Normalise +HHMM without colon → +HH:MM
    dt_str = re.sub(r"([+-])(\d{2})(\d{2})$", r"\1\2:\3", dt_str)
    try:
        return datetime.fromisoformat(dt_str).astimezone(HKT)
    except (ValueError, TypeError):
        logger.warning("Could not parse proposed_dt: %r", dt_str)
        return None


async def process_turn(history: list[dict], new_message: str) -> ConversationTurn:
    """Run a conversation turn through Claude and return structured results."""
    messages = list(history) + [{"role": "user", "content": new_message}]
    results: ToolResults = await run_conversation(messages)

    proposed_dt = _parse_dt(results.proposed_dt) if results.proposed_dt else None
    if proposed_dt is not None:
        proposed_dt = _align_to_named_weekday(proposed_dt, new_message)

    # Prefer request_missing_info.question over generate_reply.reply when asking for a field
    if results.missing_field_asked and results.missing_field_question:
        reply = results.missing_field_question
        reply_type = "ask_missing_info"
    else:
        reply = results.reply
        reply_type = results.reply_type

    logger.debug(
        "process_turn: intent=%s proposed_dt_raw=%r proposed_dt=%s missing=%s reply_type=%s",
        results.intent, results.proposed_dt, proposed_dt, results.missing_fields, reply_type,
    )

    return ConversationTurn(
        intent=results.intent or "other",
        organizer_name=results.organizer_name,
        purpose=results.purpose,
        duration_mins=results.duration_mins,
        proposed_dt=proposed_dt,
        is_external=results.is_external,
        location_area=results.location_area,
        is_vip=results.is_vip,
        is_urgent=results.is_urgent,
        missing_fields=results.missing_fields,
        reply=reply,
        reply_type=reply_type,
        day_off_dates=results.day_off_dates,
        day_off_person=results.day_off_person,
    )
