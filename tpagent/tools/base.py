"""Shared Tool contract. Every tool module exposes `TOOLS: list[Tool]`.

Tools are provider-agnostic: the agent converts `schema` to Anthropic or
OpenAI tool format. `run` receives validated kwargs and returns a string
(or a `ToolResult` when it needs to attach an image for vision models).
"""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class ToolResult:
    text: str
    image_png: bytes | None = None  # optional screenshot for vision models
    is_error: bool = False


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]  # JSON schema for parameters (type: object)
    run: Callable[..., str | ToolResult | Awaitable[str | ToolResult]]
    dangerous: bool = False  # requires permission unless --yes
    tags: list[str] = field(default_factory=list)  # e.g. ["files"], ["browser"]

    async def call(self, **kwargs: Any) -> ToolResult:
        try:
            out = self.run(**kwargs)
            if inspect.isawaitable(out):
                out = await out
            elif not isinstance(out, (str, ToolResult)):
                # sync functions that return plain values
                out = str(out)
            if isinstance(out, str):
                return ToolResult(text=out)
            return out
        except Exception as e:  # noqa: BLE001
            return ToolResult(text=f"Error in {self.name}: {type(e).__name__}: {e}", is_error=True)

    # --- format converters -------------------------------------------------
    def to_anthropic(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.schema}

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.schema},
        }


def truncate(text: str, limit: int = 30_000) -> str:
    """Keep tool output under control so cheap models stay in the cheap price tier."""
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    return f"{head}\n\n... [truncated {len(text) - limit} chars] ...\n\n{tail}"


__all__ = ["Tool", "ToolResult", "truncate", "asyncio"]
