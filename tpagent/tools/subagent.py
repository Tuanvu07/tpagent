"""Subagent tools: spawn child agents with a restricted toolset and fresh context.

TODO(integrator): this module expects from `tpagent.core.agent`:
  * `make_default_agent(config, enable_modules=None, model=None, tools=None,
    system_prompt=None, max_turns=None)` -> Agent. Only kwargs present in its
    signature are passed (inspected at call time), so extra/missing ones are fine.
    - `tools`: list[Tool] to restrict the child; if the factory lacks `tools`,
      the child's `.tools` attribute is overwritten after construction.
    - `model`: a tier name ("cheap"|"standard"|"strong") or model id, resolved
      via `Config.resolve_model`.
  * `Agent.run(task: str)` (async or sync) returning the final text, or an object
    with `.text` / `.final_text` / `.content`. `run_task`/`ask` are also tried.
  * `config` is obtained from `tpagent.config.load_config()` unless the parent
    agent sets `tpagent.tools.subagent.CONFIG`.
Everything is imported lazily so this module loads before the core exists.
"""
from __future__ import annotations

import asyncio
import contextvars
import importlib
import inspect
from typing import Any, Callable

from .base import Tool, truncate

MAX_DEPTH = 2
REPLY_LIMIT = 8_000
TIERS = ("cheap", "standard", "strong")
CHILD_SYSTEM_PROMPT = "You are a subagent; do the task and reply with a concise report."

CONFIG: Any = None  # parent may set this to its Config; otherwise load_config() is used
_depth: contextvars.ContextVar[int] = contextvars.ContextVar("tpagent_subagent_depth", default=0)
_factory_override: Callable[..., Any] | None = None  # tests monkeypatch via set_agent_factory


def set_agent_factory(factory: Callable[..., Any] | None) -> None:
    """Override the agent factory (used by tests / embedding apps)."""
    global _factory_override
    _factory_override = factory


def _get_factory() -> Callable[..., Any]:
    if _factory_override is not None:
        return _factory_override
    core = importlib.import_module("tpagent.core.agent")
    return core.make_default_agent


def _get_config() -> Any:
    if CONFIG is not None:
        return CONFIG
    return importlib.import_module("tpagent.config").load_config()


def _all_tools() -> list[Tool]:
    """Every tool the parent could have (core + all optional modules that import)."""
    registry = importlib.import_module("tpagent.tools")
    return registry.load_tools(enable=list(registry.OPTIONAL_MODULES))


def _select_tools(names: list[str] | None) -> list[Tool]:
    """Pick tools by name or module tag; always drop the subagent tools (depth guard)."""
    pool = [t for t in _all_tools() if "subagent" not in t.tags]
    if not names:
        return pool
    wanted = set(names)
    chosen = [t for t in pool if t.name in wanted or wanted & set(t.tags)]
    unknown = wanted - {t.name for t in chosen} - {tag for t in chosen for tag in t.tags}
    if unknown:
        raise ValueError(f"unknown tools/tags: {sorted(unknown)}; available: {sorted(t.name for t in pool)}")
    return chosen


def _build_agent(tools: list[Tool], tier: str, max_turns: int) -> Any:
    factory = _get_factory()
    params = inspect.signature(factory).parameters
    accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    offered: dict[str, Any] = {"enable_modules": [], "model": tier, "tools": tools,
                               "system_prompt": CHILD_SYSTEM_PROMPT, "max_turns": max_turns}
    kwargs = {k: v for k, v in offered.items() if accepts_any or k in params}
    agent = factory(_get_config(), **kwargs)
    if "tools" not in kwargs and hasattr(agent, "tools"):
        agent.tools = tools
    if "max_turns" not in kwargs and hasattr(agent, "max_turns"):
        agent.max_turns = max_turns
    return agent


async def _run_agent(agent: Any, task: str) -> str:
    runner = next((getattr(agent, n) for n in ("run", "run_task", "ask") if callable(getattr(agent, n, None))), None)
    if runner is None:
        raise TypeError("child agent has no run()/run_task()/ask() method")
    result = runner(task)
    if inspect.isawaitable(result):
        result = await result
    for attr in ("text", "final_text", "content"):
        if not isinstance(result, str) and hasattr(result, attr):
            result = getattr(result, attr)
            break
    return "" if result is None else str(result)


async def spawn_subagent(task: str, tools: list[str] | None = None, model_tier: str = "cheap",
                         max_turns: int = 15) -> str:
    """Run one child agent and return its final answer."""
    depth = _depth.get()
    if depth >= MAX_DEPTH:
        return f"Error: subagent depth limit ({MAX_DEPTH}) reached; do the task yourself."
    if model_tier not in TIERS:
        return f"Error: model_tier must be one of {TIERS}"
    selected = _select_tools(tools)
    token = _depth.set(depth + 1)
    try:
        agent = _build_agent(selected, model_tier, max_turns)
        answer = await _run_agent(agent, task.strip())
    finally:
        _depth.reset(token)
    return truncate(answer or "(subagent returned no text)", REPLY_LIMIT)


async def spawn_subagents_parallel(tasks: list[dict[str, Any]]) -> str:
    """Run several child agents concurrently; results are joined with headers."""
    if not tasks:
        return "Error: tasks list is empty"
    coros = [spawn_subagent(t["task"], t.get("tools"), t.get("tier", "cheap"), int(t.get("max_turns", 15)))
             for t in tasks]
    results = await asyncio.gather(*coros, return_exceptions=True)
    blocks = []
    for i, (t, r) in enumerate(zip(tasks, results), 1):
        body = f"Error: {type(r).__name__}: {r}" if isinstance(r, BaseException) else r
        title = t["task"].strip().splitlines()[0][:80]
        blocks.append(f"## Subagent {i}: {title}\n{body}")
    return "\n\n".join(blocks)


_TOOLS_PROP = {"type": "array", "items": {"type": "string"},
               "description": "Tool names or module tags (files, shell, web, browser, computer, video) "
                              "the child may use; default: all except subagent tools"}
_TIER_PROP = {"type": "string", "enum": list(TIERS), "description": "Model tier for the child (default cheap)"}

TOOLS: list[Tool] = [
    Tool("spawn_subagent",
         "Delegate a self-contained task to a child agent with a fresh context and a restricted toolset. "
         "Use for research, exploring many files, or long side tasks; returns the child's final report.",
         {"type": "object",
          "properties": {"task": {"type": "string", "description": "Complete standalone instructions"},
                         "tools": _TOOLS_PROP, "model_tier": _TIER_PROP,
                         "max_turns": {"type": "integer", "description": "Turn budget (default 15)"}},
          "required": ["task"]},
         spawn_subagent, tags=["subagent"]),
    Tool("spawn_subagents_parallel",
         "Run several independent child agents at the same time and get all reports back together.",
         {"type": "object",
          "properties": {"tasks": {"type": "array", "items": {
              "type": "object",
              "properties": {"task": {"type": "string"}, "tools": _TOOLS_PROP, "tier": _TIER_PROP,
                             "max_turns": {"type": "integer"}},
              "required": ["task"]}}},
          "required": ["tasks"]},
         spawn_subagents_parallel, tags=["subagent"]),
]

__all__ = ["TOOLS", "spawn_subagent", "spawn_subagents_parallel", "set_agent_factory", "MAX_DEPTH"]
