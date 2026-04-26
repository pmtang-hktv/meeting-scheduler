from __future__ import annotations
import anthropic
from ai.prompts import SYSTEM_PROMPT
from ai.tools import TOOLS
from ai.tool_executor import ToolResults, execute_tool

_client: anthropic.AsyncAnthropic | None = None


def configure(api_key: str) -> None:
    global _client
    _client = anthropic.AsyncAnthropic(api_key=api_key)


async def run_conversation(
    messages: list[dict],
    max_iterations: int = 10,
) -> ToolResults:
    """Agentic tool-use loop. Returns aggregated ToolResults after all tool calls settle."""
    assert _client is not None, "claude_client not configured"

    results = ToolResults()
    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    current_messages = list(messages)

    for _ in range(max_iterations):
        response = await _client.messages.create(
            model="claude-sonnet-4-6",
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
