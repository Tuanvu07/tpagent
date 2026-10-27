"""The agent loop: model -> tool calls -> tool results -> model ... -> answer.

Events emitted through `on_event(kind, data)` (sync or async callback):
  start          {model, provider, session, tier, thinking_budget}
  text_delta     {text}                 streamed text fragment (providers with supports_streaming)
  thinking_delta {text}                 streamed extended-thinking fragment (Anthropic, when enabled)
  text           {text, streamed}       full intermediate assistant text of a turn that also called tools
  tool_call      {id, name, args}
  tool_result    {id, name, text, is_error, has_image}
  cost           {usage, cost_usd, total_usd}
  done           {text, total_usd, turns}
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from tpagent.config import Config
from tpagent.llm import make_provider
from tpagent.llm.base import LLMProvider, LLMResponse, Message, ToolCall
from tpagent.tools import load_tools
from tpagent.tools.ask_user import CURRENT_ASK, AskUserFn
from tpagent.tools.base import Tool, ToolResult
from tpagent.tools.files import allow_outside_cwd
from tpagent.tools.workspace import CURRENT_WORKSPACE, get_workspace, set_workspace

from .context import ContextManager, truncate_tool_output
from .permissions import Approver, PermissionManager
from .prompt import DEFAULT_SYSTEM_PROMPT, build_system_prompt
from .router import CostTracker, classify
from .sessions import list_sessions, load_messages, save_session

EventCallback = Callable[[str, dict[str, Any]], None | Awaitable[None]]
Emit = Callable[[str, dict[str, Any]], Awaitable[None]]

PARALLEL_SAFE_TAGS = {"read"}  # tools that may run concurrently with each other
FORCED_THINKING_BUDGET = 4_000  # used by `/think on` when the tier has no budget configured


@dataclass
class Agent:
    config: Config
    provider: LLMProvider
    tools: list[Tool]
    system_prompt: str | None = None  # custom base prompt; skills/memory sections are still appended
    model: str | None = None  # explicit model; None -> routed per task
    tier: str | None = None  # explicit tier; None -> classify()
    permissions: PermissionManager | None = None
    approver: Approver | None = None  # used only when `permissions` is not given
    ask_user: AskUserFn | None = None  # (question, options) -> answer; None -> model decides alone
    workspace: Path | None = None  # None -> current workspace root (cwd by default)
    thinking: bool | None = None  # None -> config per tier; True -> force on; False -> off
    max_turns: int | None = None  # None -> config.max_turns
    cost: CostTracker = field(default_factory=CostTracker)
    messages: list[Message] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6])
    providers_cache: dict[str, LLMProvider] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.permissions is None:
            self.permissions = PermissionManager(self.config.auto_approve, self.config.safe_commands_auto,
                                                 approver=self.approver)
        if self.workspace is None:
            self.workspace = get_workspace()
        self._tool_map = {t.name: t for t in self.tools}
        self._context = ContextManager(self.config.context_limit_tokens, None, "")

    # --- public --------------------------------------------------------------
    def system(self) -> str:
        return build_system_prompt(self.tools, self.workspace or get_workspace(), self.system_prompt)

    def pick_model(self, task: str) -> tuple[str, str]:
        """Return (provider_name, model) for this task."""
        if self.model:
            return self.config.resolve_model(self.model)
        return self.config.resolve_model(self.pick_tier(task))

    def pick_tier(self, task: str) -> str | None:
        """Tier used for routing/thinking; None when an explicit model bypasses tiers."""
        if self.model:
            return self.tier
        return self.tier or classify(task)

    def thinking_budget(self, tier: str | None) -> int:
        if self.thinking is False:
            return 0
        budget = self.config.thinking_budget(tier)
        return budget or (FORCED_THINKING_BUDGET if self.thinking else 0)

    async def run(self, task: str, on_event: EventCallback | None = None) -> str:
        emit = _emitter(on_event)
        ws_token = CURRENT_WORKSPACE.set(self.workspace)
        ask_token = CURRENT_ASK.set(self.ask_user) if self.ask_user is not None else None
        try:
            return await self._run(task, emit)
        finally:
            CURRENT_WORKSPACE.reset(ws_token)
            if ask_token is not None:
                CURRENT_ASK.reset(ask_token)

    async def _run(self, task: str, emit: Emit) -> str:
        tier = self.pick_tier(task)
        provider_name, model = self.pick_model(task)
        provider = self._provider_for(provider_name)
        budget = self.thinking_budget(tier)
        self._context.summarizer, self._context.summary_model = provider, self._cheap_model()
        await emit("start", {"model": model, "provider": provider_name, "session": self.session_id,
                             "tier": tier, "thinking_budget": budget})
        self.messages.append({"role": "user", "content": task})
        schema_chars = sum(len(json.dumps(t.schema)) for t in self.tools)
        max_turns = self.max_turns or self.config.max_turns
        final_text = ""
        turns = 0
        for turns in range(1, max_turns + 1):
            system = self.system()
            self.messages = await self._context.fit(self.messages, system, schema_chars)
            resp, streamed = await self._chat(provider, model, system, budget, emit)
            cost = self.cost.add(resp.model or model, resp.usage)
            await emit("cost", {"usage": resp.usage, "cost_usd": cost, "total_usd": self.cost.total_usd})
            assistant: Message = {"role": "assistant", "content": resp.text,
                                  "tool_calls": [c.to_dict() for c in resp.tool_calls]}
            if resp.thinking_blocks:
                assistant["thinking"] = resp.thinking_blocks
            self.messages.append(assistant)
            if not resp.tool_calls:
                final_text = resp.text
                break
            if resp.text:
                await emit("text", {"text": resp.text, "streamed": streamed})
            await self._run_tool_calls(resp.tool_calls, emit)
        else:
            final_text = f"(stopped: reached max_turns={max_turns})"
        self.save_session()
        await emit("done", {"text": final_text, "total_usd": self.cost.total_usd, "turns": turns})
        return final_text

    def save_session(self) -> Path | None:
        return save_session(self.config, self.session_id, self.messages, self.cost)

    def load_session(self, session_id: str) -> int:
        """Replace the conversation with a saved session (images omitted). Returns message count."""
        self.messages = load_messages(self.config, session_id)
        self.session_id = session_id
        return len(self.messages)

    def clear(self) -> None:
        self.messages.clear()

    # --- internals -----------------------------------------------------------
    async def _chat(
        self, provider: LLMProvider, model: str, system: str, budget: int, emit: Emit
    ) -> tuple[LLMResponse, bool]:
        """One model call; streams deltas as events when the provider can. Returns (response, streamed)."""
        kwargs: dict[str, Any] = {}
        if budget:
            kwargs["thinking_budget"] = budget
        streamed = False
        if getattr(provider, "supports_streaming", False):
            async def on_delta(text: str) -> None:
                nonlocal streamed
                streamed = True
                await emit("text_delta", {"text": text})

            async def on_thinking(text: str) -> None:
                await emit("thinking_delta", {"text": text})

            kwargs.update(stream=True, on_delta=on_delta, on_thinking=on_thinking)
        resp = await provider.chat(self.messages, self.tools, system, model, self.config.max_output_tokens, **kwargs)
        return resp, streamed

    def _provider_for(self, name: str) -> LLMProvider:
        """The injected provider serves its own name; others are built lazily."""
        if name == getattr(self.provider, "name", None):
            return self.provider
        if name not in self.providers_cache:
            self.providers_cache[name] = make_provider(name, self.config)
        return self.providers_cache[name]

    def _cheap_model(self) -> str:
        return self.config.resolve_model("cheap")[1]

    async def _run_tool_calls(self, calls: list[ToolCall], emit: Emit) -> None:
        if len(calls) > 1 and all(_parallel_safe(self._tool_map.get(c.name)) for c in calls):
            results = await asyncio.gather(*(self._run_one(c, emit) for c in calls))
        else:
            results = [await self._run_one(c, emit) for c in calls]
        for call, result in zip(calls, results):
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": truncate_tool_output(result.text),
                    "image_png": result.image_png,
                    "is_error": result.is_error,
                }
            )

    async def _run_one(self, call: ToolCall, emit: Emit) -> ToolResult:
        await emit("tool_call", {"id": call.id, "name": call.name, "args": call.args})
        tool = self._tool_map.get(call.name)
        if tool is None:
            result = ToolResult(text=f"Unknown tool: {call.name}", is_error=True)
        elif not await self.permissions.check_async(tool, call.args):  # type: ignore[union-attr]
            result = ToolResult(text="Permission denied by user. Do not retry; explain or choose another approach.", is_error=True)
        else:
            result = await tool.call(**call.args)
        await emit("tool_result", {"id": call.id, "name": call.name, "text": result.text, "is_error": result.is_error,
                                   "has_image": result.image_png is not None})
        return result


def _parallel_safe(tool: Tool | None) -> bool:
    return tool is not None and not tool.dangerous and bool(PARALLEL_SAFE_TAGS & set(tool.tags))


def _emitter(on_event: EventCallback | None) -> Emit:
    async def emit(kind: str, data: dict[str, Any]) -> None:
        if on_event is None:
            return
        out = on_event(kind, data)
        if asyncio.iscoroutine(out):
            await out

    return emit


def make_default_agent(
    config: Config,
    enable_modules: list[str] | None = None,
    model: str | None = None,
    tier: str | None = None,
    provider_name: str | None = None,
    approver: Approver | None = None,
    ask_user: AskUserFn | None = None,
    workspace: Path | None = None,
    tools: list[Tool] | None = None,
    system_prompt: str | None = None,
    max_turns: int | None = None,
) -> Agent:
    """Wire provider + tools from config. `provider_name` overrides routing;
    `workspace` (default: current) becomes the root for file/shell/memory/tasks/skills;
    `tools`/`system_prompt`/`max_turns` are used by subagents to build restricted children."""
    from tpagent.tools import subagent  # light module; children share this config

    subagent.CONFIG = config
    if workspace is not None:
        set_workspace(workspace)
    allow_outside_cwd(config.allow_outside_cwd)
    if tools is None:
        tools = load_tools(enable_modules if enable_modules is not None else config.enabled_tools)
    if model in config.tiers:  # subagents pass a tier name as `model`
        tier, model = model, None
    if provider_name:
        config.default_provider = provider_name
        bare = model or config.provider(provider_name).model or ""
        model = bare if bare.split(":", 1)[0] in config.providers else f"{provider_name}:{bare}"
    first_provider_name = config.resolve_model(model or tier or config.default_tier)[0]
    provider = make_provider(first_provider_name, config)
    return Agent(config=config, provider=provider, tools=tools, model=model, tier=tier, approver=approver,
                 ask_user=ask_user, workspace=get_workspace(), system_prompt=system_prompt, max_turns=max_turns)


__all__ = ["Agent", "DEFAULT_SYSTEM_PROMPT", "EventCallback", "make_default_agent", "load_messages", "list_sessions"]
