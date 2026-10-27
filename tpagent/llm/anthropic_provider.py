"""Anthropic provider: native tool use, image blocks, prompt caching,
streaming (`messages.stream`) and extended thinking.

Thinking blocks returned by the model are kept verbatim (including their
`signature`) on the assistant message under `"thinking"` and sent back first
in the next request, as the API requires during tool use."""
from __future__ import annotations

import json
from typing import Any

from tpagent.tools.base import Tool

from .base import DeltaCallback, LLMProvider, LLMResponse, Message, ToolCall, Usage, png_to_base64

CACHE = {"type": "ephemeral"}
THINKING_HEADROOM = 2_000  # max_tokens must exceed budget_tokens; leave room for the answer
THINKING_TYPES = {"thinking", "redacted_thinking"}


def convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Internal format -> Anthropic messages. Consecutive tool results are
    merged into one user message, as the API requires."""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            out.append({"role": "assistant", "content": _assistant_blocks(m)})
        elif role == "tool":
            block = _tool_result_block(m)
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


def _assistant_blocks(m: Message) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [dict(b) for b in m.get("thinking") or [] if b.get("type") in THINKING_TYPES]
    if m.get("content"):
        blocks.append({"type": "text", "text": m["content"]})
    for call in m.get("tool_calls") or []:
        blocks.append({"type": "tool_use", "id": call["id"], "name": call["name"], "input": call.get("args") or {}})
    return blocks or [{"type": "text", "text": "(no content)"}]


def _tool_result_block(m: Message) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": m.get("content") or "(empty)"}]
    if m.get("image_png"):
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": png_to_base64(m["image_png"])},
            }
        )
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": content}
    if m.get("is_error"):
        block["is_error"] = True
    return block


def convert_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    converted = [t.to_anthropic() for t in tools]
    if converted:
        converted[-1]["cache_control"] = CACHE  # cache the whole tool list
    return converted


def _thinking_block(block: Any) -> dict[str, Any]:
    if block.type == "redacted_thinking":
        return {"type": "redacted_thinking", "data": block.data}
    return {"type": "thinking", "thinking": block.thinking, "signature": getattr(block, "signature", "") or ""}


def parse_response(resp: Any) -> LLMResponse:
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    thinking: list[dict[str, Any]] = []
    for block in resp.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            args = block.input if isinstance(block.input, dict) else json.loads(block.input or "{}")
            calls.append(ToolCall(id=block.id, name=block.name, args=args))
        elif block.type in THINKING_TYPES:
            thinking.append(_thinking_block(block))
    u = resp.usage
    usage = Usage(
        input_tokens=getattr(u, "input_tokens", 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0),
        output_tokens=getattr(u, "output_tokens", 0),
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
    )
    return LLMResponse(
        text="".join(text_parts),
        tool_calls=calls,
        usage=usage,
        stop_reason=resp.stop_reason or "end_turn",
        model=getattr(resp, "model", ""),
        thinking_blocks=thinking,
    )


def build_request(
    messages: list[Message], tools: list[Tool], system: str, model: str, max_tokens: int, thinking_budget: int | None
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": CACHE}],
        "messages": convert_messages(messages),
    }
    if tools:
        kwargs["tools"] = convert_tools(tools)
    if thinking_budget and thinking_budget > 0:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        kwargs["max_tokens"] = max(max_tokens, thinking_budget + THINKING_HEADROOM)
    return kwargs


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    supports_streaming = True

    def __init__(self, api_key: str | None, base_url: str | None = None) -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)

    async def chat(
        self,
        messages: list[Message],
        tools: list[Tool],
        system: str,
        model: str,
        max_tokens: int = 8_000,
        *,
        stream: bool = False,
        on_delta: DeltaCallback | None = None,
        on_thinking: DeltaCallback | None = None,
        thinking_budget: int | None = None,
    ) -> LLMResponse:
        kwargs = build_request(messages, tools, system, model, max_tokens, thinking_budget)
        if not stream:
            return parse_response(await self._client.messages.create(**kwargs))
        async with self._client.messages.stream(**kwargs) as s:
            async for event in s:
                if event.type == "text" and on_delta is not None:
                    await on_delta(event.text)
                elif event.type == "thinking" and on_thinking is not None:
                    await on_thinking(event.thinking)
            final = await s.get_final_message()
        return parse_response(final)


__all__ = ["AnthropicProvider", "build_request", "convert_messages", "convert_tools", "parse_response"]
