"""Session persistence view: saved JSON (config.sessions_dir) + per-session workspace dirs."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .files import SESSION_ID_RE, new_session_id, validate_session_id
from .settings import Settings

TITLE_CHARS = 80


@dataclass
class SessionInfo:
    id: str
    title: str
    cost_usd: float
    mtime: float
    message_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SessionStore:
    def __init__(self, settings: Settings) -> None:
        self.sessions_dir: Path = settings.config.sessions_dir
        self.workspace: Path = settings.workspace

    # --- paths -------------------------------------------------------------
    def session_dir(self, session_id: str, create: bool = False) -> Path:
        d = self.workspace / validate_session_id(session_id)
        if create:
            d.mkdir(parents=True, exist_ok=True)
        return d

    def session_file(self, session_id: str) -> Path:
        return self.sessions_dir / f"{validate_session_id(session_id)}.json"

    def exists(self, session_id: str) -> bool:
        return self.session_dir(session_id).is_dir() or self.session_file(session_id).is_file()

    # --- CRUD ----------------------------------------------------------------
    def create(self) -> str:
        session_id = new_session_id()
        self.session_dir(session_id, create=True)
        return session_id

    def load(self, session_id: str) -> dict[str, Any] | None:
        path = self.session_file(session_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def delete(self, session_id: str) -> None:
        path = self.session_file(session_id)
        if path.is_file():
            path.unlink()
        d = self.session_dir(session_id)
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)

    def list(self) -> list[dict[str, Any]]:
        ids: set[str] = set()
        if self.sessions_dir.is_dir():
            ids.update(p.stem for p in self.sessions_dir.glob("*.json"))
        if self.workspace.is_dir():
            ids.update(p.name for p in self.workspace.iterdir() if p.is_dir() and not p.name.startswith("."))
        infos = [self.info(sid) for sid in ids if SESSION_ID_RE.match(sid)]
        infos.sort(key=lambda i: i.mtime, reverse=True)
        return [i.to_dict() for i in infos]

    def info(self, session_id: str) -> SessionInfo:
        data = self.load(session_id) or {}
        messages = data.get("messages") or []
        first_user = next((m.get("content") for m in messages if m.get("role") == "user"), "")
        title = str(first_user or "").strip().splitlines()[0][:TITLE_CHARS] if first_user else "(phiên mới)"
        mtimes = [p.stat().st_mtime for p in (self.session_file(session_id), self.session_dir(session_id)) if p.exists()]
        return SessionInfo(
            id=session_id,
            title=title,
            cost_usd=float(data.get("cost_usd") or 0.0),
            mtime=max(mtimes, default=0.0),
            message_count=len(messages),
        )

