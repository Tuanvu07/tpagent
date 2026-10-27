"""Message/tool conversion for Anthropic and OpenAI formats (no network)."""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace as NS

from tpagent.llm import anthropic_provider as ap
from tpagent.llm import openai_provider as op
from tpagent.tools import load_tools

HISTORY = [
    {"role": "user", "content": "do it"},
    {"role": "assistant", "content": "ok", "tool_calls": [{"id": "t1", "name": "read_file", "args": {"path": "a"}},
                                                        {"id": "t2", "name": "bash", "args": {"command": "ls"}}]},
    {"role": "tool", "tool_call_id": "t1", "name": "read_file", "content": "A", "image_png": None, "is_error": False},
    {"role": "tool", "tool_call_id": "t2", "name": "bash", "content": "boom", "image_png": b"\x89PNG", "is_error": True},
]


def test_anthropic_conversion_merges_tool_results_and_images():
    msgs = ap.convert_messages(HISTORY)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    blocks = msgs[1]["content"]
    assert blocks[0] == {"type": "text", "text": "ok"}
    assert blocks[1]["type"] == "tool_use" and blocks[1]["input"] == {"path": "a"}
    results = msgs[2]["content"]
    assert len(results) == 2 and results[1]["is_error"] is True
    img = results[1]["content"][1]
    assert img["type"] == "image" and base64.b64decode(img["source"]["data"]) == b"\x89PNG"
    tools = ap.convert_tools(load_tools())
    assert tools[-1]["cache_control"] == {"type": "ephemeral"} and "input_schema" in tools[0]


def test_anthropic_parse_response():
    resp = NS(
        content=[NS(type="text", text="hi"), NS(type="tool_use", id="x", name="bash", input={"command": "ls"})],
        usage=NS(input_tokens=10, output_tokens=5, cache_creation_input_tokens=3, cache_read_input_tokens=2),
        stop_reason="tool_use", model="claude-haiku-5-5",
    )
    out = ap.parse_response(resp)
    assert out.text == "hi" and out.tool_calls[0].args == {"command": "ls"}
    assert out.usage.input_tokens == 13 and out.usage.cache_read_tokens == 2


def test_openai_conversion_uses_function_calls_and_data_uri():
    msgs = op.convert_messages(HISTORY, system="SYS")
    assert msgs[0] == {"role": "system", "content": "SYS"}
    asst = msgs[2]
    assert asst["tool_calls"][0]["function"]["name"] == "read_file"
    assert json.loads(asst["tool_calls"][1]["function"]["arguments"]) == {"command": "ls"}
    assert msgs[3] == {"role": "tool", "tool_call_id": "t1", "content": "A"}
    assert msgs[4]["role"] == "tool" and msgs[5]["role"] == "user"
    assert msgs[5]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    tools = op.convert_tools(load_tools())
    assert tools[0]["type"] == "function" and "parameters" in tools[0]["function"]


def test_openai_parse_response_handles_bad_json_args():
    resp = NS(
        choices=[NS(message=NS(content=None, tool_calls=[NS(id="c1", function=NS(name="bash", arguments="{not json"))]),
                    finish_reason="tool_calls")],
        usage=NS(prompt_tokens=7, completion_tokens=2, prompt_tokens_details=NS(cached_tokens=4)),
        model="deepseek-chat",
    )
    out = op.parse_response(resp)
    assert out.stop_reason == "tool_use" and out.tool_calls[0].args == {"_raw": "{not json"}
    assert out.usage.cache_read_tokens == 4 and out.text == ""
