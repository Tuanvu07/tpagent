"""File tools: read_file, write_file, edit_file, glob_files, grep_files, list_dir.

Paths outside the workspace root (default: cwd, see `set_workspace`) are
refused unless `allow_outside_cwd()` has been enabled (config.allow_outside_cwd)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .base import Tool, truncate
from .workspace import get_workspace, set_workspace

_ALLOW_OUTSIDE = False
MAX_READ_LINES = 2_000
MAX_LINE_CHARS = 2_000


def allow_outside_cwd(value: bool) -> None:
    global _ALLOW_OUTSIDE  # noqa: PLW0603 - single module-level switch set from config
    _ALLOW_OUTSIDE = value


def resolve(path: str) -> Path:
    root = get_workspace()
    p = Path(path).expanduser()
    p = (root / p).resolve() if not p.is_absolute() else p.resolve()
    if not _ALLOW_OUTSIDE and not p.is_relative_to(root):
        raise PermissionError(f"Path outside workspace is not allowed: {p} (workspace {root}; set allow_outside_cwd in config)")
    return p


def read_file(path: str, offset: int = 1, limit: int = MAX_READ_LINES) -> str:
    """Read a text file with 1-based line numbers. `offset` is the first line to show."""
    p = resolve(path)
    if not p.is_file():
        return f"Error: not a file: {p}"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(offset, 1) - 1
    chunk = lines[start : start + max(1, min(limit, MAX_READ_LINES))]
    if not chunk:
        return f"(empty: file has {len(lines)} lines, offset {offset} is past the end)"
    body = "\n".join(f"{start + i + 1:>6}\t{ln[:MAX_LINE_CHARS]}" for i, ln in enumerate(chunk))
    more = len(lines) - (start + len(chunk))
    suffix = f"\n... ({more} more lines, use offset={start + len(chunk) + 1})" if more > 0 else ""
    return truncate(body + suffix)


def write_file(path: str, content: str) -> str:
    """Create or overwrite a file (parent dirs are created)."""
    p = resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    p.write_text(content, encoding="utf-8")
    return f"{'Overwrote' if existed else 'Created'} {p} ({len(content)} chars)"


def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Replace `old_string` with `new_string`. `old_string` must occur exactly once
    unless replace_all=True."""
    p = resolve(path)
    if not p.is_file():
        return f"Error: not a file: {p}"
    if old_string == new_string:
        return "Error: old_string and new_string are identical"
    text = p.read_text(encoding="utf-8")
    count = text.count(old_string)
    if count == 0:
        return "Error: old_string not found in file. Re-read the file and copy the text exactly (whitespace matters)."
    if count > 1 and not replace_all:
        return f"Error: old_string occurs {count} times; include more surrounding context to make it unique, or set replace_all=true."
    p.write_text(text.replace(old_string, new_string), encoding="utf-8")
    return f"Edited {p}: replaced {count} occurrence(s)"


def glob_files(pattern: str, path: str = ".", limit: int = 200) -> str:
    """Find files matching a glob (e.g. '**/*.py'), newest first."""
    root = resolve(path)
    matches = [m for m in root.glob(pattern) if m.is_file() and ".git" not in m.parts]
    matches.sort(key=lambda m: m.stat().st_mtime, reverse=True)
    if not matches:
        return "No files matched."
    ws = get_workspace()
    shown = [str(m.relative_to(ws)) if m.is_relative_to(ws) else str(m) for m in matches[:limit]]
    extra = f"\n... ({len(matches) - limit} more)" if len(matches) > limit else ""
    return "\n".join(shown) + extra


def grep_files(pattern: str, path: str = ".", glob: str | None = None, ignore_case: bool = False, limit: int = 200) -> str:
    """Search file contents with a regex. Uses ripgrep when installed."""
    root = resolve(path)
    rg = shutil.which("rg")
    if rg:
        cmd = [rg, "-n", "--no-heading", "--color=never", "--max-count", "50", pattern, str(root)]
        if glob:
            cmd[1:1] = ["--glob", glob]
        if ignore_case:
            cmd.insert(1, "-i")
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            lines = proc.stdout.splitlines()
            if proc.returncode not in (0, 1):
                return f"rg error: {proc.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return "Error: grep timed out"
    else:
        lines = _python_grep(root, pattern, glob, ignore_case)
    if not lines:
        return "No matches."
    extra = f"\n... ({len(lines) - limit} more matches)" if len(lines) > limit else ""
    return truncate("\n".join(lines[:limit]) + extra)


