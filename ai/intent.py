from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from ai.claude_client import run_conversation
from ai.tool_executor import ToolResults

HKT = ZoneInfo("Asia/Hong_Kong")
logger = logging.getLogger(__name__)


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
    day_off_start: str | None = None
    day_off_end: str | None = None
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
        day_off_start=results.day_off_start,
        day_off_end=results.day_off_end,
        day_off_person=results.day_off_person,
    )
