"""Permission layer: ask before dangerous tool calls, remember session allow-list.

Two entry points:
  * `check_async(tool, args)` - used by the agent. Order: auto_approve / allow-list
    -> pluggable `approver` coroutine (web UI, tests) -> TTY prompt in a thread
    -> deny when nothing can ask.
  * `check(tool, args)` - the original synchronous path, kept for embedders.
"""
from __future__ import annotations

import asyncio
import fnmatch
import sys
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from rich.console import Console
from rich.prompt import Prompt

from tpagent.tools.base import Tool

AskFn = Callable[[str], str]  # receives a prompt, returns raw user answer
Approver = Callable[[Tool, dict[str, Any]], Awaitable[bool]]


def _default_ask(prompt: str) -> str:
    return Prompt.ask(prompt, console=Console(stderr=True), default="n")


def describe_call(tool: Tool, args: dict[str, Any]) -> str:
    if tool.name == "bash":
        return str(args.get("command", ""))[:300]
    short = {k: (v if len(str(v)) < 80 else str(v)[:77] + "...") for k, v in args.items()}
    return f"{tool.name} {short}"


@dataclass
class PermissionManager:
    auto_approve: bool = False
    safe_commands_auto: bool = True
    interactive: bool | None = None  # None -> stdin.isatty()
    approver: Approver | None = None  # async hook: (tool, args) -> allowed?
    ask_fn: AskFn = _default_ask
    allowed_patterns: list[str] = field(default_factory=list)  # "tool:glob" remembered for session
    denied_log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.interactive is None:
            self.interactive = sys.stdin.isatty()

    def _needs_prompt(self, tool: Tool, args: dict[str, Any]) -> bool:
        if not tool.dangerous or self.auto_approve:
            return False
        if tool.name == "bash" and self.safe_commands_auto:
            from tpagent.tools.shell import is_destructive

            return is_destructive(str(args.get("command", "")))
        return True

    def _is_allowed(self, key: str) -> bool:
        return any(fnmatch.fnmatch(key, pat) for pat in self.allowed_patterns)

    def _key(self, tool: Tool, args: dict[str, Any]) -> str:
        return f"{tool.name}:{describe_call(tool, args)}"

    def _deny(self, key: str) -> bool:
        self.denied_log.append(key)
        return False

    def check(self, tool: Tool, args: dict[str, Any]) -> bool:
        """Synchronous check (no approver). Non-interactive -> deny unless auto_approve."""
        if not self._needs_prompt(tool, args):
            return True
        key = self._key(tool, args)
        if self._is_allowed(key):
            return True
        if not self.interactive:
            return self._deny(key)
        return self._prompt(tool, key) or self._deny(key)

    async def check_async(self, tool: Tool, args: dict[str, Any]) -> bool:
        """Async check: allow-list -> approver hook -> TTY prompt (in a thread) -> deny."""
        if not self._needs_prompt(tool, args):
            return True
        key = self._key(tool, args)
        if self._is_allowed(key):
            return True
        if self.approver is not None:
            return bool(await self.approver(tool, args)) or self._deny(key)
        if not self.interactive:
            return self._deny(key)
        return await asyncio.to_thread(self._prompt, tool, key) or self._deny(key)

    def _prompt(self, tool: Tool, key: str) -> bool:
        desc = key.split(":", 1)[1]
        answer = self.ask_fn(f"[bold yellow]Cho phép chạy[/] [cyan]{tool.name}[/]?\n  {desc}\n  [y]es / [n]o / [a]lways for this tool").strip().lower()
        if answer in ("a", "always"):
            self.allowed_patterns.append(f"{tool.name}:*")
            return True
        return answer in ("y", "yes")

    def allow(self, pattern: str) -> None:
        """Add an allow-list pattern like 'bash:git *' or 'browser_click:*'."""
        self.allowed_patterns.append(pattern)


__all__ = ["PermissionManager", "Approver", "AskFn", "describe_call"]
