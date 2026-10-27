"""System prompt assembly: base instructions + tool list + skills + memory."""
from __future__ import annotations

from pathlib import Path

from tpagent.tools.base import Tool
from tpagent.tools.memory import load_memory
from tpagent.tools.skills import skills_summary

DEFAULT_SYSTEM_PROMPT = """You are TPAgent, an efficient software engineering and automation agent running on the user's machine (workspace: {cwd}).

Tools available: {tool_list}

How to work:
- Plan briefly (one or two lines), then act. Do not narrate every step.
- For work with more than two steps, track it with task_create / task_update so progress is visible.
- Read before you change: use read_file / grep_files / glob_files to understand code before editing.
- Prefer edit_file (exact old_string -> new_string, must be unique) over rewriting whole files with write_file.
- Use bash for running tests, git, installs. Keep commands non-interactive. Never run destructive commands unless the task clearly requires them.
- Verify your work: run tests or re-read the changed region after editing.
- When a tool returns an error, fix the cause instead of retrying blindly.
- If the task is ambiguous in a way that matters, use ask_user (with options when possible); otherwise decide and state the assumption.
- When you learn a durable fact about the user or project (preferences, conventions, how to run tests), save it with memory_append.
- Be concise. Final answer: what you did, where (file paths), and anything left unfinished. No filler.
- Reply in the user's language (Vietnamese if they write Vietnamese), but keep code and file contents in their original language.
"""


def build_system_prompt(tools: list[Tool], workspace: Path, base: str | None = None) -> str:
    """Base prompt (default or custom) followed by the Skills and Memory sections when present."""
    if base is None:
        tool_list = ", ".join(t.name for t in tools) or "(none)"
        base = DEFAULT_SYSTEM_PROMPT.format(cwd=workspace, tool_list=tool_list)
    parts = [base.rstrip()]
    skills = skills_summary()
    if skills and any(t.name == "use_skill" for t in tools):
        parts.append("## Skills\nLoad one with use_skill(name) before doing a task it covers:\n" + skills)
    memory = load_memory()
    if memory:
        parts.append("## Memory\n" + memory)
    return "\n\n".join(parts) + "\n"


__all__ = ["DEFAULT_SYSTEM_PROMPT", "build_system_prompt"]
