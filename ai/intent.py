from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo
from ai.claude_client import run_conversation
from ai.tool_executor import ToolResults

HKT = ZoneInfo("Asia/Hong_Kong")


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


async def process_turn(history: list[dict], new_message: str) -> ConversationTurn:
    """Run a conversation turn through Claude and return structured results."""
    messages = list(history) + [{"role": "user", "content": new_message}]
    results: ToolResults = await run_conversation(messages)

    proposed_dt: datetime | None = None
    if results.proposed_dt:
        try:
            proposed_dt = datetime.fromisoformat(results.proposed_dt).astimezone(HKT)
        except ValueError:
            proposed_dt = None

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
        reply=results.reply or results.missing_field_question,
        reply_type=results.reply_type or (
            "ask_missing_info" if results.missing_field_asked else "general"
        ),
    )
