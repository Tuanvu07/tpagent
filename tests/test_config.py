from tpagent.config import load_config


def test_env_overrides_and_resolution(workdir, monkeypatch):
    (workdir / "config.yaml").write_text(
        "tiers:\n  cheap: qwen/qwen3.7-flash\n  strong: deepseek:deepseek-chat\nmax_turns: 7\n"
        "providers:\n  deepseek:\n    api_key: filekey\n"
    )
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qk")
    monkeypatch.delenv("TPAGENT_PROVIDER", raising=False)
    cfg = load_config()
    assert cfg.max_turns == 7
    assert cfg.providers["qwen"].api_key == "qk" and cfg.providers["deepseek"].api_key == "filekey"
    assert cfg.resolve_model("cheap") == ("openrouter", "qwen/qwen3.7-flash")
    assert cfg.resolve_model("strong") == ("deepseek", "deepseek-chat")
    assert cfg.resolve_model("standard") == ("anthropic", "claude-sonnet-5-5")
    assert cfg.resolve_model("gemini-3-flash") == ("gemini", "gemini-3-flash")


def test_fake_provider_env_forces_fake_tiers(workdir, monkeypatch):
    monkeypatch.setenv("TPAGENT_PROVIDER", "fake")
    cfg = load_config()
    assert cfg.resolve_model("strong") == ("fake", "fake")
