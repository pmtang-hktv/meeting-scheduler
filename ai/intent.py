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


# Month name / abbreviation → month number. Used by the deterministic explicit-date
# parser below.
_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# One left-to-right pass tokenises a message into month names, day ranges ("6-8",
# "6 to 8"), and bare numbers. Range is tried before num so "6-8" is one token.
_DATE_TOKEN_RE = re.compile(
    r"(?P<range>\d{1,2}\s*(?:-|–|—|to|through|thru|until|til|till)\s*\d{1,2})"
    r"|(?P<month>\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:t)?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b)"
    r"|(?P<num>\d{1,4})",
    re.IGNORECASE,
)
_RANGE_SPLIT_RE = re.compile(r"-|–|—|to|through|thru|until|til|till", re.IGNORECASE)


def parse_explicit_dates(text: str, today: "date | None" = None) -> list[dict]:
    """Deterministically extract explicit month-name dates from a message.

    Handles the terse multi-date lists Claude tends to mis-read, e.g.
    "Jul 3, 6,10 13 in 2026", "6-8 Jul", "Jul 3 and Jul 6", "and Jul 3 and Jul 6".
    Returns day-off segments [{"start": iso, "end": iso|None, "half": None}] sorted
    by date. A day number is attached to the month immediately following it (day-first,
    e.g. "6-8 Jul") otherwise to the most recent month seen (month-first). A 4-digit
    1900–2100 number is treated as an explicit year applied to every date.

    Only engages when at least one month name is present, so relative expressions
    ("next Friday", "tomorrow") and slash/locale dates are left for the LLM. Returns []
    when nothing explicit is found, signalling the caller to fall back to Claude.
    """
    from datetime import date as _date
    today = today or datetime.now(tz=HKT).date()

    # Strip ordinal suffixes ("3rd" → "3") so day numbers tokenise cleanly.
    cleaned = re.sub(r"(\d{1,2})(?:st|nd|rd|th)\b", r"\1", text, flags=re.IGNORECASE)

    tokens: list[tuple[str, str]] = [
        (m.lastgroup, m.group(m.lastgroup)) for m in _DATE_TOKEN_RE.finditer(cleaned)
    ]
    if not any(kind == "month" for kind, _ in tokens):
        return []

    year: int | None = None
    for kind, val in tokens:
        if kind == "num" and len(val) == 4 and 1900 <= int(val) <= 2100:
            year = int(val)
            break

    def _day_range(val: str) -> tuple[int, int] | None:
        if "-" in val or "–" in val or "—" in val or re.search(r"[a-z]", val, re.IGNORECASE):
            parts = [p for p in _RANGE_SPLIT_RE.split(val) if p.strip()]
            if len(parts) == 2:
                a, b = int(parts[0]), int(parts[1])
                return (a, b) if a <= b else (b, a)
            return None
        n = int(val)
        return (n, n)

    def _resolve(month: int, day: int) -> "_date | None":
        yr = year or today.year
        try:
            d = _date(yr, month, day)
        except ValueError:
            return None
        # Without an explicit year, roll a past date into next year.
        if year is None and d < today:
            try:
                d = _date(yr + 1, month, day)
            except ValueError:
                return None
        return d

    entries: list[tuple[_date, _date]] = []
    current_month: int | None = None
    pending: list[tuple[int, int]] = []  # day-ranges seen before their month

    def _emit(month: int, span: tuple[int, int]) -> None:
        s = _resolve(month, span[0])
        e = _resolve(month, span[1])
        if s and e:
            entries.append((s, e if e >= s else s))

    for i, (kind, val) in enumerate(tokens):
        if kind == "month":
            current_month = _MONTHS.get(val.lower())
            if current_month:
                for span in pending:
                    _emit(current_month, span)
            pending = []
            continue
        if kind == "num" and len(val) == 4 and 1900 <= int(val) <= 2100:
            continue  # already captured as the year
        span = _day_range(val)
        if span is None or not (1 <= span[0] <= 31 and 1 <= span[1] <= 31):
            continue
        # A day followed by a month but NOT preceded by one is day-first ("6-8 Jul",
        # "3 Jul") — attach it to that upcoming month. A day sandwiched after its own
        # month ("Jul 3 and Aug 6" → 3 belongs to Jul) stays month-first.
        prev = tokens[i - 1] if i > 0 else None
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt and nxt[0] == "month" and not (prev and prev[0] == "month"):
            target = _MONTHS.get(nxt[1].lower())
            if target:
                _emit(target, span)
                continue
        if current_month:
            _emit(current_month, span)
        else:
            pending.append(span)

    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for s, e in sorted(entries):
        key = (s.isoformat(), e.isoformat())
        if key in seen:
            continue
        seen.add(key)
        out.append({"start": s.isoformat(), "end": None if e == s else e.isoformat(), "half": None})
    return out


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
