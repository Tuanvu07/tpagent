"""Fake provider for demos and tests: no network, no API key.

Default script: first turn reads a file (README.md or the first file it can
find named in the task), second turn echoes the task and the read result.
Tests can pass their own `responses` list instead. With `stream=True` and an
`on_delta` callback the text is delivered word by word (so the CLI/web UI can
be demoed without a key)."""
from __future__ import annotations

import re
from typing import Any

from tpagent.tools.base import Tool

from .base import DeltaCallback, LLMProvider, LLMResponse, Message, ToolCall, Usage


class FakeProvider(LLMProvider):
    name = "fake"
    supports_streaming = True

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = list(responses) if responses is not None else None
        self.calls: list[dict[str, Any]] = []  # recorded chat() inputs for assertions

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
        self.calls.append({"messages": messages, "tools": [t.name for t in tools], "system": system, "model": model,
                           "thinking_budget": thinking_budget, "stream": stream})
        if self._responses is not None:
            if not self._responses:
                resp = LLMResponse(text="(fake: script exhausted)", model=model)
            else:
                resp = self._responses.pop(0)
                resp.model = resp.model or model
        else:
            resp = self._default_script(messages, tools, model)
        if stream and on_delta is not None and resp.text:
            for piece in re.split(r"(?<=\s)", resp.text):
                if piece:
                    await on_delta(piece)
        return resp

    def _default_script(self, messages: list[Message], tools: list[Tool], model: str) -> LLMResponse:
        usage = Usage(input_tokens=_approx_tokens(messages), output_tokens=40)
        task = next((m["content"] for m in messages if m["role"] == "user" and isinstance(m["content"], str)), "")
        has_tool_result = any(m["role"] == "tool" for m in messages)
        tool_names = {t.name for t in tools}
        if not has_tool_result and "read_file" in tool_names:
            path = _guess_path(task)
            call = ToolCall(id="fake_1", name="read_file", args={"path": path, "limit": 20})
            return LLMResponse(
                text=f"[fake] I will read `{path}` first.", tool_calls=[call], usage=usage, stop_reason="tool_use", model=model
            )
        last_tool = next((m for m in reversed(messages) if m["role"] == "tool"), None)
        snippet = (last_tool or {}).get("content", "")[:300]
        return LLMResponse(
            text=f"[fake] Task: {task}\n\nTool result preview:\n{snippet}\n\nDone (fake provider, no API key used).",
            usage=usage,
            model=model,
        )


def _guess_path(task: str) -> str:
    m = re.search(r"[\w./-]+\.(?:py|md|txt|yaml|yml|toml|json|js|ts)", task)
    return m.group(0) if m else "README.md"


def _approx_tokens(messages: list[Message]) -> int:
    return sum(len(str(m.get("content", ""))) for m in messages) // 4
