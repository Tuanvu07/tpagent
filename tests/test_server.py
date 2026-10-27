"""Web server: auth, sessions, files, WebSocket task + approval flow (fake provider, no network)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tpagent.llm.base import LLMResponse, ToolCall
from tpagent.llm.fake import FakeProvider

TOKEN = "test-token-123"


@pytest.fixture
def client(workdir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TPAGENT_PROVIDER", "fake")
    monkeypatch.setenv("TPAGENT_TOKEN", TOKEN)
    monkeypatch.setenv("TPAGENT_WORKSPACE", str(workdir / "workspace"))
    from tpagent.server import Settings, create_app

    settings = Settings.from_env()
    settings.config.sessions_dir = workdir / "sessions"
    settings.config.max_turns = 6
    with TestClient(create_app(settings)) as c:
        yield c


def _h() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _new_session(client: TestClient) -> str:
    r = client.post("/api/sessions", headers=_h())
    assert r.status_code == 201
    return r.json()["id"]


def _collect(ws, until: tuple[str, ...] = ("done", "error", "cancelled")) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        ev = ws.receive_json()
        events.append(ev)
        if ev["type"] in until:
            return events


def _script_provider(monkeypatch: pytest.MonkeyPatch, *responses: LLMResponse) -> None:
    import tpagent.core.agent as core

    monkeypatch.setattr(core, "make_provider", lambda name, cfg: FakeProvider(responses=list(responses)))


# --- auth ------------------------------------------------------------------------
def test_rejects_without_token(client: TestClient) -> None:
    assert client.get("/api/sessions").status_code == 401
    assert client.get("/api/sessions", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/me", params={"token": TOKEN}).status_code == 200
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/abc"):
            pass


def test_index_served_without_auth(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200 and "TPAgent" in r.text
    assert client.get("/static/app.js").status_code == 200


# --- sessions + files --------------------------------------------------------------
def test_create_list_delete_session(client: TestClient, workdir: Path) -> None:
    sid = _new_session(client)
    assert (workdir / "workspace" / sid).is_dir()
    listed = client.get("/api/sessions", headers=_h()).json()["sessions"]
    assert [s["id"] for s in listed] == [sid] and listed[0]["title"] == "(phiên mới)"
    assert client.get(f"/api/sessions/{sid}", headers=_h()).json()["messages"] == []
    assert client.get("/api/sessions/nope", headers=_h()).status_code == 404
    assert client.delete(f"/api/sessions/{sid}", headers=_h()).status_code == 200
    assert not (workdir / "workspace" / sid).exists()
    assert client.get("/api/sessions", headers=_h()).json()["sessions"] == []


def test_upload_list_download(client: TestClient, workdir: Path) -> None:
    sid = _new_session(client)
    files = [("files", ("a.txt", b"hello", "text/plain")), ("files", ("../evil.txt", b"x", "text/plain"))]
    r = client.post(f"/api/files/{sid}", headers=_h(), files=files)
    assert r.status_code == 201 and r.json()["saved"] == ["a.txt", "evil.txt"]
    assert not (workdir / "workspace" / "evil.txt").exists()
    names = [f["path"] for f in client.get(f"/api/files/{sid}", headers=_h()).json()["files"]]
    assert names == ["a.txt", "evil.txt"]
    r = client.get(f"/api/files/{sid}/download", headers=_h(), params={"path": "a.txt"})
    assert r.status_code == 200 and r.content == b"hello"
    assert "attachment" in r.headers["content-disposition"]
    r = client.get(f"/api/files/{sid}/download", params={"path": "a.txt", "token": TOKEN, "inline": "1"})
    assert r.status_code == 200 and "inline" in r.headers["content-disposition"]


def test_path_traversal_rejected(client: TestClient, workdir: Path) -> None:
    sid = _new_session(client)
    (workdir / "secret.txt").write_text("top secret")
    for bad in ("../../secret.txt", "/etc/passwd", "..%2F..%2Fsecret.txt"):
        r = client.get(f"/api/files/{sid}/download", headers=_h(), params={"path": bad})
        assert r.status_code in (400, 404), bad
        assert b"top secret" not in r.content
    assert client.get("/api/files/..%2F..", headers=_h()).status_code in (400, 404)


# --- websocket ---------------------------------------------------------------------
def test_ws_task_runs_to_done_and_persists(client: TestClient, workdir: Path) -> None:
    sid = _new_session(client)
    (workdir / "workspace" / sid / "notes.md").write_text("# ghi chú\nxin chào")
    with client.websocket_connect(f"/ws/{sid}?token={TOKEN}") as ws:
        assert ws.receive_json()["type"] == "status"
        ws.send_json({"type": "task", "text": "đọc notes.md", "tier": "cheap", "auto_approve": False})
        events = _collect(ws)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert "tool_call" in kinds and "tool_result" in kinds and "cost" in kinds
    assert "xin chào" in next(e for e in events if e["type"] == "tool_result")["text"]  # read from session dir
    assert "Done (fake provider" in events[-1]["text"]
    saved = json.loads((workdir / "sessions" / f"{sid}.json").read_text())
    assert saved["messages"][0]["content"] == "đọc notes.md"
    detail = client.get(f"/api/sessions/{sid}", headers=_h()).json()
    assert detail["messages"][0]["role"] == "user" and detail["running"] is False
    assert client.get("/api/sessions", headers=_h()).json()["sessions"][0]["title"] == "đọc notes.md"


def test_ws_approval_flow(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _script_provider(
        monkeypatch,
        LLMResponse(tool_calls=[ToolCall("c1", "bash", {"command": "rm -f missing-file.txt && echo hi"})], stop_reason="tool_use"),
        LLMResponse(text="xong"),
    )
    sid = _new_session(client)
    with client.websocket_connect(f"/ws/{sid}?token={TOKEN}") as ws:
        ws.receive_json()
        ws.send_json({"type": "task", "text": "xóa file", "auto_approve": False})
        events = _collect(ws, until=("approval_request",))
        req = events[-1]
        assert req["tool"] == "bash" and "rm -f" in req["args"]["command"]
        ws.send_json({"type": "approval_response", "id": req["id"], "approved": True, "always": False})
        events = _collect(ws)
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["text"].strip() == "hi" and not result["is_error"]
    assert events[-1]["type"] == "done" and events[-1]["text"] == "xong"


def test_ws_approval_denied_and_auto_approve(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _script_provider(
        monkeypatch,
        LLMResponse(tool_calls=[ToolCall("c1", "bash", {"command": "rm -f nothing.txt"})], stop_reason="tool_use"),
        LLMResponse(text="first"),
        LLMResponse(tool_calls=[ToolCall("c2", "bash", {"command": "rm -f nothing.txt; echo ok"})], stop_reason="tool_use"),
        LLMResponse(text="second"),
    )
    sid = _new_session(client)
    with client.websocket_connect(f"/ws/{sid}?token={TOKEN}") as ws:
        ws.receive_json()
        ws.send_json({"type": "task", "text": "a", "auto_approve": False})
        req = _collect(ws, until=("approval_request",))[-1]
        ws.send_json({"type": "approval_response", "id": req["id"], "approved": False})
        events = _collect(ws)
        assert "Permission denied" in next(e for e in events if e["type"] == "tool_result")["text"]
        ws.send_json({"type": "task", "text": "b", "auto_approve": True})
        events = _collect(ws)
    kinds = [e["type"] for e in events]
    assert "approval_request" not in kinds
    assert next(e for e in events if e["type"] == "tool_result")["text"].strip() == "ok"


def test_ws_question_flow(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _script_provider(
        monkeypatch,
        LLMResponse(tool_calls=[ToolCall("q1", "ask_user", {"question": "Màu nào?", "options": ["đỏ", "xanh"]})], stop_reason="tool_use"),
        LLMResponse(text="ok màu"),
    )
    sid = _new_session(client)
    with client.websocket_connect(f"/ws/{sid}?token={TOKEN}") as ws:
        ws.receive_json()
        ws.send_json({"type": "task", "text": "hỏi tôi", "auto_approve": False})
        q = _collect(ws, until=("question",))[-1]
        assert q["question"] == "Màu nào?" and q["options"] == ["đỏ", "xanh"]
        ws.send_json({"type": "answer", "id": q["id"], "text": "xanh"})
        events = _collect(ws)
    assert next(e for e in events if e["type"] == "tool_result")["text"] == "xanh"


def test_ws_cancel_and_busy(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _script_provider(
        monkeypatch,
        LLMResponse(tool_calls=[ToolCall("c1", "bash", {"command": "rm -f x.txt"})], stop_reason="tool_use"),
        LLMResponse(text="never"),
    )
    sid = _new_session(client)
    with client.websocket_connect(f"/ws/{sid}?token={TOKEN}") as ws:
        ws.receive_json()
        ws.send_json({"type": "task", "text": "slow", "auto_approve": False})
        _collect(ws, until=("approval_request",))
        ws.send_json({"type": "task", "text": "again", "auto_approve": False})
        assert "Đang chạy" in ws.receive_json()["message"]
        ws.send_json({"type": "cancel"})
        assert _collect(ws)[-1]["type"] == "cancelled"
    detail = client.get(f"/api/sessions/{sid}", headers=_h()).json()
    assert detail["running"] is False and detail["messages"][-1]["role"] == "tool"


def test_sessions_have_isolated_workspaces(client: TestClient, workdir: Path) -> None:
    ids = [_new_session(client) for _ in range(3)]
    for sid in ids:
        (workdir / "workspace" / sid / "f.md").write_text(f"content-of-{sid}")
    for sid in ids:  # agents for earlier sessions stay alive; each run must see its own dir
        with client.websocket_connect(f"/ws/{sid}?token={TOKEN}") as ws:
            ws.receive_json()
            ws.send_json({"type": "task", "text": "đọc f.md", "auto_approve": False})
            events = _collect(ws)
        assert f"content-of-{sid}" in next(e for e in events if e["type"] == "tool_result")["text"]
