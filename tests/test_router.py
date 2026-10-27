from tpagent.core.router import CostTracker, classify, cost_usd, price_for
from tpagent.llm.base import Usage


def test_classify_tiers():
    assert classify("rename variable foo to bar in utils.py") == "cheap"
    assert classify("Refactor the authentication architecture across services") == "strong"
    assert classify("touch a.py b.py c.py d.py and wire them together") == "strong"
    assert classify("Add a unit test for the parser function in parser.py") == "standard"
    assert classify("x" * 2_500) == "strong"


def test_pricing_and_long_prompt_tier():
    assert price_for("claude-haiku-5-5", 10_000) == (0.10, 0.50)
    assert price_for("claude-haiku-5-5", 150_000) == (0.50, 2.50)
    assert price_for("qwen/qwen3.7-flash", 10) == (0.03, 0.13)
    assert price_for("ollama:llama3", 10) == (0.0, 0.0)
    assert price_for("unknown-model", 10) == (0.0, 0.0)


def test_cost_math():
    # 50k input at $0.10/M + 10k output at $0.50/M = 0.005 + 0.005
    assert abs(cost_usd("claude-haiku-5-5", Usage(50_000, 10_000)) - 0.010) < 1e-9
    # >100k prompt switches to the long-prompt price (0.50/M)
    assert abs(cost_usd("claude-haiku-5-5", Usage(200_000, 0)) - 0.10) < 1e-9
    # cached tokens cost 10%
    u = Usage(input_tokens=1_000_000, output_tokens=0, cache_read_tokens=1_000_000)
    assert abs(cost_usd("deepseek-chat", u) - 0.022) < 1e-9


def test_cost_tracker_summary():
    t = CostTracker()
    t.add("claude-haiku-5-5", Usage(80_000, 0))  # $0.008
    t.add("claude-haiku-5-5", Usage(0, 20_000))  # $0.010
    assert abs(t.total_usd - 0.018) < 1e-9
    s = t.summary()
    assert "claude-haiku-5-5: 2 calls" in s and "TOTAL: $0.0180" in s
