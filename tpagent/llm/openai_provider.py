"""OpenAI-compatible provider: OpenAI, DeepSeek, Qwen/DashScope, Gemini,
OpenRouter, Ollama. Only `base_url` and `api_key` differ. Streaming assembles
text and tool-call argument deltas into one LLMResponse; `thinking_budget`
is ignored (reasoning models decide on their own)."""
from __future__ import annotations

import json
from typing import Any

from tpagent.tools.base import Tool

from .base import DeltaCallback, LLMProvider, LLMResponse, Message, ToolCall, Usage, png_to_base64


def convert_messages(messages: list[Message], system: str) -> list[dict[str, Any]]:
    """Internal format -> OpenAI chat messages. Tool-result images cannot
    live in a `tool` message, so they are appended as a follow-up user
    message with an image_url data URI."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            out.append(_assistant_message(m))
        elif role == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m.get("content") or "(empty)"})
            if m.get("image_png"):
                out.append(_image_user_message(m))
    return out


def _assistant_message(m: Message) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant", "content": m.get("content") or None}
    calls = m.get("tool_calls") or []
    if calls:
        msg["tool_calls"] = [
            {
                "id": c["id"],
                "type": "function",
                "function": {"name": c["name"], "arguments": json.dumps(c.get("args") or {}, ensure_ascii=False)},
            }
            for c in calls
        ]
    return msg


def _image_user_message(m: Message) -> dict[str, Any]:
    uri = f"data:image/png;base64,{png_to_base64(m['image_png'])}"
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": f"Screenshot returned by tool `{m.get('name', 'tool')}`:"},
            {"type": "image_url", "image_url": {"url": uri}},
        ],
    }


def convert_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    return [t.to_openai() for t in tools]


def _parse_args(raw: str | dict | None) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_raw": parsed}


def parse_response(resp: Any) -> LLMResponse:
    choice = resp.choices[0]
    msg = choice.message
    calls = [
        ToolCall(id=tc.id or f"call_{i}", name=tc.function.name, args=_parse_args(tc.function.arguments))
        for i, tc in enumerate(msg.tool_calls or [])
    ]
    usage = _usage_from(getattr(resp, "usage", None))
    finish = choice.finish_reason or "stop"
    stop = "tool_use" if calls else ("max_tokens" if finish == "length" else "end_turn")
    return LLMResponse(text=msg.content or "", tool_calls=calls, usage=usage, stop_reason=stop, model=resp.model or "")


def _cached_tokens(usage: Any) -> int:
    details = getattr(usage, "prompt_tokens_details", None)
    return getattr(details, "cached_tokens", 0) or 0 if details else 0


def _usage_from(usage: Any) -> Usage:
    if not usage:
        return Usage()
    return Usage(
        input_tokens=usage.prompt_tokens or 0,
        output_tokens=usage.completion_tokens or 0,
        cache_read_tokens=_cached_tokens(usage),
    )


async def assemble_stream(chunks: Any, on_delta: DeltaCallback | None) -> LLMResponse:
    """Fold chat-completion stream chunks into one response. Tool-call
    arguments arrive as string fragments keyed by `index`."""
    text_parts: list[str] = []
    calls: dict[int, dict[str, str]] = {}
    usage, model, finish = Usage(), "", ""
    async for chunk in chunks:
        model = getattr(chunk, "model", None) or model
        if getattr(chunk, "usage", None):
            usage = _usage_from(chunk.usage)
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        finish = choice.finish_reason or finish
        delta = choice.delta
        if delta is None:
            continue
        if delta.content:
            text_parts.append(delta.content)
            if on_delta is not None:
                await on_delta(delta.content)
        for tc in delta.tool_calls or []:
            slot = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
            slot["id"] = tc.id or slot["id"]
            if tc.function:
                slot["name"] = tc.function.name or slot["name"]
                slot["arguments"] += tc.function.arguments or ""
    tool_calls = [
        ToolCall(id=c["id"] or f"call_{i}", name=c["name"], args=_parse_args(c["arguments"]))
        for i, c in sorted(calls.items())
    ]
    stop = "tool_use" if tool_calls else ("max_tokens" if finish == "length" else "end_turn")
    return LLMResponse(text="".join(text_parts), tool_calls=tool_calls, usage=usage, stop_reason=stop, model=model)


class OpenAIProvider(LLMProvider):
    name = "openai"
    supports_streaming = True

    def __init__(self, api_key: str | None, base_url: str | None = None, name: str = "openai") -> None:
        import openai

        self.name = name
        self._client = openai.AsyncOpenAI(api_key=api_key or "none", base_url=base_url)

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
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": convert_messages(messages, system),
        }
        if tools:
            kwargs["tools"] = convert_tools(tools)
            kwargs["tool_choice"] = "auto"
        if not stream:
            return parse_response(await self._client.chat.completions.create(**kwargs))
        chunks = await self._client.chat.completions.create(
            **kwargs, stream=True, stream_options={"include_usage": True}
        )
        return await assemble_stream(chunks, on_delta)
