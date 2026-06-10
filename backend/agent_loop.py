"""
AgentLoop — drives a Claude tool-use conversation backed by MCPBridge.

Yields event dicts to the caller (HTTP layer streams these as SSE):
  {"type": "text",        "delta": str}
  {"type": "tool_call",   "id": str, "name": str, "input": dict}
  {"type": "tool_result", "id": str, "content": str, "is_error": bool}
  {"type": "done"}
  {"type": "error",       "message": str}
"""
import json
import logging
from typing import Any, AsyncGenerator

import anthropic

import config
import tool_filter
from mcp_bridge import MCPBridge

log = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"
MAX_ITERATIONS = 10  # prevent infinite tool-use loops

Message = dict[str, Any]


def _mcp_tools_to_anthropic(tools) -> list[dict]:
    """Convert MCP Tool objects to the format Anthropic's API expects."""
    result = []
    for t in tools:
        schema = t.inputSchema if t.inputSchema else {"type": "object", "properties": {}}
        result.append({
            "name": t.name,
            "description": t.description or "",
            "input_schema": schema,
        })
    return result


async def run(
    bridge: MCPBridge,
    history: list[Message],
    user_message: str,
) -> AsyncGenerator[dict, None]:
    """
    Async generator — yields event dicts for SSE streaming.

    Args:
        bridge:       Initialized MCPBridge instance.
        history:      Prior conversation messages (Anthropic format).
        user_message: The new user turn.
    """
    client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY, max_retries=5)

    messages: list[Message] = history + [{"role": "user", "content": user_message}]

    all_tools = await bridge.list_tools()
    mcp_tools = tool_filter.select(all_tools, user_message, history)
    log.info("Tool filter: %d/%d tools selected for this request", len(mcp_tools), len(all_tools))
    anthropic_tools = _mcp_tools_to_anthropic(mcp_tools)

    system = """\
You are a helpful Azure cloud assistant with access to tools that can read and \
manage Azure resources.

## Response style
- Always respond in clear, natural language — never paste raw JSON into your reply.
- Introduce what you found in one or two sentences before presenting any data.
- Use **markdown tables** for any list of resources, properties, or structured data \
(resource groups, VMs, storage accounts, policy results, role assignments, etc.).
- Use **bullet points** for short enumerations (3 items or fewer) where a table \
would be excessive.
- Use **bold** for resource names, IDs, and key values so they stand out.
- For status or health information, use plain English (e.g. "running", "stopped", \
"compliant") rather than the raw API enum value.
- Keep responses concise — summarise what matters, omit fields the user didn't ask \
about unless they are important for context.
- If a tool returns an error or empty result, explain what that means in plain English \
and suggest a next step.

## Tool use
- Call a tool whenever you need live Azure data — do not guess resource names or IDs.
- Before each tool call, write one short sentence explaining what you are about to look up.
- After receiving tool results, interpret and summarise them; do not repeat the raw \
payload back to the user.\
"""

    for iteration in range(MAX_ITERATIONS):
        assistant_content: list[dict] = []
        tool_use_blocks: list[dict] = []

        try:
            async with client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=system,
                messages=messages,
                tools=anthropic_tools,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            tool_use_blocks.append({
                                "type": "tool_use",
                                "id": block.id,
                                "name": block.name,
                                "input": {},
                            })

                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield {"type": "text", "delta": delta.text}
                            # Accumulate for history
                            if assistant_content and assistant_content[-1]["type"] == "text":
                                assistant_content[-1]["text"] += delta.text
                            else:
                                assistant_content.append({"type": "text", "text": delta.text})

                        elif delta.type == "input_json_delta" and tool_use_blocks:
                            # Accumulate tool input JSON — it arrives as a partial string
                            current = tool_use_blocks[-1]
                            current.setdefault("_input_json", "")
                            current["_input_json"] += delta.partial_json

                    elif event.type == "message_stop":
                        # Parse accumulated tool input JSON
                        for block in tool_use_blocks:
                            raw = block.pop("_input_json", "{}")
                            try:
                                block["input"] = json.loads(raw)
                            except json.JSONDecodeError:
                                block["input"] = {}

                stop_reason = (await stream.get_final_message()).stop_reason

        except anthropic.RateLimitError as exc:
            yield {"type": "error", "message": "Rate limit reached. The request was retried but still failed — please wait a moment and try again."}
            log.warning("Rate limit error after retries: %s", exc)
            return
        except anthropic.APIError as exc:
            yield {"type": "error", "message": f"Claude API error: {exc}"}
            return

        # Merge tool_use_blocks into assistant_content for history
        assistant_content.extend(tool_use_blocks)
        messages.append({"role": "assistant", "content": assistant_content})

        if stop_reason != "tool_use" or not tool_use_blocks:
            # No more tool calls — we're done
            break

        # Execute all tool calls and collect results
        tool_results: list[dict] = []
        for block in tool_use_blocks:
            tool_id = block["id"]
            tool_name = block["name"]
            tool_input = block["input"]

            yield {"type": "tool_call", "id": tool_id, "name": tool_name, "input": tool_input}

            try:
                result = await bridge.call_tool(tool_name, tool_input)
                is_error = bool(result.isError)
                content_text = "\n".join(
                    c.text for c in result.content if hasattr(c, "text")
                )
            except Exception as exc:
                is_error = True
                content_text = f"Tool execution error: {exc}"

            yield {"type": "tool_result", "id": tool_id, "content": content_text, "is_error": is_error}

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": content_text,
                "is_error": is_error,
            })

        messages.append({"role": "user", "content": tool_results})
        tool_use_blocks = []

    else:
        yield {"type": "error", "message": f"Exceeded maximum tool iterations ({MAX_ITERATIONS})"}
        return

    yield {"type": "done"}
