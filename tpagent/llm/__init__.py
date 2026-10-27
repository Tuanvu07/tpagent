"""LLM provider factory."""
from __future__ import annotations

from tpagent.config import Config

from .base import LLMProvider, LLMResponse, Message, ToolCall, Usage

OPENAI_COMPATIBLE = {"openai", "deepseek", "qwen", "gemini", "openrouter", "ollama"}


def make_provider(provider_name: str, config: Config) -> LLMProvider:
    """Build a provider by name using keys/base_url from config (env-overridden)."""
    pc = config.provider(provider_name)
    if provider_name == "fake":
        from .fake import FakeProvider

        return FakeProvider()
    if provider_name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        _require_key(pc.api_key, "ANTHROPIC_API_KEY")
        return AnthropicProvider(api_key=pc.api_key, base_url=pc.base_url)
    if provider_name in OPENAI_COMPATIBLE:
        from .openai_provider import OpenAIProvider

        if provider_name != "ollama":
            _require_key(pc.api_key, f"{provider_name.upper()}_API_KEY")
        return OpenAIProvider(api_key=pc.api_key, base_url=pc.base_url, name=provider_name)
    raise ValueError(f"Unknown provider: {provider_name}")


def _require_key(key: str | None, hint: str) -> None:
    if not key:
        raise RuntimeError(f"Missing API key: set {hint} or providers.<name>.api_key in config.yaml")


__all__ = ["LLMProvider", "LLMResponse", "Message", "ToolCall", "Usage", "make_provider"]