def _python_grep(root: Path, pattern: str, glob: str | None, ignore_case: bool) -> list[str]:
    rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    out: list[str] = []
    files = [root] if root.is_file() else (f for f in root.rglob(glob or "*") if f.is_file() and ".git" not in f.parts)
    for f in files:
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if rx.search(line):
                    out.append(f"{f}:{i}:{line[:300]}")
        except OSError:
            continue
    return out


def list_dir(path: str = ".", depth: int = 1) -> str:
    """List a directory tree (dirs end with '/'), skipping .git and caches."""
    root = resolve(path)
    if not root.is_dir():
        return f"Error: not a directory: {root}"
    skip = {".git", "__pycache__", "node_modules", ".venv", ".mypy_cache", ".pytest_cache"}
    lines: list[str] = []
    for cur, dirs, files in os.walk(root):
        rel = Path(cur).relative_to(root)
        level = len(rel.parts)
        dirs[:] = sorted(d for d in dirs if d not in skip)
        if level >= depth:
            dirs[:] = []
        indent = "  " * level
        for d in dirs:
            lines.append(f"{indent}{d}/")
        for f in sorted(files):
            lines.append(f"{indent}{f}")
        if len(lines) > 500:
            lines.append("... (truncated)")
            break
    return "\n".join(lines) or "(empty)"


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


_PATH = {"type": "string", "description": "File path (relative to the workspace root or absolute)"}

TOOLS: list[Tool] = [
    Tool(
        "read_file",
        "Read a text file with line numbers. Use offset/limit for large files.",
        _schema({"path": _PATH, "offset": {"type": "integer", "description": "First line (1-based)", "default": 1},
                 "limit": {"type": "integer", "description": "Max lines", "default": MAX_READ_LINES}}, ["path"]),
        read_file, tags=["files", "read"],
    ),
    Tool(
        "write_file",
        "Create or overwrite a whole file. Prefer edit_file for changes to existing files.",
        _schema({"path": _PATH, "content": {"type": "string"}}, ["path", "content"]),
        write_file, tags=["files"],
    ),
    Tool(
        "edit_file",
        "Replace an exact text snippet in a file. old_string must match exactly once (include enough context).",
        _schema({"path": _PATH, "old_string": {"type": "string"}, "new_string": {"type": "string"},
                 "replace_all": {"type": "boolean", "default": False}}, ["path", "old_string", "new_string"]),
        edit_file, tags=["files"],
    ),
    Tool(
        "glob_files",
        "Find files by glob pattern, e.g. '**/*.py' or 'src/**/*.ts'. Newest first.",
        _schema({"pattern": {"type": "string"}, "path": {"type": "string", "default": "."},
                 "limit": {"type": "integer", "default": 200}}, ["pattern"]),
        glob_files, tags=["files", "read"],
    ),
    Tool(
        "grep_files",
        "Search file contents with a regular expression (ripgrep). Returns file:line:text.",
        _schema({"pattern": {"type": "string"}, "path": {"type": "string", "default": "."},
                 "glob": {"type": "string", "description": "Only files matching this glob, e.g. '*.py'"},
                 "ignore_case": {"type": "boolean", "default": False}, "limit": {"type": "integer", "default": 200}},
                ["pattern"]),
        grep_files, tags=["files", "read"],
    ),
    Tool(
        "list_dir",
        "List files and folders under a path (depth-limited tree).",
        _schema({"path": {"type": "string", "default": "."}, "depth": {"type": "integer", "default": 1}}, []),
        list_dir, tags=["files", "read"],
    ),
]

__all__ = ["TOOLS", "resolve", "allow_outside_cwd", "set_workspace", "get_workspace"]
