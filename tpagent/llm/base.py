"""Provider-agnostic LLM interface.

Internal message format (list of dicts):
  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [ToolCall-as-dict, ...],
   "thinking": [provider thinking blocks to echo back, optional]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str,
   "image_png": bytes | None, "is_error": bool}
"""
from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from tpagent.tools.base import Tool

Message = dict[str, Any]
DeltaCallback = Callable[[str], Awaitable[None]]


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "args": self.args}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = "end_turn"
    model: str = ""
    thinking_blocks: list[dict[str, Any]] = field(default_factory=list)  # opaque, echoed back verbatim


class LLMProvider(ABC):
    name: str = "base"
    supports_streaming: bool = False  # agent passes stream=True/on_delta only when True

    @abstractmethod
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
        """Send one chat turn and return the normalized response.

        `stream` + `on_delta`: text is delivered incrementally while generating.
        `thinking_budget`: extended-thinking token budget (providers without it ignore).
        """


def png_to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def tool_calls_from_dicts(raw: list[dict[str, Any]] | None) -> list[ToolCall]:
    return [ToolCall(id=c["id"], name=c["name"], args=dict(c.get("args") or {})) for c in raw or []]


__all__ = ["DeltaCallback", "LLMProvider", "LLMResponse", "Message", "ToolCall", "Usage", "png_to_base64", "tool_calls_from_dicts"]
