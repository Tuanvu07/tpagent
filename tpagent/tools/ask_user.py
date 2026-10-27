"""ask_user tool: let the model ask the human a question mid-task.

The agent sets the `CURRENT_ASK` contextvar to its `ask_user` hook for the
duration of `run()` (same pattern as subagent depth). Without a hook the tool
tells the model to decide on its own and state the assumption."""
from __future__ import annotations

import contextvars
from typing import Awaitable, Callable

from .base import Tool

AskUserFn = Callable[[str, list[str] | None], Awaitable[str]]
NO_USER = "No user available; decide yourself and state the assumption."

CURRENT_ASK: contextvars.ContextVar[AskUserFn | None] = contextvars.ContextVar("tpagent_ask_user", default=None)


async def ask_user(question: str, options: list[str] | None = None) -> str:
    hook = CURRENT_ASK.get()
    if hook is None:
        return NO_USER
    answer = await hook(question.strip(), list(options) if options else None)
    return answer.strip() if answer and answer.strip() else "(user gave no answer)"


TOOLS: list[Tool] = [
    Tool(
        "ask_user",
        "Ask the user a question when the task is ambiguous or a decision is theirs to make (e.g. which option, "
        "confirm scope). Offer short options when possible. Blocks until they answer; use sparingly.",
        {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}, "description": "Optional choices to pick from"},
            },
            "required": ["question"],
        },
        ask_user, tags=["ask_user"],
    ),
]

__all__ = ["TOOLS", "CURRENT_ASK", "AskUserFn", "NO_USER", "ask_user"]
