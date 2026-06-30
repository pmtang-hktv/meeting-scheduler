from __future__ import annotations
import json
import logging
import re
import anthropic
from ai.prompts import get_system_prompt
from ai.tools import TOOLS
from ai.tool_executor import ToolResults, execute_tool

logger = logging.getLogger(__name__)
_client: anthropic.AsyncAnthropic | None = None


def configure(api_key: str) -> None:
    global _client
    # The SDK retries transient failures (429 rate-limit, 5xx, 529 overloaded, connection
    # drops, timeouts) with exponential backoff and honours Retry-After. The default of 2
    # retries is too few when Haiku is briefly overloaded — a single blip then surfaced as
    # an unhandled exception and the user saw "Sorry, something went wrong". Retry more, and
    # cap each attempt at 30s so a stalled request fails fast and is retried rather than
    # hanging on the SDK's 10-minute default.
    _client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=5, timeout=30.0)


async def run_conversation(
    messages: list[dict],
    max_iterations: int = 10,
) -> ToolResults:
    """Agentic tool-use loop. Returns aggregated ToolResults after all tool calls settle."""
    assert _client is not None, "claude_client not configured"

    results = ToolResults()
    system = [{"type": "text", "text": get_system_prompt(), "cache_control": {"type": "ephemeral"}}]
    current_messages = list(messages)

    for _ in range(max_iterations):
        response = await _client.messages.create(
            model="claude-haiku-4-5-20251001",
            system=system,
            messages=current_messages,
            tools=TOOLS,
            max_tokens=2048,
        )

        if response.stop_reason == "end_turn":
            # Extract any final text as a reply if generate_reply wasn't called
            for block in response.content:
                if block.type == "text" and not results.reply:
                    results.reply = block.text
            break

        if response.stop_reason == "tool_use":
            tool_results_content: list[dict] = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_output = execute_tool(block.name, block.input, results)
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": tool_output,
                    })

            current_messages = current_messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results_content},
            ]
        else:
            break

    return results


async def evaluate_location_reply(
    purpose: str,
    meeting_date: str,
    user_message: str,
) -> tuple[bool, str | None, str]:
    """
    Use Claude to judge whether user_message is a valid venue/address reply to a location
    chase message. Returns (location_found, extracted_location, reply_to_send).

    If location_found is False the caller should stay in AWAITING_LOCATION and send the
    follow-up reply so Claude can re-ask in a natural way.
    """
    assert _client is not None, "claude_client not configured"
    prompt = (
        f"You are helping manage a Telegram scheduling bot. "
        f"A reminder was sent asking for the exact venue of an upcoming meeting.\n\n"
        f"Meeting: {purpose}\n"
        f"Date/time: {meeting_date}\n"
        f"Person's reply: \"{user_message}\"\n\n"
        f"Does this reply contain a specific venue or address that can be used as the meeting location? "
        f"Reply ONLY with a JSON object, no other text:\n"
        f"{{\"found\": true/false, "
        f"\"location\": \"<clean venue/address string or null>\", "
        f"\"reply\": \"<short friendly Telegram message to send back>\"}}\n\n"
        f"If found=true, the reply should confirm the location was noted.\n"
        f"If found=false (vague, off-topic, or just TBC/unknown), the reply should politely re-ask for the specific venue."
    )
    try:
        response = await _client.messages.create(
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
        )
        raw = response.content[0].text.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            found = bool(data.get("found"))
            location = data.get("location") or None
            reply = data.get("reply") or ("Got it, location noted." if found else "Could you share the exact venue or address?")
            return found, location, reply
    except Exception:
        logger.exception("evaluate_location_reply failed")
    return False, None, "Could you please share the exact venue or address for the meeting?"
