"""Persistent memory: one Markdown file `<workspace>/.tpagent/MEMORY.md` (max 8k chars).

The agent's system prompt appends its contents under "## Memory", so facts
survive across sessions. Meant for durable facts about the user/project
(preferences, conventions, decisions), not for transient task state."""
from __future__ import annotations

from .base import Tool
from .workspace import state_dir

FILE_NAME = "MEMORY.md"
MAX_CHARS = 8_000


def memory_path():
    return state_dir() / FILE_NAME


def memory_read() -> str:
    p = memory_path()
    if not p.is_file():
        return "(memory is empty)"
    return p.read_text(encoding="utf-8") or "(memory is empty)"


def memory_write(content: str) -> str:
    """Replace the whole memory file."""
    content = content.strip() + "\n"
    if len(content) > MAX_CHARS:
        return f"Error: memory would be {len(content)} chars; limit is {MAX_CHARS}. Condense it first."
    (state_dir(create=True) / FILE_NAME).write_text(content, encoding="utf-8")
    return f"Memory saved ({len(content)} chars)."


def memory_append(line: str) -> str:
    """Append one line (a bullet is added when missing)."""
    line = line.strip()
    if not line:
        return "Error: empty line"
    if not line.startswith(("-", "*", "#")):
        line = f"- {line}"
    p = memory_path()
    current = p.read_text(encoding="utf-8") if p.is_file() else ""
    new = (current.rstrip("\n") + "\n" if current.strip() else "") + line + "\n"
    if len(new) > MAX_CHARS:
        return f"Error: memory full ({len(current)}/{MAX_CHARS} chars). Use memory_write to condense it."
    state_dir(create=True)
    p.write_text(new, encoding="utf-8")
    return f"Appended to memory ({len(new)} chars total)."


def load_memory() -> str:
    """Raw contents for the system prompt ('' when absent)."""
    p = memory_path()
    return p.read_text(encoding="utf-8").strip() if p.is_file() else ""


_OBJ = {"type": "object"}

TOOLS: list[Tool] = [
    Tool("memory_read", "Read the persistent memory file (durable facts about the user and this project).",
         {**_OBJ, "properties": {}}, memory_read, tags=["memory", "read"]),
    Tool(
        "memory_write",
        f"Replace the whole memory file (max {MAX_CHARS} chars). Save durable facts: user preferences, project "
        "conventions, decisions, paths that matter. Never store transient task state or secrets.",
        {**_OBJ, "properties": {"content": {"type": "string"}}, "required": ["content"]},
        memory_write, tags=["memory"],
    ),
    Tool(
        "memory_append",
        "Append one line to memory. Use when you learn a durable fact worth remembering next session.",
        {**_OBJ, "properties": {"line": {"type": "string"}}, "required": ["line"]},
        memory_append, tags=["memory"],
    ),
]

__all__ = ["TOOLS", "MAX_CHARS", "memory_read", "memory_write", "memory_append", "load_memory", "memory_path"]
