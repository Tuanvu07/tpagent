"""Context management: token estimation, tool-output truncation and
summarization of old history so the prompt stays under the cheap tier."""
from __future__ import annotations

import threading

from tpagent.llm.base import LLMProvider, Message
from tpagent.tools.base import truncate

HARD_LIMIT_TOKENS = 100_000  # Haiku cheap-tier boundary
TOOL_OUTPUT_CHARS = 30_000
IMAGE_TOKENS = 1_600  # rough cost of one screenshot
KEEP_LAST_TURNS = 6  # verbatim tail (assistant turns) kept after summarizing

_ENC = None  # tiktoken encoder, loaded in the background; None -> len/4 fallback


def _load_encoder() -> None:
    """tiktoken downloads its BPE file on first use; never block the agent on that."""
    global _ENC  # noqa: PLW0603
    try:
        import tiktoken

        _ENC = tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - optional dependency / offline
        _ENC = None


threading.Thread(target=_load_encoder, daemon=True).start()


def count_tokens(text: str) -> int:
    if _ENC is None:
        return max(1, len(text) // 4)
    try:
        return len(_ENC.encode(text, disallowed_special=()))
    except Exception:  # noqa: BLE001
        return max(1, len(text) // 4)


def message_tokens(m: Message) -> int:
    total = count_tokens(str(m.get("content") or "")) + 4
    for call in m.get("tool_calls") or []:
        total += count_tokens(str(call))
    if m.get("image_png"):
        total += IMAGE_TOKENS
    return total


def estimate_tokens(messages: list[Message], system: str = "", tools_schema_chars: int = 0) -> int:
    return count_tokens(system) + tools_schema_chars // 4 + sum(message_tokens(m) for m in messages)


def truncate_tool_output(text: str, limit: int = TOOL_OUTPUT_CHARS) -> str:
    return truncate(text, limit)


def _split_point(messages: list[Message], keep_turns: int) -> int:
    """Index where the verbatim tail starts: the last `keep_turns` assistant
    turns plus their tool results. Index 0 (the task) is never summarized."""
    seen = 0
    for i in range(len(messages) - 1, 0, -1):
        if messages[i]["role"] == "assistant":
            seen += 1
            if seen >= keep_turns:
                return i
    return 1


def _render(messages: list[Message]) -> str:
    parts = []
    for m in messages:
        role = m["role"]
        body = str(m.get("content") or "")
        if role == "assistant" and m.get("tool_calls"):
            body += "\nCALLS: " + ", ".join(f"{c['name']}({c.get('args')})" for c in m["tool_calls"])
        if role == "tool":
            body = f"[{m.get('name', 'tool')}] " + body[:1_500]
        parts.append(f"{role.upper()}: {body}")
    return "\n\n".join(parts)


SUMMARY_PROMPT = (
    "Summarize the conversation below for an AI coding agent that will continue the task. "
    "Keep: the goal, decisions made, files read/edited (with paths), key facts and errors, "
    "and what remains to do. Be dense and factual, under 600 words.\n\n"
)


async def summarize_history(
    messages: list[Message], provider: LLMProvider, model: str, keep_turns: int = KEEP_LAST_TURNS
) -> list[Message]:
    """Replace old messages with one summary user message; keep task + tail."""
    split = _split_point(messages, keep_turns)
    if split <= 1:
        return messages
    old = messages[1:split]
    try:
        resp = await provider.chat(
            [{"role": "user", "content": SUMMARY_PROMPT + _render(old)}], [], "You summarize agent transcripts.", model, 1_500
        )
        summary = resp.text.strip() or _render(old)[:4_000]
    except Exception as e:  # noqa: BLE001 - fall back to a mechanical digest
        summary = f"(summary model failed: {e})\n" + _render(old)[:4_000]
    summary_msg: Message = {"role": "user", "content": f"[Summary of earlier work]\n{summary}"}
    tail = _drop_orphan_tool_results(messages[split:])
    return [messages[0], summary_msg, *tail]


def _drop_orphan_tool_results(tail: list[Message]) -> list[Message]:
    """A tail must not start with tool results whose tool_use was summarized."""
    i = 0
    while i < len(tail) and tail[i]["role"] == "tool":
        i += 1
    return tail[i:]


def shrink_old_tool_outputs(messages: list[Message], keep_last: int = 4, limit: int = 2_000) -> None:
    """In place: truncate tool outputs older than the last `keep_last` of them.
    Cheap first line of defence before summarizing."""
    tool_idx = [i for i, m in enumerate(messages) if m["role"] == "tool"]
    for i in tool_idx[:-keep_last] if keep_last else tool_idx:
        m = messages[i]
        if len(str(m.get("content") or "")) > limit:
            m["content"] = truncate(str(m["content"]), limit)
        m["image_png"] = None


class ContextManager:
    def __init__(self, limit_tokens: int, summarizer: LLMProvider | None, summary_model: str) -> None:
        self.limit = min(limit_tokens, HARD_LIMIT_TOKENS - 10_000)
        self.summarizer = summarizer
        self.summary_model = summary_model
        self.compactions = 0

    async def fit(self, messages: list[Message], system: str, tools_schema_chars: int) -> list[Message]:
        """Return a message list under the limit (may be the same list)."""
        if estimate_tokens(messages, system, tools_schema_chars) <= self.limit:
            return messages
        shrink_old_tool_outputs(messages)
        if estimate_tokens(messages, system, tools_schema_chars) <= self.limit or self.summarizer is None:
            return messages
        self.compactions += 1
        compacted = await summarize_history(messages, self.summarizer, self.summary_model)
        if estimate_tokens(compacted, system, tools_schema_chars) > self.limit:
            shrink_old_tool_outputs(compacted, keep_last=1)  # tail still too fat: shrink all but the newest
        return compacted


__all__ = [
    "ContextManager", "count_tokens", "estimate_tokens", "shrink_old_tool_outputs",
    "summarize_history", "truncate_tool_output",
]
