"""WebSocket /ws/{session_id}: run tasks, stream agent events, relay approvals/answers.

Client -> server:
  {"type":"task","text":str,"tier":null|"cheap"|"standard"|"strong","auto_approve":bool}
  {"type":"approval_response","id":str,"approved":bool,"always":bool}
  {"type":"answer","id":str,"text":str}
  {"type":"cancel"}
Server -> client: agent events {"type":"start"|"cost"|"text"|"text_delta"|"tool_call"|"tool_result"|"done",...}
  plus {"type":"status"}, {"type":"approval_request"}, {"type":"question"}, {"type":"cancelled"}, {"type":"error"}.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from .auth import websocket_authorized
from .files import SESSION_ID_RE
from .runtime import RuntimeRegistry, SessionRuntime

router = APIRouter()
MAX_TASK_CHARS = 100_000


@router.websocket("/ws/{session_id}")
async def ws_session(ws: WebSocket, session_id: str) -> None:
    if not websocket_authorized(ws) or not SESSION_ID_RE.match(session_id):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    registry: RuntimeRegistry = ws.app.state.registry
    rt = registry.get(session_id)
    registry.store.session_dir(session_id, create=True)
    await ws.accept()
    lock = asyncio.Lock()

    async def sink(msg: dict[str, Any]) -> None:
        async with lock:
            await ws.send_json(msg)

    rt.sink = sink
    await rt.send({"type": "status", "session": session_id, "running": rt.running, "total_usd": rt.cost_usd})
    await rt.replay_pending()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await rt.send({"type": "error", "message": "JSON không hợp lệ"})
                continue
            await handle_message(rt, data if isinstance(data, dict) else {})
    except WebSocketDisconnect:
        pass
    finally:
        if rt.sink is sink:
            rt.sink = None


async def handle_message(rt: SessionRuntime, data: dict[str, Any]) -> None:
    kind = data.get("type")
    if kind == "task":
        text = str(data.get("text") or "").strip()[:MAX_TASK_CHARS]
        if not text:
            await rt.send({"type": "error", "message": "Chưa nhập nội dung"})
        elif not rt.start(text, data.get("tier"), bool(data.get("auto_approve"))):
            await rt.send({"type": "error", "message": "Đang chạy một việc khác, hãy chờ hoặc bấm Dừng"})
    elif kind == "approval_response":
        rt.resolve(str(data.get("id", "")), {"approved": bool(data.get("approved")), "always": bool(data.get("always"))})
    elif kind == "answer":
        rt.resolve(str(data.get("id", "")), {"text": str(data.get("text", ""))})
    elif kind == "cancel":
        if not rt.cancel():
            await rt.send({"type": "error", "message": "Không có việc nào đang chạy"})
    elif kind == "ping":
        await rt.send({"type": "pong"})
    else:
        await rt.send({"type": "error", "message": f"Loại tin không rõ: {kind}"})
