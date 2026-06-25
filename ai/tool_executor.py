from __future__ import annotations
from typing import Any


class ToolResults:
    def __init__(self) -> None:
        self.intent: str | None = None
        self.intent_confidence: str | None = None
        self.organizer_name: str | None = None
        self.purpose: str | None = None
        self.duration_mins: int | None = None
        self.proposed_dt: str | None = None
        self.is_external: bool = False
        self.location_area: str | None = None
        self.missing_fields: list[str] = []
        self.is_vip: bool = False
        self.vip_name: str | None = None
        self.is_urgent: bool = False
        self.urgency_signal: str | None = None
        self.party_type: str | None = None
        self.missing_field_question: str | None = None
        self.missing_field_asked: str | None = None
        self.reply: str | None = None
        self.reply_type: str | None = None
        self.day_off_start: str | None = None
        self.day_off_end: str | None = None
        self.day_off_person: str | None = None


def execute_tool(name: str, inputs: dict[str, Any], results: ToolResults) -> str:
    if name == "detect_intent":
        results.intent = inputs.get("intent")
        results.intent_confidence = inputs.get("confidence")
        return f"Intent detected: {results.intent}"

    if name == "extract_meeting_details":
        if inputs.get("organizer_name"):
            results.organizer_name = inputs["organizer_name"]
        if inputs.get("purpose"):
            results.purpose = inputs["purpose"]
        if inputs.get("duration_mins"):
            results.duration_mins = inputs["duration_mins"]
        if inputs.get("proposed_dt"):
            results.proposed_dt = inputs["proposed_dt"]
        results.is_external = inputs.get("is_external", False)
        if inputs.get("location_area"):
            results.location_area = inputs["location_area"]
        results.missing_fields = inputs.get("missing_fields", [])
        return "Details extracted"

    if name == "extract_day_off":
        if inputs.get("start_date"):
            results.day_off_start = inputs["start_date"]
        if inputs.get("end_date"):
            results.day_off_end = inputs["end_date"]
        if inputs.get("person_name"):
            results.day_off_person = inputs["person_name"]
        return "Day off extracted"

    if name == "detect_vip":
        results.is_vip = inputs.get("is_vip", False)
        results.vip_name = inputs.get("vip_name")
        return f"VIP: {results.is_vip}"

    if name == "detect_urgency":
        results.is_urgent = inputs.get("is_urgent", False)
        results.urgency_signal = inputs.get("urgency_signal")
        return f"Urgent: {results.is_urgent}"

    if name == "detect_external_party":
        results.is_external = inputs.get("is_external", False)
        results.party_type = inputs.get("party_type")
        return f"External: {results.is_external}"

    if name == "request_missing_info":
        results.missing_field_asked = inputs.get("missing_field")
        results.missing_field_question = inputs.get("question")
        return f"Will ask for: {results.missing_field_asked}"

    if name == "generate_reply":
        results.reply = inputs.get("reply")
        results.reply_type = inputs.get("reply_type")
        return "Reply generated"

    return f"Unknown tool: {name}"
