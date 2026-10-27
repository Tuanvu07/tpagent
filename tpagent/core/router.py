"""Model routing (cheap/standard/strong) and cost tracking."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from tpagent.llm.base import Usage

TIERS = ("cheap", "standard", "strong")

# USD per 1M tokens: (input, output). Optional "long" key for >100k prompts.
PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "claude-haiku-5-5": {"base": (0.10, 0.50), "long": (0.50, 2.50)},
    "claude-sonnet-5-5": {"base": (2.00, 10.00)},
    "claude-opus-5-5": {"base": (4.00, 20.00)},
    "claude-haiku-4-5": {"base": (1.00, 5.00)},
    "deepseek-chat": {"base": (0.22, 0.66)},
    "deepseek-reasoner": {"base": (0.22, 0.66)},
    "qwen3.7-flash": {"base": (0.03, 0.13)},
    "qwen3.8-flash": {"base": (0.15, 0.47)},
    "gemini-3-flash": {"base": (0.50, 3.00)},
    "gemini-3.1-flash-lite": {"base": (0.25, 1.50)},
    "gpt-5-mini": {"base": (0.25, 2.00)},
    "ollama": {"base": (0.0, 0.0)},
    "fake": {"base": (0.0, 0.0)},
}
APPROXIMATE_PRICES = {"gpt-5-mini"}
LONG_PROMPT_THRESHOLD = 100_000
CACHE_READ_DISCOUNT = 0.1  # cached input tokens cost ~10% of normal input

STRONG_KEYWORDS = (
    "refactor", "architecture", "architect", "redesign", "debug", "race condition", "deadlock",
    "memory leak", "migrate", "migration", "security audit", "performance", "optimi", "concurren",
    "multi-file", "across the codebase", "whole project", "kiến trúc", "tái cấu trúc", "gỡ lỗi",
)
CHEAP_KEYWORDS = (
    "rename", "typo", "format", "list", "show", "print", "what is", "explain", "read", "cat ",
    "translate", "summarize", "summary", "đổi tên", "liệt kê", "dịch", "tóm tắt", "là gì",
)
FILE_PATTERN = re.compile(r"[\w./-]+\.[a-zA-Z]{1,5}\b")


def classify(task_text: str) -> str:
    """Cheap heuristic tier classifier (no LLM call)."""
    text = task_text.lower()
    n_files = len(set(FILE_PATTERN.findall(text)))
    if any(k in text for k in STRONG_KEYWORDS) or n_files >= 4 or len(text) > 2_000:
        return "strong"
    if len(text) < 200 and n_files <= 1 and any(k in text for k in CHEAP_KEYWORDS):
        return "cheap"
    return "standard"


async def classify_with_llm(task_text: str, provider, model: str) -> str:  # type: ignore[no-untyped-def]
    """Optional LLM-based classifier using a cheap model; falls back to heuristics."""
    prompt = (
        "Classify the difficulty of this coding/automation task. Reply with exactly one word: "
        "cheap, standard, or strong.\n\nTask:\n" + task_text[:2_000]
    )
    try:
        resp = await provider.chat([{"role": "user", "content": prompt}], [], "You are a task router.", model, 10)
        word = resp.text.strip().lower().split()[0] if resp.text.strip() else ""
        return word if word in TIERS else classify(task_text)
    except Exception:  # noqa: BLE001 - network failure must never block the agent
        return classify(task_text)


def price_for(model: str, input_tokens: int) -> tuple[float, float]:
    entry = _lookup(model)
    if entry is None:
        return (0.0, 0.0)
    if input_tokens > LONG_PROMPT_THRESHOLD and "long" in entry:
        return entry["long"]
    return entry["base"]


def _lookup(model: str) -> dict[str, tuple[float, float]] | None:
    base = model.split("/")[-1].split(":")[0]  # strip "qwen/" or "ollama:" style prefixes
    if base in PRICING:
        return PRICING[base]
    return next((v for k, v in PRICING.items() if base.startswith(k)), None)


def is_price_known(model: str) -> bool:
    return _lookup(model) is not None


def cost_usd(model: str, usage: Usage) -> float:
    in_price, out_price = price_for(model, usage.input_tokens)
    fresh_in = max(usage.input_tokens - usage.cache_read_tokens, 0)
    cached = usage.cache_read_tokens * in_price * CACHE_READ_DISCOUNT
    return (fresh_in * in_price + cached + usage.output_tokens * out_price) / 1_000_000


@dataclass
class ModelUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class CostTracker:
    per_model: dict[str, ModelUsage] = field(default_factory=dict)

    def add(self, model: str, usage: Usage) -> float:
        mu = self.per_model.setdefault(model, ModelUsage())
        cost = cost_usd(model, usage)
        mu.calls += 1
        mu.input_tokens += usage.input_tokens
        mu.output_tokens += usage.output_tokens
        mu.cost_usd += cost
        return cost

    @property
    def total_usd(self) -> float:
        return sum(m.cost_usd for m in self.per_model.values())

    def summary(self) -> str:
        if not self.per_model:
            return "No model calls yet."
        lines = []
        for model, mu in self.per_model.items():
            flag = " (~approx)" if model.split("/")[-1] in APPROXIMATE_PRICES else ""
            flag = flag or ("" if is_price_known(model) else " (price unknown, counted $0)")
            lines.append(
                f"{model}: {mu.calls} calls, {mu.input_tokens:,} in / {mu.output_tokens:,} out, ${mu.cost_usd:.4f}{flag}"
            )
        lines.append(f"TOTAL: ${self.total_usd:.4f}")
        return "\n".join(lines)
