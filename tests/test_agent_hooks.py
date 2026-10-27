"""Agent-level wiring: approver + ask_user hooks, streaming events, thinking budget,
system prompt sections (skills/memory), session resume, make_default_agent."""
from __future__ import annotations

from tpagent.core.agent import Agent, load_messages, make_default_agent
from tpagent.core.sessions import list_sessions
from tpagent.llm.base import LLMResponse, ToolCall
from tpagent.llm.fake import FakeProvider
from tpagent.tools import load_tools, tasks
from tpagent.tools.workspace import set_workspace


def _scripted(*responses: LLMResponse) -> FakeProvider:
    return FakeProvider(responses=list(responses))


async def test_approver_hook_gates_dangerous_calls(config):
    asked: list[str] = []

    async def approver(tool, args):
        asked.append(args["command"])
        return False

    provider = _scripted(
        LLMResponse(tool_calls=[ToolCall("c1", "bash", {"command": "rm -rf build"})], stop_reason="tool_use"),
        LLMResponse(text="done"),
    )
    agent = make_default_agent(config, enable_modules=[], model="fake", approver=approver)
    agent.provider = provider  # swap the factory's default fake for the scripted one
    await agent.run("delete build")
    assert asked == ["rm -rf build"]
    assert "Permission denied" in next(m for m in agent.messages if m["role"] == "tool")["content"]


async def test_ask_user_hook_reaches_tool_and_is_reset_after_run(config):
    from tpagent.tools.ask_user import CURRENT_ASK

    async def ask(question, options):
        return f"answer to {question} from {options}"

    provider = _scripted(
        LLMResponse(tool_calls=[ToolCall("c1", "ask_user", {"question": "Which?", "options": ["a", "b"]})],
                    stop_reason="tool_use"),
        LLMResponse(text="ok"),
    )
    agent = Agent(config=config, provider=provider, tools=load_tools(), model="fake", ask_user=ask)
    await agent.run("x")
    assert next(m for m in agent.messages if m["role"] == "tool")["content"] == "answer to Which? from ['a', 'b']"
    assert CURRENT_ASK.get() is None


async def test_without_ask_user_hook_model_is_told_to_decide(config):
    provider = _scripted(
        LLMResponse(tool_calls=[ToolCall("c1", "ask_user", {"question": "Which?"})], stop_reason="tool_use"),
        LLMResponse(text="ok"),
    )
    agent = Agent(config=config, provider=provider, tools=load_tools(), model="fake")
    await agent.run("x")
    assert "decide yourself" in next(m for m in agent.messages if m["role"] == "tool")["content"]


async def test_streaming_emits_text_deltas_and_marks_text_event(config):
    provider = _scripted(
        LLMResponse(text="I will list.", tool_calls=[ToolCall("c1", "list_dir", {})], stop_reason="tool_use"),
        LLMResponse(text="All done here."),
    )
    events: list[tuple[str, dict]] = []
    agent = Agent(config=config, provider=provider, tools=load_tools(), model="fake")
    answer = await agent.run("ls", on_event=lambda k, d: events.append((k, d)))
    deltas = "".join(d["text"] for k, d in events if k == "text_delta")
    assert deltas == "I will list.All done here." and answer == "All done here."
    text_events = [d for k, d in events if k == "text"]
    assert text_events == [{"text": "I will list.", "streamed": True}]
    assert provider.calls[0]["stream"] is True


async def test_non_streaming_provider_gets_plain_text_event(config):
    provider = _scripted(
        LLMResponse(text="step", tool_calls=[ToolCall("c1", "list_dir", {})], stop_reason="tool_use"),
        LLMResponse(text="end"),
    )
    provider.supports_streaming = False
    events: list[tuple[str, dict]] = []
    agent = Agent(config=config, provider=provider, tools=load_tools(), model="fake")
    await agent.run("ls", on_event=lambda k, d: events.append((k, d)))
    assert not [k for k, _ in events if k == "text_delta"]
    assert [d for k, d in events if k == "text"] == [{"text": "step", "streamed": False}]


