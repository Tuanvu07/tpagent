"""Configuration: config.yaml (cwd, then ~/.tpagent/) overridden by env vars."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# provider name -> (env var for key, default base_url, default model)
PROVIDER_DEFAULTS: dict[str, dict[str, str | None]] = {
    "anthropic": {"env": "ANTHROPIC_API_KEY", "base_url": None, "model": "claude-haiku-5-5"},
    "openai": {"env": "OPENAI_API_KEY", "base_url": None, "model": "gpt-5-mini"},
    "deepseek": {"env": "DEEPSEEK_API_KEY", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
    "qwen": {
        "env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.7-flash",
    },
    "gemini": {
        "env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-3-flash",
    },
    "openrouter": {"env": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1", "model": "qwen/qwen3.7-flash"},
    "ollama": {"env": "OLLAMA_HOST", "base_url": "http://localhost:11434/v1", "model": "qwen3:8b"},
    "fake": {"env": None, "base_url": None, "model": "fake"},
}

# "Claude Max" profile: all tiers on Claude. Haiku handles cheap chores
# (subagents, summaries), Sonnet is the daily driver, Opus for hard problems.
DEFAULT_TIERS: dict[str, str] = {
    "cheap": "claude-haiku-5-5",
    "standard": "claude-sonnet-5-5",
    "strong": "claude-opus-5-5",
}

# All tool modules on by default — like Claude Code + Cowork in one.
DEFAULT_ENABLED_TOOLS: list[str] = ["browser", "computer", "video", "subagent"]

# Extended-thinking budget (tokens) per tier; 0 = off. Only Anthropic models use it.
DEFAULT_THINKING: dict[str, int] = {"cheap": 0, "standard": 0, "strong": 4000}

# model name prefix -> provider name (used when a tier names a model, not a provider)
MODEL_PREFIX_PROVIDER: list[tuple[str, str]] = [
    ("claude", "anthropic"),
    ("deepseek", "deepseek"),
    ("qwen/", "openrouter"),
    ("qwen", "qwen"),
    ("gemini", "gemini"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("fake", "fake"),
]


@dataclass
class ProviderConfig:
    name: str
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


@dataclass
class Config:
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    tiers: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TIERS))
    default_provider: str | None = None  # None -> inferred from the tier's model
    default_tier: str = "standard"
    max_turns: int = 40
    context_limit_tokens: int = 80_000
    max_output_tokens: int = 8_000
    auto_approve: bool = False
    safe_commands_auto: bool = True  # bash: prompt only for destructive commands
    allow_outside_cwd: bool = False
    enabled_tools: list[str] = field(default_factory=lambda: list(DEFAULT_ENABLED_TOOLS))
    thinking: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_THINKING))
    sessions_dir: Path = field(default_factory=lambda: Path.home() / ".tpagent" / "sessions")

    def provider_for_model(self, model: str) -> str:
        """Pick a provider name for a model id (explicit `provider/model` wins)."""
        for p in self.providers:
            if model.startswith(f"{p}:"):
                return p
        for prefix, provider in MODEL_PREFIX_PROVIDER:
            if model.startswith(prefix):
                return provider
        return self.default_provider or "anthropic"

    def resolve_model(self, model_or_tier: str) -> tuple[str, str]:
        """Return (provider_name, model) for a tier name or a model id."""
        model = self.tiers.get(model_or_tier, model_or_tier)
        if ":" in model and model.split(":", 1)[0] in PROVIDER_DEFAULTS:
            provider, model = model.split(":", 1)
            return provider, model
        return self.provider_for_model(model), model

    def thinking_budget(self, tier: str | None) -> int:
        """Thinking budget for a tier (0 when the tier is unknown or thinking is off)."""
        return int(self.thinking.get(tier or "", 0) or 0)

    def provider(self, name: str) -> ProviderConfig:
        if name not in self.providers:
            self.providers[name] = _provider_from_env(name, {})
        return self.providers[name]


def _find_config_file(explicit: str | Path | None = None) -> Path | None:
    candidates = [Path(explicit)] if explicit else []
    candidates += [Path.cwd() / "config.yaml", Path.home() / ".tpagent" / "config.yaml"]
    return next((p for p in candidates if p.is_file()), None)


def _provider_from_env(name: str, raw: dict[str, Any]) -> ProviderConfig:
    defaults = PROVIDER_DEFAULTS.get(name, {"env": None, "base_url": None, "model": None})
    env_name = defaults["env"]
    env_value = os.environ.get(env_name) if env_name else None
    api_key = raw.get("api_key") or env_value
    base_url = raw.get("base_url") or defaults["base_url"]
    if name == "ollama" and env_value:  # OLLAMA_HOST is a host, not a key
        api_key, base_url = "ollama", env_value.rstrip("/") + "/v1"
    return ProviderConfig(name=name, api_key=api_key, base_url=base_url, model=raw.get("model") or defaults["model"])


def load_config(path: str | Path | None = None) -> Config:
    """Load config.yaml (if any) and apply env overrides."""
    raw: dict[str, Any] = {}
    file = _find_config_file(path)
    if file:
        raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}

    cfg = Config()
    raw_providers = raw.get("providers") or {}
    for name in set(PROVIDER_DEFAULTS) | set(raw_providers):
        cfg.providers[name] = _provider_from_env(name, raw_providers.get(name) or {})

    cfg.tiers.update(raw.get("tiers") or {})
    cfg.default_provider = os.environ.get("TPAGENT_PROVIDER") or raw.get("default_provider")
    cfg.default_tier = raw.get("default_tier", cfg.default_tier)
    cfg.max_turns = int(raw.get("max_turns", cfg.max_turns))
    cfg.context_limit_tokens = int(raw.get("context_limit_tokens", cfg.context_limit_tokens))
    cfg.max_output_tokens = int(raw.get("max_output_tokens", cfg.max_output_tokens))
    cfg.auto_approve = bool(raw.get("auto_approve", cfg.auto_approve))
    cfg.safe_commands_auto = bool(raw.get("safe_commands_auto", cfg.safe_commands_auto))
    cfg.allow_outside_cwd = bool(raw.get("allow_outside_cwd", cfg.allow_outside_cwd))
    if "enabled_tools" in raw:
        cfg.enabled_tools = list(raw.get("enabled_tools") or [])
    env_tools = os.environ.get("TPAGENT_ENABLED_TOOLS")
    if env_tools is not None:  # "" disables all optional modules
        cfg.enabled_tools = [t.strip() for t in env_tools.split(",") if t.strip()]
    cfg.thinking.update({k: int(v) for k, v in (raw.get("thinking") or {}).items()})
    if raw.get("sessions_dir"):
        cfg.sessions_dir = Path(raw["sessions_dir"]).expanduser()
    if cfg.default_provider == "fake":
        cfg.tiers = {t: "fake" for t in cfg.tiers}
    return cfg
