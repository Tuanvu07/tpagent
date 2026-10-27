"""Workspace root shared by file/shell/tasks/memory/skills tools.

Resolution order: the `CURRENT_WORKSPACE` contextvar (pinned by `Agent.run`, so
several agents with different workspaces can run concurrently in one process),
then the process-wide root set by `set_workspace`, then the current working
directory (resolved on every call, so tests that chdir keep working).
Per-workspace state lives in `<workspace>/.tpagent/`."""
from __future__ import annotations

import contextvars
from pathlib import Path

_WORKSPACE: Path | None = None
STATE_DIR_NAME = ".tpagent"
CURRENT_WORKSPACE: contextvars.ContextVar[Path | None] = contextvars.ContextVar("tpagent_workspace", default=None)


def set_workspace(path: str | Path | None) -> Path:
    """Set the workspace root (None resets to 'follow cwd'). Returns the resolved root."""
    global _WORKSPACE  # noqa: PLW0603 - single process-wide root, set at startup
    _WORKSPACE = Path(path).expanduser().resolve() if path is not None else None
    return get_workspace()


def get_workspace() -> Path:
    pinned = CURRENT_WORKSPACE.get()
    if pinned is not None:
        return pinned
    return _WORKSPACE if _WORKSPACE is not None else Path.cwd().resolve()


def state_dir(create: bool = False) -> Path:
    d = get_workspace() / STATE_DIR_NAME
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


__all__ = ["CURRENT_WORKSPACE", "set_workspace", "get_workspace", "state_dir", "STATE_DIR_NAME"]