async def test_thinking_budget_follows_tier_and_override(config):
    config.thinking = {"cheap": 0, "standard": 0, "strong": 4000}
    provider = _scripted(LLMResponse(text="a"), LLMResponse(text="b"), LLMResponse(text="c"), LLMResponse(text="d"))
    agent = Agent(config=config, provider=provider, tools=[], tier="strong")
    events: list[dict] = []
    await agent.run("hard", on_event=lambda k, d: events.append(d) if k == "start" else None)
    assert provider.calls[0]["thinking_budget"] == 4000 and events[0]["thinking_budget"] == 4000
    agent.thinking = False
    await agent.run("hard")
    assert provider.calls[1]["thinking_budget"] is None
    agent.tier, agent.thinking = "cheap", True
    await agent.run("easy")
    assert provider.calls[2]["thinking_budget"] == 4000  # forced on, tier had none -> default budget
    agent.thinking = None
    await agent.run("easy")
    assert provider.calls[3]["thinking_budget"] is None


def test_system_prompt_lists_skills_and_memory(config, workdir):
    from tpagent.tools.memory import memory_append

    agent = Agent(config=config, provider=FakeProvider(), tools=load_tools(), model="fake")
    prompt = agent.system()
    assert str(workdir.resolve()) in prompt
    assert "## Skills" in prompt and "- code-task:" in prompt and "## Memory" not in prompt
    memory_append("user likes short answers")
    prompt = agent.system()
    assert prompt.rstrip().endswith("## Memory\n- user likes short answers")
    custom = Agent(config=config, provider=FakeProvider(), tools=load_tools(), system_prompt="CUSTOM").system()
    assert custom.startswith("CUSTOM") and "## Memory" in custom


async def test_session_resume_drops_images(config):
    provider = _scripted(LLMResponse(text="first"))
    agent = Agent(config=config, provider=provider, tools=[], model="fake")
    await agent.run("hello")
    agent.messages.append({"role": "tool", "tool_call_id": "t", "name": "shot", "content": "img", "image_png": b"\x89",
                           "is_error": False})
    agent.save_session()
    restored = load_messages(config, agent.session_id)
    assert restored[0]["content"] == "hello" and restored[1]["content"] == "first"
    assert restored[2]["image_png"] is None and "image omitted" in restored[2]["content"]

    other = Agent(config=config, provider=_scripted(LLMResponse(text="again")), tools=[], model="fake")
    assert other.load_session(agent.session_id) == 3 and other.session_id == agent.session_id
    infos = list_sessions(config)
    assert infos[0].id == agent.session_id and infos[0].first_task == "hello" and infos[0].messages == 3


def test_make_default_agent_sets_workspace_and_hooks(config, tmp_path_factory):
    ws = tmp_path_factory.mktemp("agent_ws")
    try:
        async def ask(q, o):
            return "x"

        agent = make_default_agent(config, enable_modules=[], model="fake", workspace=ws, ask_user=ask,
                                   max_turns=3, system_prompt="SP")
        assert agent.workspace == ws.resolve() and agent.ask_user is ask and agent.max_turns == 3
        assert agent.permissions is not None and agent.permissions.approver is None
        assert agent.system().startswith("SP")
        assert {t.name for t in agent.tools} >= {"read_file", "bash", "task_create", "memory_read", "use_skill", "ask_user"}
        child = make_default_agent(config, enable_modules=[], model="cheap", tools=agent.tools[:2])
        assert child.tier == "cheap" and child.model is None and len(child.tools) == 2
        assert child.workspace == ws.resolve()  # children inherit the process workspace
    finally:
        set_workspace(None)
        tasks.reset()


async def test_concurrent_agents_keep_their_own_workspace(config, tmp_path_factory):
    import asyncio

    ws_a, ws_b = tmp_path_factory.mktemp("ws_a"), tmp_path_factory.mktemp("ws_b")
    (ws_a / "who.txt").write_text("A")
    (ws_b / "who.txt").write_text("B")

    def agent_for(ws):
        provider = _scripted(
            LLMResponse(tool_calls=[ToolCall("c1", "read_file", {"path": "who.txt"})], stop_reason="tool_use"),
            LLMResponse(text="ok"),
        )
        return Agent(config=config, provider=provider, tools=load_tools(), model="fake", workspace=ws)

    a, b = agent_for(ws_a), agent_for(ws_b)
    await asyncio.gather(a.run("x"), b.run("x"))
    read = lambda ag: next(m for m in ag.messages if m["role"] == "tool")["content"]  # noqa: E731
    assert read(a).endswith("A") and read(b).endswith("B")
