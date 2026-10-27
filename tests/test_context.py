from tpagent.core.context import ContextManager, count_tokens, estimate_tokens, shrink_old_tool_outputs, summarize_history
from tpagent.llm.base import LLMResponse
from tpagent.llm.fake import FakeProvider


def _history(n_turns: int, tool_len: int = 5_000) -> list[dict]:
    msgs = [{"role": "user", "content": "task"}]
    for i in range(n_turns):
        msgs.append({"role": "assistant", "content": f"step {i}", "tool_calls": [{"id": f"c{i}", "name": "bash", "args": {}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "name": "bash", "content": "x" * tool_len})
    return msgs


def test_count_tokens_reasonable():
    n = count_tokens("hello world " * 100)
    assert 150 < n < 400


def test_shrink_old_tool_outputs_keeps_recent():
    msgs = _history(6)
    shrink_old_tool_outputs(msgs, keep_last=2, limit=100)
    tools = [m for m in msgs if m["role"] == "tool"]
    assert all(len(m["content"]) < 300 for m in tools[:-2])
    assert all(len(m["content"]) == 5_000 for m in tools[-2:])


async def test_summarize_history_keeps_task_and_tail():
    msgs = _history(10)
    provider = FakeProvider(responses=[LLMResponse(text="SUMMARY TEXT")])
    out = await summarize_history(msgs, provider, "fake", keep_turns=3)
    assert out[0]["content"] == "task"
    assert out[1]["content"].startswith("[Summary of earlier work]\nSUMMARY TEXT")
    assert out[2]["role"] == "assistant" and out[2]["content"] == "step 7"
    assert len(out) == 2 + 6


async def test_context_manager_fits_under_limit():
    msgs = _history(30, tool_len=20_000)
    provider = FakeProvider(responses=[LLMResponse(text="short summary")])
    cm = ContextManager(limit_tokens=20_000, summarizer=provider, summary_model="fake")
    before = estimate_tokens(msgs)
    out = await cm.fit(msgs, "sys", 0)
    assert before > 20_000 and estimate_tokens(out) < 20_000
    assert cm.compactions == 1
