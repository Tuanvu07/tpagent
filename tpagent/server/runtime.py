"""One in-memory runtime per chat session: the Agent, the running task, and the
approval / question bridge between the agent loop and the browser WebSocket."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from tpagent.core.agent import Agent
from tpagent.core.router import TIERS

from .agent_factory import build_agent, restore_session
from .sessions import SessionStore
from .settings import APPROVAL_TIMEOUT_S, Settings

try:  # the core's workspace root is process-wide; pin it to the session before each run
    from tpagent.tools.workspace import set_workspace
except ImportError:  # older core: file tools follow cwd
    set_workspace = None  # type: ignore[assignment]

Sink = Callable[[dict[str, Any]], Awaitable[None]]
QUESTION_TIMEOUT_S = 6 * 3600
CANCELLED_TEXT = "(Người dùng đã dừng tác vụ)"


@dataclass
class Pending:
    id: str
    payload: dict[str, Any]
    future: asyncio.Future[dict[str, Any]]


class SessionRuntime:
    def __init__(self, session_id: str, store: SessionStore, settings: Settings, run_lock: asyncio.Lock) -> None:
        self.session_id = session_id
        self.store = store
        self.settings = settings
        self.run_lock = run_lock  # per session: Agent.run pins its own workspace via contextvar
        self.agent: Agent | None = None
        self.task: asyncio.Task[None] | None = None
        self.pending: dict[str, Pending] = {}
        self.sink: Sink | None = None
        self.always_allowed: set[str] = set()
        self.auto_approve = False

    # --- state ---------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    @property
    def cost_usd(self) -> float:
        if self.agent is not None:
            return self.agent.cost.total_usd
        return float((self.store.load(self.session_id) or {}).get("cost_usd") or 0.0)

    def messages(self) -> list[dict[str, Any]]:
        if self.agent is not None:
            return [jsonable(m) for m in self.agent.messages]
        return list((self.store.load(self.session_id) or {}).get("messages") or [])

    def ensure_agent(self) -> Agent:
        if self.agent is None:
            workspace = self.store.session_dir(self.session_id, create=True)
            agent = build_agent(self.settings.config, workspace, self.approve, self.ask_user)
            saved = self.store.load(self.session_id)
            if saved:
                restore_session(agent, saved)
            agent.session_id = self.session_id
            self.agent = agent
        return self.agent

    # --- output to the browser -------------------------------------------------
    async def send(self, msg: dict[str, Any]) -> None:
        if self.sink is None:
            return
        try:
            await self.sink(jsonable(msg))
        except Exception:  # noqa: BLE001 - socket went away; keep the agent running
            self.sink = None

    async def replay_pending(self) -> None:
        for p in list(self.pending.values()):
            await self.send(p.payload)

    # --- agent -> user bridge ----------------------------------------------------
    async def approve(self, tool: str, args: dict[str, Any]) -> bool:
        if self.auto_approve or tool in self.always_allowed:
            return True
        reply = await self._ask_client({"type": "approval_request", "tool": tool, "args": args}, APPROVAL_TIMEOUT_S)
        if reply is None:
            return False
        if reply.get("always") and reply.get("approved"):
            self.always_allowed.add(tool)
        return bool(reply.get("approved"))

    async def ask_user(self, question: str, options: list[str] | None = None) -> str:
        payload = {"type": "question", "question": question, "options": list(options or [])}
        reply = await self._ask_client(payload, QUESTION_TIMEOUT_S)
        if reply is None:
            return "(no answer from user; continue with your best judgement)"
        return str(reply.get("text", ""))

    async def _ask_client(self, payload: dict[str, Any], timeout: float) -> dict[str, Any] | None:
        pid = uuid.uuid4().hex[:10]
        payload = {**payload, "id": pid}
        pending = Pending(pid, payload, asyncio.get_running_loop().create_future())
        self.pending[pid] = pending
        await self.send(payload)
        try:
            return await asyncio.wait_for(pending.future, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self.pending.pop(pid, None)

    def resolve(self, pid: str, data: dict[str, Any]) -> bool:
        p = self.pending.get(pid)
        if p is None or p.future.done():
            return False
        p.future.set_result(data)
        return True

    # --- task lifecycle ------------------------------------------------------------
    def start(self, text: str, tier: str | None, auto_approve: bool) -> bool:
        if self.running:
            return False
        self.auto_approve = auto_approve
        self.task = asyncio.create_task(self._run(text, tier if tier in TIERS else None))
        return True

    def cancel(self) -> bool:
        if not self.running or self.task is None:
            return False
        self.task.cancel()
        return True

    async def _run(self, text: str, tier: str | None) -> None:
        try:
            if self.run_lock.locked():
                await self.send({"type": "queued", "message": "Đang chờ một phiên khác chạy xong…"})
            async with self.run_lock:
                agent = self.ensure_agent()
                if set_workspace is not None:
                    set_workspace(self.store.session_dir(self.session_id, create=True))
                agent.tier, agent.model = tier, None
                await agent.run(text, on_event=self._on_event)
        except asyncio.CancelledError:
            if self.agent is not None:
                _repair_after_cancel(self.agent)
                self.agent.save_session()
            await self.send({"type": "cancelled", "total_usd": self.cost_usd})
        except Exception as e:  # noqa: BLE001 - provider/network errors go to the browser
            await self.send({"type": "error", "message": f"{type(e).__name__}: {e}"})

    async def _on_event(self, kind: str, data: dict[str, Any]) -> None:
        await self.send({"type": kind, **data})


class RuntimeRegistry:
    def __init__(self, store: SessionStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings
        self._runtimes: dict[str, SessionRuntime] = {}

    def get(self, session_id: str) -> SessionRuntime:
        rt = self._runtimes.get(session_id)
        if rt is None:
            rt = self._runtimes[session_id] = SessionRuntime(session_id, self.store, self.settings, asyncio.Lock())
        return rt

    def peek(self, session_id: str) -> SessionRuntime | None:
        return self._runtimes.get(session_id)

    def drop(self, session_id: str) -> None:
        rt = self._runtimes.pop(session_id, None)
        if rt is not None:
            rt.cancel()


def _repair_after_cancel(agent: Agent) -> None:
    """Keep the transcript well-formed so the next turn can continue."""
    if not agent.messages:
        return
    last = agent.messages[-1]
    if last.get("role") == "assistant" and last.get("tool_calls"):
        for call in last["tool_calls"]:
            agent.messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "name": call.get("name", ""),
                                   "content": CANCELLED_TEXT, "image_png": None, "is_error": True})
    elif last.get("role") in ("user", "tool"):
        agent.messages.append({"role": "assistant", "content": CANCELLED_TEXT, "tool_calls": []})


def _json_default(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    return str(value)


def jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=_json_default, ensure_ascii=False))
