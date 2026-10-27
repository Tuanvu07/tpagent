"""Build an Agent for a web session, adapting to whatever the core currently exports.

The core is being upgraded concurrently; `make_default_agent` may or may not accept
`workspace=`, `approver=` and `ask_user=`. We pass what it supports and emulate the
rest here (wrapping dangerous tools, adding an `ask_user` tool, fixing the prompt)."""
from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path
from typing import Any, Awaitable, Callable

from tpagent.config import Config
from tpagent.core import agent as core_agent
from tpagent.core.agent import Agent, make_default_agent
from tpagent.core.router import ModelUsage
from tpagent.tools.base import Tool, ToolResult

Approver = Callable[[str, dict[str, Any]], Awaitable[bool]]
AskUser = Callable[[str, list[str] | None], Awaitable[str]]

DENIED_TEXT = "Permission denied by user. Do not retry; explain or choose another approach."
WORKSPACE_NOTE = (
    "\nThe user's files for this session live in {ws}. Use absolute paths under that directory for all file "
    "operations and save every output there so the user can download it.\n"
)
ASK_USER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "The question to show the user"},
        "options": {"type": "array", "items": {"type": "string"}, "description": "Optional short choices shown as buttons"},
    },
    "required": ["question"],
}


def build_agent(config: Config, workspace: Path, approver: Approver, ask_user: AskUser, tier: str | None = None) -> Agent:
    params = inspect.signature(make_default_agent).parameters
    kwargs: dict[str, Any] = {"tier": tier}
    optional = {"workspace": workspace, "approver": _core_approver(approver), "ask_user": ask_user}
    kwargs.update({k: v for k, v in optional.items() if k in params})
    agent = make_default_agent(config, **kwargs)
    if "approver" not in params:
        _wrap_dangerous_tools(agent, approver)
    if "ask_user" not in params:
        _add_ask_user_tool(agent, ask_user)
    if "workspace" not in params:
        agent.system_prompt = _fallback_system_prompt(agent, workspace)
    return agent


def restore_session(agent: Agent, payload: dict[str, Any]) -> None:
    """Load messages + cost from a saved session JSON into a fresh agent."""
    agent.session_id = str(payload.get("session_id") or agent.session_id)
    messages: list[dict[str, Any]] = []
    for raw in payload.get("messages") or []:
        m = dict(raw)
        m.pop("image_png_bytes", None)  # images are not persisted; drop the placeholder
        if m.get("role") == "tool":
            m["image_png"] = None
        messages.append(m)
    agent.messages = messages
    known = {f.name for f in dataclasses.fields(ModelUsage)}
    for model, raw in (payload.get("per_model") or {}).items():
        if isinstance(raw, dict):
            agent.cost.per_model[model] = ModelUsage(**{k: v for k, v in raw.items() if k in known})


# --- emulation for an older core ---------------------------------------------
def _core_approver(approver: Approver) -> Callable[[Any, dict[str, Any]], Awaitable[bool]]:
    async def approve(tool: Any, args: dict[str, Any]) -> bool:
        return await approver(str(getattr(tool, "name", tool)), dict(args or {}))

    return approve


def _needs_approval(tool: Tool, args: dict[str, Any], config: Config) -> bool:
    if not tool.dangerous:
        return False
    if tool.name == "bash" and config.safe_commands_auto:
        from tpagent.tools.shell import is_destructive

        return is_destructive(str(args.get("command", "")))
    return True


def _guarded(tool: Tool, approver: Approver, config: Config) -> Tool:
    async def run(**kwargs: Any) -> ToolResult:
        if _needs_approval(tool, kwargs, config) and not await approver(tool.name, kwargs):
            return ToolResult(text=DENIED_TEXT, is_error=True)
        return await tool.call(**kwargs)

    return dataclasses.replace(tool, run=run)


def _wrap_dangerous_tools(agent: Agent, approver: Approver) -> None:
    if agent.permissions is not None:
        agent.permissions.auto_approve = True  # the wrappers below ask the browser instead of the TTY
    agent.tools = [_guarded(t, approver, agent.config) if t.dangerous else t for t in agent.tools]
    _refresh_tool_map(agent)


def _add_ask_user_tool(agent: Agent, ask_user: AskUser) -> None:
    if any(t.name == "ask_user" for t in agent.tools):
        return

    async def run(question: str, options: list[str] | None = None) -> str:
        return await ask_user(question, options)

    agent.tools.append(
        Tool(
            "ask_user",
            "Ask the user a question and wait for the answer. Use it when you need a decision or missing information. "
            "`options` are short choices shown as buttons; the user may also type a free answer.",
            ASK_USER_SCHEMA,
            run,
            tags=["user"],
        )
    )
    _refresh_tool_map(agent)


def _refresh_tool_map(agent: Agent) -> None:
    if hasattr(agent, "_tool_map"):
        agent._tool_map = {t.name: t for t in agent.tools}  # noqa: SLF001 - private cache of the older core


def _fallback_system_prompt(agent: Agent, workspace: Path) -> str:
    template = getattr(core_agent, "DEFAULT_SYSTEM_PROMPT", None)
    tool_list = ", ".join(t.name for t in agent.tools) or "(none)"
    try:
        base = template.format(cwd=workspace, tool_list=tool_list) if isinstance(template, str) else agent.system()
    except (KeyError, IndexError):
        base = agent.system()
    return base + WORKSPACE_NOTE.format(ws=workspace)
