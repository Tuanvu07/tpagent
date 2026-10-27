"""bash tool with timeout, plus a destructive-command classifier used by the
permission layer (prompt only for dangerous commands when safe_commands_auto)."""
from __future__ import annotations

import asyncio
import re

from .base import Tool, ToolResult, truncate
from .workspace import get_workspace

DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600

DESTRUCTIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+",  # rm -rf, rm -r, rm -f ...
        r"\brm\s+-[a-z]*\s+/(\s|$)",  # rm ... /
        r"\brmdir\b",
        r"\bsudo\b",
        r"\bsu\s+-",
        r"\bmkfs(\.\w+)?\b",
        r"\bdd\s+if=",
        r"\bshred\b",
        r"\bchmod\s+(-R\s+)?[0-7]*777\b",
        r"\bchown\s+-R\b",
        r"\bgit\s+push\b.*(--force|-f\b|\+\w)",
        r"\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f|checkout\s+--\s+\.|branch\s+-D)",
        r"\bgit\s+push\b.*--delete",
        r"\b(drop|truncate)\s+(table|database)\b",
        r"\bkill\s+(-9\s+)?-1\b",
        r"\bkillall\b",
        r"\bpkill\b",
        r"\bshutdown\b|\breboot\b|\bhalt\b|\bpoweroff\b",
        r">\s*/dev/sd[a-z]",
        r"\bcurl\b.*\|\s*(ba|z|)sh\b",
        r"\bwget\b.*\|\s*(ba|z|)sh\b",
        r":\(\)\s*\{\s*:\|:&\s*\};:",  # fork bomb
        r"\b(pip|npm|apt|apt-get|brew|yum|dnf)\s+(uninstall|remove|purge)\b",
        r"\bfind\b.*-delete\b",
        r"\bfind\b.*-exec\s+rm\b",
        r"\bmv\s+.*\s+/dev/null",
        r"\btruncate\s+-s\s*0\b",
    )
]


def is_destructive(cmd: str) -> bool:
    """Heuristic: does this shell command delete data, escalate privileges,
    rewrite remote history or otherwise need a human to confirm?"""
    return any(p.search(cmd) for p in DESTRUCTIVE_PATTERNS)


async def bash(command: str, timeout: int = DEFAULT_TIMEOUT, cwd: str | None = None) -> ToolResult:
    """Run a shell command in the workspace root (or `cwd`); returns combined
    stdout/stderr and the exit code."""
    timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    cwd = cwd or str(get_workspace())
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.DEVNULL,
        cwd=cwd,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return ToolResult(text=f"Error: command timed out after {timeout}s", is_error=True)
    text = out.decode("utf-8", errors="replace")
    code = proc.returncode or 0
    body = truncate(text.rstrip() or "(no output)")
    if code != 0:
        return ToolResult(text=f"{body}\n\n[exit code {code}]", is_error=True)
    return ToolResult(text=body)


TOOLS: list[Tool] = [
    Tool(
        "bash",
        "Run a shell command (bash) and return stdout+stderr. Non-interactive only. "
        f"Default timeout {DEFAULT_TIMEOUT}s, max {MAX_TIMEOUT}s.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run"},
                "timeout": {"type": "integer", "description": "Seconds before the command is killed", "default": DEFAULT_TIMEOUT},
                "cwd": {"type": "string", "description": "Working directory (default: workspace root)"},
            },
            "required": ["command"],
        },
        bash,
        dangerous=True,
        tags=["shell"],
    )
]
