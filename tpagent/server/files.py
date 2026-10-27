"""Per-session workspace files: safe path resolution, listing, upload."""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status

SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")
MAX_TREE_ENTRIES = 2_000
UPLOAD_CHUNK = 1 << 20


def new_session_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def validate_session_id(session_id: str) -> str:
    if not SESSION_ID_RE.match(session_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mã phiên không hợp lệ")
    return session_id


def safe_child(root: Path, rel_path: str) -> Path:
    """Resolve `rel_path` inside `root`; reject traversal, absolute paths and symlink escapes."""
    root = root.resolve()
    candidate = (root / rel_path.lstrip("/\\")).resolve()
    if candidate != root and not candidate.is_relative_to(root):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Đường dẫn không hợp lệ")
    return candidate


def safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name.strip()
    base = re.sub(r"[\x00-\x1f]", "", base)
    if base in ("", ".", ".."):
        base = f"file-{uuid.uuid4().hex[:6]}"
    return base


@dataclass
class FileEntry:
    path: str
    name: str
    is_dir: bool
    size: int
    mtime: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def list_tree(root: Path) -> list[dict[str, Any]]:
    """Flat, sorted listing of every file/dir under root (hidden entries skipped)."""
    entries: list[FileEntry] = []
    if not root.is_dir():
        return []
    for p in sorted(root.rglob("*")):
        if any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        entries.append(FileEntry(p.relative_to(root).as_posix(), p.name, p.is_dir(), 0 if p.is_dir() else st.st_size, st.st_mtime))
        if len(entries) >= MAX_TREE_ENTRIES:
            break
    return [e.to_dict() for e in entries]


async def save_uploads(root: Path, uploads: list[UploadFile], subdir: str = "") -> list[str]:
    target_dir = safe_child(root, subdir) if subdir else root
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for up in uploads:
        name = safe_filename(up.filename or "file")
        dest = safe_child(target_dir, name)
        with dest.open("wb") as fh:
            while chunk := await up.read(UPLOAD_CHUNK):
                fh.write(chunk)
        await up.close()
        saved.append(dest.relative_to(root.resolve()).as_posix())
    return saved
