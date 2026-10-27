"""Tool registry. Each submodule exposes TOOLS: list[Tool]. Optional modules
(browser/computer/video/subagent) are imported lazily so missing deps don't
break the core agent."""
from __future__ import annotations

import importlib

from .base import Tool, ToolResult, truncate

CORE_MODULES = ["files", "shell", "web", "tasks", "memory", "skills", "ask_user"]
OPTIONAL_MODULES = ["browser", "computer", "video", "subagent"]


def load_tools(enable: list[str] | None = None) -> list[Tool]:
    """Return tools from core modules plus any enabled optional modules.
    `enable` is a list of module names; None means core only."""
    tools: list[Tool] = []
    for mod in CORE_MODULES + [m for m in (enable or []) if m in OPTIONAL_MODULES]:
        try:
            m = importlib.import_module(f"tpagent.tools.{mod}")
            tools.extend(getattr(m, "TOOLS", []))
        except ImportError as e:  # optional dependency missing
            print(f"[tpagent] skip tool module '{mod}': {e}")
    return tools


__all__ = ["Tool", "ToolResult", "truncate", "load_tools", "CORE_MODULES", "OPTIONAL_MODULES"]
