"""REST API: sessions and per-session files. All routes require the shared token."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse

from .auth import require_token
from .files import list_tree, safe_child, save_uploads, validate_session_id
from .runtime import RuntimeRegistry
from .sessions import SessionStore

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


def _store(request: Request) -> SessionStore:
    return request.app.state.store


def _registry(request: Request) -> RuntimeRegistry:
    return request.app.state.registry


def _require_session(store: SessionStore, session_id: str) -> str:
    validate_session_id(session_id)
    if not store.exists(session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không có phiên này")
    return session_id


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    cfg = request.app.state.settings.config
    return {"ok": True, "default_tier": cfg.default_tier, "tiers": cfg.tiers, "workspace": str(request.app.state.settings.workspace)}


@router.get("/sessions")
def list_sessions(request: Request) -> dict[str, Any]:
    registry = _registry(request)
    items = _store(request).list()
    for item in items:
        rt = registry.peek(item["id"])
        if rt is not None:
            item["cost_usd"], item["running"] = rt.cost_usd, rt.running
        else:
            item["running"] = False
    return {"sessions": items}


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(request: Request) -> dict[str, Any]:
    session_id = _store(request).create()
    return {"id": session_id}


@router.get("/sessions/{session_id}")
def get_session(request: Request, session_id: str) -> dict[str, Any]:
    store = _store(request)
    _require_session(store, session_id)
    rt = _registry(request).peek(session_id)
    if rt is not None:
        return {"id": session_id, "messages": rt.messages(), "cost_usd": rt.cost_usd, "running": rt.running}
    data = store.load(session_id) or {}
    return {"id": session_id, "messages": data.get("messages") or [], "cost_usd": float(data.get("cost_usd") or 0.0), "running": False}


@router.delete("/sessions/{session_id}")
def delete_session(request: Request, session_id: str) -> dict[str, Any]:
    store = _store(request)
    _require_session(store, session_id)
    _registry(request).drop(session_id)
    store.delete(session_id)
    return {"ok": True}


@router.get("/files/{session_id}")
def list_files(request: Request, session_id: str) -> dict[str, Any]:
    store = _store(request)
    _require_session(store, session_id)
    return {"files": list_tree(store.session_dir(session_id))}


@router.post("/files/{session_id}", status_code=status.HTTP_201_CREATED)
async def upload_files(request: Request, session_id: str, files: list[UploadFile], subdir: str = "") -> dict[str, Any]:
    store = _store(request)
    _require_session(store, session_id)
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Chưa chọn file")
    saved = await save_uploads(store.session_dir(session_id, create=True), files, subdir)
    return {"saved": saved}


@router.get("/files/{session_id}/download")
def download_file(request: Request, session_id: str, path: str) -> FileResponse:
    store = _store(request)
    _require_session(store, session_id)
    target = safe_child(store.session_dir(session_id), path)
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không có file này")
    inline = request.query_params.get("inline") == "1"
    return FileResponse(target, filename=target.name, content_disposition_type="inline" if inline else "attachment")
