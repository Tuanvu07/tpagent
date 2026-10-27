"""Subagent tools with a stub agent factory (no LLM, no core needed)."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tpagent.tools import subagent as S
from tpagent.tools.base import Tool


def _tool(name: str, tag: str) -> Tool:
    return Tool(name, f"{name} tool", {"type": "object", "properties": {}}, lambda: "ok", tags=[tag])


FAKE_POOL = [_tool("read_file", "files"), _tool("bash", "shell"), _tool("web_fetch", "web"),
             _tool("video_trim", "video"), *S.TOOLS]


class StubAgent:
    """Records what it was built with; `run` returns a report or recurses via spawn_subagent."""
    built: list["StubAgent"] = []

    def __init__(self, config: Any, tools: list[Tool], model: str, system_prompt: str, max_turns: int) -> None:
        self.tools, self.model, self.system_prompt, self.max_turns = tools, model, system_prompt, max_turns
        StubAgent.built.append(self)

    async def run(self, task: str) -> str:
        if task.startswith("recurse"):
            return await S.spawn_subagent(task)
        await asyncio.sleep(0.05)
        return f"report for: {task} (depth={S._depth.get()})"


@pytest.fixture(autouse=True)
def stub(monkeypatch: pytest.MonkeyPatch) -> None:
    StubAgent.built.clear()
    monkeypatch.setattr(S, "_all_tools", lambda: list(FAKE_POOL))
    monkeypatch.setattr(S, "CONFIG", {"fake": True})
    S.set_agent_factory(
        lambda config, enable_modules=None, model=None, tools=None, system_prompt=None, max_turns=None:
        StubAgent(config, tools or [], model or "", system_prompt or "", max_turns or 0))
    yield
    S.set_agent_factory(None)


def test_single_subagent_restricted_tools() -> None:
    out = asyncio.run(S.spawn_subagent("summarize repo", tools=["files", "bash"], model_tier="standard", max_turns=7))
    assert out == "report for: summarize repo (depth=1)"
    agent = StubAgent.built[-1]
    assert {t.name for t in agent.tools} == {"read_file", "bash"}
    assert agent.model == "standard" and agent.max_turns == 7
    assert agent.system_prompt == S.CHILD_SYSTEM_PROMPT


def test_children_never_get_subagent_tools() -> None:
    asyncio.run(S.spawn_subagent("x"))
    names = {t.name for t in StubAgent.built[-1].tools}
    assert "spawn_subagent" not in names and "spawn_subagents_parallel" not in names
    assert names == {"read_file", "bash", "web_fetch", "video_trim"}


def test_unknown_tool_name_and_bad_tier() -> None:
    with pytest.raises(ValueError, match="unknown tools"):
        asyncio.run(S.spawn_subagent("x", tools=["nope"]))
    assert "model_tier must be" in asyncio.run(S.spawn_subagent("x", model_tier="huge"))


def test_depth_guard() -> None:
    # depth 0 -> child (1) -> grandchild (2) -> great-grandchild blocked
    out = asyncio.run(S.spawn_subagent("recurse recurse deep"))
    assert "depth limit" in out
    assert len(StubAgent.built) == 2
    assert S._depth.get() == 0  # context restored


def test_factory_without_tools_kwarg() -> None:
    class Minimal:
        def __init__(self) -> None:
            self.tools: list[Tool] = []

        def run(self, task: str) -> str:  # sync run is also accepted
            return f"{len(self.tools)} tools"

    S.set_agent_factory(lambda config, model=None: Minimal())
    assert asyncio.run(S.spawn_subagent("x", tools=["video"])) == "1 tools"


def test_result_object_and_truncation() -> None:
    class Obj:
        text = "y" * 20_000

    class A:
        async def run(self, task: str) -> Obj:
            return Obj()

    S.set_agent_factory(lambda config, **kw: A())
    out = asyncio.run(S.spawn_subagent("x"))
    assert "[truncated" in out and len(out) < 9_000


def test_parallel_gather_runs_concurrently() -> None:
    tasks = [{"task": f"job {i}", "tools": ["files"], "tier": "cheap"} for i in range(5)]
    loop = asyncio.new_event_loop()
    start = loop.time()
    out = loop.run_until_complete(S.spawn_subagents_parallel(tasks))
    elapsed = loop.time() - start
    loop.close()
    assert elapsed < 0.2  # 5 x 50ms sleeps overlapped, not serial
    for i in range(5):
        assert f"## Subagent {i + 1}: job {i}" in out and f"report for: job {i}" in out


def test_parallel_isolates_errors() -> None:
    out = asyncio.run(S.spawn_subagents_parallel([{"task": "ok"}, {"task": "bad", "tools": ["zzz"]}]))
    assert "report for: ok" in out and "Error: ValueError" in out
    assert "tasks list is empty" in asyncio.run(S.spawn_subagents_parallel([]))


def test_registry_and_tool_call() -> None:
    assert [t.name for t in S.TOOLS] == ["spawn_subagent", "spawn_subagents_parallel"]
    assert all(t.tags == ["subagent"] for t in S.TOOLS)
    res = asyncio.run(S.TOOLS[0].call(task="via Tool.call"))
    assert not res.is_error and "report for: via Tool.call" in res.text
