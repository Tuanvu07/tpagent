"""Session persistence: `<sessions_dir>/<id>.json` with messages (images replaced
by their byte count), cost and per-model usage."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tpagent.config import Config
from tpagent.llm.base import Message


@dataclass
class SessionInfo:
    id: str
    path: Path
    messages: int
    cost_usd: float
    updated: float
    first_task: str


def session_path(config: Config, session_id: str) -> Path:
    return config.sessions_dir / f"{session_id}.json"


def jsonable(m: Message) -> dict[str, Any]:
    out = {k: v for k, v in m.items() if k != "image_png"}
    if m.get("image_png"):
        out["image_png_bytes"] = len(m["image_png"])
    return out


def save_session(config: Config, session_id: str, messages: list[Message], cost: Any) -> Path | None:
    try:
        config.sessions_dir.mkdir(parents=True, exist_ok=True)
        path = session_path(config, session_id)
        payload = {
            "session_id": session_id,
            "saved_at": time.time(),
            "messages": [jsonable(m) for m in messages],
            "cost_usd": cost.total_usd,
            "per_model": {k: vars(v) for k, v in cost.per_model.items()},
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        return path
    except OSError:
        return None


def load_messages(config: Config, session_id: str) -> list[Message]:
    """Restore a saved session's messages (images are gone; a placeholder notes it).
    Raises FileNotFoundError when the session does not exist."""
    path = session_path(config, session_id)
    if not path.is_file():
        raise FileNotFoundError(f"No session {session_id} in {config.sessions_dir}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    messages: list[Message] = []
    for m in payload.get("messages", []):
        m = dict(m)
        if m.pop("image_png_bytes", None):
            m["content"] = (m.get("content") or "") + "\n[image omitted on resume]"
        if m["role"] == "tool":
            m["image_png"] = None
        messages.append(m)
    return messages


def list_sessions(config: Config, limit: int = 20) -> list[SessionInfo]:
    """Newest first."""
    if not config.sessions_dir.is_dir():
        return []
    infos: list[SessionInfo] = []
    for path in config.sessions_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        msgs = payload.get("messages", [])
        first = next((str(m.get("content", "")) for m in msgs if m.get("role") == "user"), "")
        infos.append(SessionInfo(
            id=payload.get("session_id", path.stem), path=path, messages=len(msgs),
            cost_usd=float(payload.get("cost_usd", 0.0)), updated=path.stat().st_mtime,
            first_task=first.splitlines()[0][:80] if first else "",
        ))
    infos.sort(key=lambda s: s.updated, reverse=True)
    return infos[:limit]


__all__ = ["SessionInfo", "save_session", "load_messages", "list_sessions", "session_path", "jsonable"]
