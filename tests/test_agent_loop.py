"""Agent loop with a scripted FakeProvider: runs tools, stops, tracks cost."""
from __future__ import annotations

import json

from tpagent.core.agent import Agent
from tpagent.core.permissions import PermissionManager
from tpagent.llm.base import LLMResponse, ToolCall, Usage
from tpagent.llm.fake import FakeProvider
from tpagent.tools import load_tools


def _scripted(*responses: LLMResponse) -> FakeProvider:
    return FakeProvider(responses=list(responses))


async def test_loop_runs_tool_then_stops(config, workdir):
    (workdir / "hello.txt").write_text("line one\nline two\n")
    provider = _scripted(
        LLMResponse(text="reading", tool_calls=[ToolCall("c1", "read_file", {"path": "hello.txt"})],
                    usage=Usage(100, 10), stop_reason="tool_use"),
        LLMResponse(text="The file has two lines.", usage=Usage(200, 20)),
    )
    events: list[tuple[str, dict]] = []
    agent = Agent(config=config, provider=provider, tools=load_tools(), model="fake")
    answer = await agent.run("read hello.txt", on_event=lambda k, d: events.append((k, d)))

    assert answer == "The file has two lines."
    assert len(provider.calls) == 2
    tool_msgs = [m for m in agent.messages if m["role"] == "tool"]
    assert len(tool_msgs) == 1 and "line two" in tool_msgs[0]["content"]
    kinds = [k for k, _ in events]
    assert kinds.count("tool_call") == 1 and kinds.count("tool_result") == 1 and kinds[-1] == "done"
    assert agent.cost.per_model["fake"].input_tokens == 300


async def test_unknown_tool_reports_error_and_continues(config):
    provider = _scripted(
        LLMResponse(tool_calls=[ToolCall("c1", "nope", {})], stop_reason="tool_use"),
        LLMResponse(text="ok"),
    )
    agent = Agent(config=config, provider=provider, tools=load_tools(), model="fake")
    await agent.run("x")
    tool_msg = next(m for m in agent.messages if m["role"] == "tool")
    assert tool_msg["is_error"] and "Unknown tool" in tool_msg["content"]


async def test_max_turns_stops_loop(config):
    config.max_turns = 2
    provider = FakeProvider(responses=[
        LLMResponse(tool_calls=[ToolCall(f"c{i}", "list_dir", {})], stop_reason="tool_use") for i in range(5)
    ])
    agent = Agent(config=config, provider=provider, tools=load_tools(), model="fake")
    answer = await agent.run("loop forever")
    assert "max_turns" in answer and len(provider.calls) == 2


async def test_dangerous_tool_denied_when_non_interactive(config, workdir):
    provider = _scripted(
        LLMResponse(tool_calls=[ToolCall("c1", "bash", {"command": "rm -rf build"})], stop_reason="tool_use"),
        LLMResponse(text="done"),
    )
    pm = PermissionManager(auto_approve=False, interactive=False)
    agent = Agent(config=config, provider=provider, tools=load_tools(), model="fake", permissions=pm)
    await agent.run("delete build")
    tool_msg = next(m for m in agent.messages if m["role"] == "tool")
    assert "Permission denied" in tool_msg["content"]
    assert pm.denied_log


async def test_safe_bash_runs_without_prompt(config):
    provider = _scripted(
        LLMResponse(tool_calls=[ToolCall("c1", "bash", {"command": "echo hi"})], stop_reason="tool_use"),
        LLMResponse(text="done"),
    )
    pm = PermissionManager(auto_approve=False, interactive=False)
    agent = Agent(config=config, provider=provider, tools=load_tools(), model="fake", permissions=pm)
    await agent.run("say hi")
    assert next(m for m in agent.messages if m["role"] == "tool")["content"] == "hi"


async def test_parallel_read_tools_and_session_saved(config, workdir):
    (workdir / "a.txt").write_text("A")
    (workdir / "b.txt").write_text("B")
    provider = _scripted(
        LLMResponse(tool_calls=[ToolCall("c1", "read_file", {"path": "a.txt"}),
                                ToolCall("c2", "read_file", {"path": "b.txt"})], stop_reason="tool_use"),
        LLMResponse(text="done"),
    )
    agent = Agent(config=config, provider=provider, tools=load_tools(), model="fake")
    await agent.run("read both")
    ids = [m["tool_call_id"] for m in agent.messages if m["role"] == "tool"]
    assert ids == ["c1", "c2"]
    saved = json.loads((config.sessions_dir / f"{agent.session_id}.json").read_text())
    assert saved["messages"][0]["content"] == "read both"


async def test_default_fake_script_reads_then_answers(config, workdir):
    (workdir / "README.md").write_text("# hi")
    agent = Agent(config=config, provider=FakeProvider(), tools=load_tools(), model="fake")
    answer = await agent.run("summarize README.md")
    assert "Done (fake provider" in answer
