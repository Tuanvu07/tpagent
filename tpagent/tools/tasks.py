"""Task list tools (like Claude Code's TodoWrite): task_create / task_update / task_list.

State is in-memory for the process and mirrored to `<workspace>/.tpagent/tasks.json`
so a resumed session or a second process sees the same list."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from .base import Tool
from .workspace import state_dir

STATUSES = ("pending", "in_progress", "completed", "deleted")
FILE_NAME = "tasks.json"


@dataclass
class Task:
    id: int
    subject: str
    description: str = ""
    status: str = "pending"
    updated: float = 0.0


_TASKS: dict[int, Task] = {}
_LOADED_FROM: str | None = None  # workspace path the cache was loaded for


def _file():
    return state_dir() / FILE_NAME


def _load() -> dict[int, Task]:
    """Load the mirror once per workspace; the in-memory dict is authoritative afterwards."""
    global _LOADED_FROM  # noqa: PLW0603
    path = _file()
    if _LOADED_FROM == str(path):
        return _TASKS
    _TASKS.clear()
    _LOADED_FROM = str(path)
    if path.is_file():
        try:
            for raw in json.loads(path.read_text(encoding="utf-8")):
                t = Task(**raw)
                _TASKS[t.id] = t
        except (OSError, ValueError, TypeError):
            pass
    return _TASKS


def _save() -> None:
    try:
        path = state_dir(create=True) / FILE_NAME
        path.write_text(json.dumps([asdict(t) for t in _TASKS.values()], ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def reset() -> None:
    """Forget cached tasks (tests / workspace switch)."""
    global _LOADED_FROM  # noqa: PLW0603
    _TASKS.clear()
    _LOADED_FROM = None


def task_create(subject: str, description: str = "") -> str:
    tasks = _load()
    tid = max(tasks, default=0) + 1
    tasks[tid] = Task(id=tid, subject=subject.strip(), description=description.strip(), updated=time.time())
    _save()
    return f"Created task #{tid}: {subject.strip()}\n\n{task_list()}"


def task_update(id: int, status: str) -> str:
    tasks = _load()
    if status not in STATUSES:
        return f"Error: status must be one of {STATUSES}"
    task = tasks.get(int(id))
    if task is None:
        return f"Error: no task #{id}"
    task.status, task.updated = status, time.time()
    _save()
    return f"Task #{task.id} -> {status}\n\n{task_list()}"


def task_list() -> str:
    live = [t for t in _load().values() if t.status != "deleted"]
    if not live:
        return "(no tasks)"
    mark = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    rows = [f"{mark[t.status]} #{t.id} {t.subject}" + (f" - {t.description}" if t.description else "") for t in live]
    done = sum(t.status == "completed" for t in live)
    return "\n".join(rows) + f"\n({done}/{len(live)} completed)"


def all_tasks() -> list[Task]:
    """Live tasks for UIs (excludes deleted)."""
    return [t for t in _load().values() if t.status != "deleted"]


_OBJ = {"type": "object"}

TOOLS: list[Tool] = [
    Tool(
        "task_create",
        "Add a task to the plan. Use for multi-step work so progress is visible; keep subjects short and actionable.",
        {**_OBJ, "properties": {"subject": {"type": "string"}, "description": {"type": "string", "default": ""}},
         "required": ["subject"]},
        task_create, tags=["tasks"],
    ),
    Tool(
        "task_update",
        "Change a task's status: pending | in_progress | completed | deleted. Mark in_progress before starting, completed right after finishing.",
        {**_OBJ, "properties": {"id": {"type": "integer"}, "status": {"type": "string", "enum": list(STATUSES)}},
         "required": ["id", "status"]},
        task_update, tags=["tasks"],
    ),
    Tool("task_list", "Show the current task list.", {**_OBJ, "properties": {}}, task_list, tags=["tasks", "read"]),
]

__all__ = ["TOOLS", "Task", "STATUSES", "task_create", "task_update", "task_list", "all_tasks", "reset"]
