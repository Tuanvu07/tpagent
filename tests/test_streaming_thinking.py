"""Anthropic streaming + extended-thinking round trip and OpenAI stream assembly (no network)."""
from __future__ import annotations

from types import SimpleNamespace as NS
from typing import Any

from tpagent.llm import anthropic_provider as ap
from tpagent.llm import openai_provider as op
from tpagent.llm.base import LLMResponse
from tpagent.tools import load_tools


class _FakeAnthropicClient:
    """Records create()/stream() kwargs; stream() yields scripted events then a final message."""

    def __init__(self, final: Any, events: list[Any] | None = None) -> None:
        self.final, self.events, self.kwargs = final, events or [], []
        self.messages = self

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs.append(kwargs)
        return self.final

    def stream(self, **kwargs: Any) -> "_FakeAnthropicClient":
        self.kwargs.append(kwargs)
        return self

    async def __aenter__(self) -> "_FakeAnthropicClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    def __aiter__(self):
        async def gen():
            for e in self.events:
                yield e

        return gen()

    async def get_final_message(self) -> Any:
        return self.final


def _provider(client: _FakeAnthropicClient) -> ap.AnthropicProvider:
    p = ap.AnthropicProvider.__new__(ap.AnthropicProvider)
    p._client = client
    return p


THINK = NS(type="thinking", thinking="Let me look.", signature="sig123")
REDACTED = NS(type="redacted_thinking", data="opaque")
TOOL_USE = NS(type="tool_use", id="t1", name="read_file", input={"path": "a"})
USAGE = NS(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0, cache_read_input_tokens=0)


async def test_thinking_blocks_round_trip_with_signature():
    final = NS(content=[THINK, REDACTED, NS(type="text", text="reading"), TOOL_USE], usage=USAGE,
               stop_reason="tool_use", model="claude-sonnet-5-5")
    client = _FakeAnthropicClient(final)
    resp = await _provider(client).chat([{"role": "user", "content": "go"}], load_tools(), "SYS", "claude-sonnet-5-5",
                                        max_tokens=1_000, thinking_budget=4_000)
    sent = client.kwargs[0]
    assert sent["thinking"] == {"type": "enabled", "budget_tokens": 4_000}
    assert sent["max_tokens"] > 4_000  # raised above the budget
    assert resp.thinking_blocks == [
        {"type": "thinking", "thinking": "Let me look.", "signature": "sig123"},
        {"type": "redacted_thinking", "data": "opaque"},
    ]
    assert resp.text == "reading" and resp.tool_calls[0].id == "t1"

    # Next request: thinking blocks come back first, verbatim, before text and tool_use.
    history = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": resp.text, "tool_calls": [c.to_dict() for c in resp.tool_calls],
         "thinking": resp.thinking_blocks},
        {"role": "tool", "tool_call_id": "t1", "name": "read_file", "content": "A", "image_png": None, "is_error": False},
    ]
    blocks = ap.convert_messages(history)[1]["content"]
    assert [b["type"] for b in blocks] == ["thinking", "redacted_thinking", "text", "tool_use"]
    assert blocks[0]["signature"] == "sig123" and blocks[1]["data"] == "opaque"


async def test_no_thinking_by_default_and_history_without_thinking_key():
    final = NS(content=[NS(type="text", text="hi")], usage=USAGE, stop_reason="end_turn", model="m")
    client = _FakeAnthropicClient(final)
    resp = await _provider(client).chat([{"role": "user", "content": "go"}], [], "SYS", "m")
    assert "thinking" not in client.kwargs[0] and client.kwargs[0]["max_tokens"] == 8_000
    assert resp.thinking_blocks == []
    blocks = ap.convert_messages([{"role": "assistant", "content": "x", "tool_calls": []}])[0]["content"]
    assert blocks == [{"type": "text", "text": "x"}]


async def test_anthropic_stream_delivers_deltas_and_final_message():
    final = NS(content=[NS(type="text", text="Hello world"), TOOL_USE], usage=USAGE, stop_reason="tool_use", model="m")
    events = [NS(type="thinking", thinking="hmm"), NS(type="text", text="Hello "), NS(type="input_json", partial_json="{"),
              NS(type="text", text="world"), NS(type="message_stop")]
    client = _FakeAnthropicClient(final, events)
    deltas: list[str] = []
    thoughts: list[str] = []

    async def on_delta(t: str) -> None:
        deltas.append(t)

    async def on_thinking(t: str) -> None:
        thoughts.append(t)

    resp = await _provider(client).chat([{"role": "user", "content": "go"}], load_tools(), "SYS", "m", stream=True,
                                        on_delta=on_delta, on_thinking=on_thinking)
    assert "".join(deltas) == "Hello world" == resp.text and thoughts == ["hmm"]
    assert resp.tool_calls[0].name == "read_file" and resp.usage.input_tokens == 10


async def test_openai_stream_assembles_text_tool_calls_and_usage():
    def chunk(content=None, tool_calls=None, finish=None, usage=None):
        delta = NS(content=content, tool_calls=tool_calls)
        return NS(model="deepseek-chat", usage=usage, choices=[NS(delta=delta, finish_reason=finish)])

    tc = lambda i, id=None, name=None, args="": NS(index=i, id=id, function=NS(name=name, arguments=args))  # noqa: E731
    chunks = [
        chunk(content="Sure, "), chunk(content="running."),
        chunk(tool_calls=[tc(0, id="c1", name="bash", args='{"comm')]),
        chunk(tool_calls=[tc(0, args='and": "ls"}'), tc(1, id="c2", name="read_file", args="{")]),
        chunk(tool_calls=[tc(1, args='"path": "a"}')], finish="tool_calls"),
        NS(model="deepseek-chat", usage=NS(prompt_tokens=20, completion_tokens=7, prompt_tokens_details=None), choices=[]),
    ]

    async def gen():
        for c in chunks:
            yield c

    deltas: list[str] = []

    async def on_delta(t: str) -> None:
        deltas.append(t)

    resp: LLMResponse = await op.assemble_stream(gen(), on_delta)
    assert resp.text == "Sure, running." and deltas == ["Sure, ", "running."]
    assert [(c.id, c.name, c.args) for c in resp.tool_calls] == [("c1", "bash", {"command": "ls"}),
                                                                 ("c2", "read_file", {"path": "a"})]
    assert resp.stop_reason == "tool_use" and resp.usage.input_tokens == 20 and resp.usage.output_tokens == 7
    assert resp.model == "deepseek-chat"
