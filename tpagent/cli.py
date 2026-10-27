"""TPAgent CLI: one-shot `tpagent "task"` or interactive REPL (streams text live)."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from tpagent import __version__
from tpagent.config import Config, load_config
from tpagent.core.agent import Agent, list_sessions, make_default_agent
from tpagent.core.router import TIERS
from tpagent.tools import OPTIONAL_MODULES

app = typer.Typer(add_completion=False, help="TPAgent - agent lập trình/tự động hóa giá rẻ, nhiều model.")
console = Console()

HELP_TEXT = """\
[bold]Lệnh:[/]
  /model <tier|model>   đổi model (cheap | standard | strong | tên model, vd deepseek:deepseek-chat)
  /think on|off|auto    bật/tắt suy nghĩ mở rộng (auto = theo config từng bậc)
  /cost                 xem chi phí phiên này
  /tools                liệt kê tool đang bật
  /sessions             liệt kê phiên đã lưu;  /resume <id> để tiếp tục một phiên
  /yes                  bật/tắt tự động duyệt lệnh nguy hiểm
  /clear                xóa lịch sử hội thoại
  /help                 trợ giúp
  /exit                 thoát
"""


class EventPrinter:
    """Renders agent events; remembers whether the current answer was streamed live."""

    def __init__(self) -> None:
        self.live_chars = 0  # streamed chars since the last tool result
        self.thinking = False

    def __call__(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "start":
            think = f" thinking={data['thinking_budget']}" if data.get("thinking_budget") else ""
            console.print(f"[dim]model={data['model']} provider={data['provider']} session={data['session']}{think}[/]")
        elif kind == "thinking_delta":
            if not self.thinking:
                console.print("[dim italic]… suy nghĩ:[/] ", end="")
                self.thinking = True
            console.print(f"[dim italic]{_escape(data['text'])}[/]", end="", highlight=False)
        elif kind == "text_delta":
            self._end_thinking()
            console.print(data["text"], end="", markup=False, highlight=False, soft_wrap=True)
            self.live_chars += len(data["text"])
        elif kind == "tool_call":
            self._newline()
            args = ", ".join(f"{k}={_short(v)}" for k, v in data["args"].items())
            console.print(f"[dim]-> {data['name']}({args})[/]")
        elif kind == "tool_result":
            lines = data["text"].splitlines() or ["(empty)"]
            head = "\n".join(lines[:5]) + (f"\n... (+{len(lines) - 5} dòng)" if len(lines) > 5 else "")
            style = "red" if data["is_error"] else "dim"
            img = " [image]" if data.get("has_image") else ""
            console.print(f"[{style}]<- {data['name']}{img}: {_escape(head)}[/]")
            self.live_chars = 0
        elif kind == "text" and data["text"].strip() and not data.get("streamed"):
            console.print(Markdown(data["text"]))

    def _end_thinking(self) -> None:
        if self.thinking:
            console.print()
            self.thinking = False

    def _newline(self) -> None:
        self._end_thinking()
        if self.live_chars:
            console.print()
            self.live_chars = 0


def _escape(s: str) -> str:
    return s.replace("[", "\\[")


def _short(v: Any, n: int = 60) -> str:
    s = str(v).replace("\n", "\\n")
    return s if len(s) <= n else s[: n - 3] + "..."


async def _ask_user_tty(question: str, options: list[str] | None) -> str:
    console.print(Panel(question, title="Câu hỏi từ agent", border_style="yellow"))
    if options:
        for i, opt in enumerate(options, 1):
            console.print(f"  [cyan]{i}[/]. {opt}")
    answer = await asyncio.to_thread(console.input, "[bold yellow]trả lời>[/] ")
    if options and answer.strip().isdigit() and 1 <= int(answer) <= len(options):
        return options[int(answer) - 1]
    return answer


def _run_task(agent: Agent, task: str) -> None:
    printer = EventPrinter()
    try:
        answer = asyncio.run(agent.run(task, on_event=printer))
    except KeyboardInterrupt:
        console.print("[yellow]Đã dừng.[/]")
        return
    except Exception as e:  # noqa: BLE001 - show provider/network errors to the user
        console.print(Panel(f"{type(e).__name__}: {e}", title="Lỗi", border_style="red"))
        return
    if printer.live_chars:  # final answer already streamed to the terminal
        console.print()
    else:
        console.print(Panel(Markdown(answer or "(không có câu trả lời)"), title="Kết quả", border_style="green"))
    console.print(f"[dim]Chi phí phiên: ${agent.cost.total_usd:.4f}[/]")


def _handle_slash(agent: Agent, line: str) -> bool:
    """Return False to exit the REPL."""
    cmd, _, arg = line.strip().partition(" ")
    arg = arg.strip()
    if cmd in ("/exit", "/quit", "/q"):
        return False
    if cmd == "/help":
        console.print(HELP_TEXT)
    elif cmd == "/cost":
        console.print(agent.cost.summary())
    elif cmd == "/tools":
        for t in agent.tools:
            flag = " [red](nguy hiểm)[/]" if t.dangerous else ""
            console.print(f"  [cyan]{t.name}[/]{flag} - {t.description[:90]}")
    elif cmd == "/yes":
        pm = agent.permissions
        pm.auto_approve = not pm.auto_approve  # type: ignore[union-attr]
        console.print(f"Tự động duyệt: {'BẬT' if pm.auto_approve else 'TẮT'}")  # type: ignore[union-attr]
    elif cmd == "/clear":
        agent.clear()
        console.print("Đã xóa lịch sử.")
    elif cmd == "/model":
        _set_model(agent, arg)
    elif cmd == "/think":
        _set_thinking(agent, arg)
    elif cmd == "/sessions":
        _show_sessions(agent.config)
    elif cmd == "/resume":
        _resume(agent, arg)
    else:
        console.print(f"[red]Lệnh không rõ: {cmd}[/]. Gõ /help.")
    return True


def _set_model(agent: Agent, arg: str) -> None:
    if not arg:
        console.print(f"Hiện tại: model={agent.model or '(auto)'} tier={agent.tier or '(auto)'}")
        return
    if arg in TIERS:
        agent.tier, agent.model = arg, None
    else:
        agent.model, agent.tier = arg, None
    provider, model = agent.pick_model("")
    console.print(f"Đã chọn: {model} (provider {provider})")


def _set_thinking(agent: Agent, arg: str) -> None:
    modes = {"on": True, "off": False, "auto": None}
    if arg not in modes:
        state = {True: "BẬT", False: "TẮT", None: "auto (theo config)"}[agent.thinking]
        console.print(f"Suy nghĩ mở rộng: {state}. Dùng /think on|off|auto")
        return
    agent.thinking = modes[arg]
    console.print(f"Suy nghĩ mở rộng: {arg}")


def _show_sessions(cfg: Config) -> None:
    sessions = list_sessions(cfg)
    if not sessions:
        console.print("(chưa có phiên nào)")
        return
    for s in sessions:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(s.updated))
        console.print(f"  [cyan]{s.id}[/]  {when}  {s.messages} msg  ${s.cost_usd:.4f}  {s.first_task}")


def _resume(agent: Agent, session_id: str) -> bool:
    if not session_id:
        console.print("Dùng: /resume <id> (xem /sessions)")
        return False
    try:
        n = agent.load_session(session_id)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/]")
        return False
    console.print(f"Đã nạp phiên {session_id} ({n} tin nhắn).")
    return True


def _repl(agent: Agent) -> None:
    console.print(Panel(f"TPAgent v{__version__} - gõ việc cần làm, hoặc /help", border_style="blue"))
    while True:
        try:
            line = console.input("[bold blue]tpagent>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not line:
            continue
        if line.startswith("/"):
            if not _handle_slash(agent, line):
                break
            continue
        _run_task(agent, line)
    console.print(f"[dim]Tổng chi phí: ${agent.cost.total_usd:.4f}. Tạm biệt![/]")


def _build_agent(cfg: Config, model: str | None, tier: str | None, enable: str | None, provider: str | None,
                 workspace: Path | None) -> Agent:
    modules = [m.strip() for m in enable.split(",") if m.strip()] if enable is not None else None
    if modules is not None:
        bad = [m for m in modules if m not in OPTIONAL_MODULES]
        if bad:
            raise typer.BadParameter(f"module không hợp lệ: {bad}; chọn trong {OPTIONAL_MODULES}")
    return make_default_agent(cfg, enable_modules=modules, model=model, tier=tier, provider_name=provider,
                              ask_user=_ask_user_tty, workspace=workspace)


@app.command()
def run(
    task: Optional[str] = typer.Argument(None, help="Việc cần làm. Bỏ trống để vào chế độ hội thoại."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Tên model, vd claude-haiku-5-5, deepseek:deepseek-chat"),
    tier: Optional[str] = typer.Option(None, "--tier", "-t", help="cheap | standard | strong"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Tự động duyệt lệnh nguy hiểm"),
    enable: Optional[str] = typer.Option(None, "--enable", "-e", help="Bật module tool: browser,computer,video,subagent"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="anthropic | deepseek | qwen | gemini | openrouter | ollama | openai | fake"),
    config_path: Optional[str] = typer.Option(None, "--config", "-c", help="Đường dẫn config.yaml"),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w", help="Thư mục làm việc (mặc định: thư mục hiện tại)"),
    resume: Optional[str] = typer.Option(None, "--resume", "-r", help="Tiếp tục phiên đã lưu (xem /sessions)"),
    think: Optional[bool] = typer.Option(None, "--think/--no-think", help="Ép bật/tắt suy nghĩ mở rộng"),
    version: bool = typer.Option(False, "--version", help="In phiên bản"),
) -> None:
    """Chạy một việc (one-shot) hoặc mở REPL nếu không truyền task."""
    if version:
        console.print(f"tpagent {__version__}")
        raise typer.Exit()
    if tier is not None and tier not in TIERS:
        raise typer.BadParameter(f"tier phải là một trong {TIERS}")
    cfg = load_config(config_path)
    cfg.auto_approve = cfg.auto_approve or yes
    try:
        agent = _build_agent(cfg, model, tier, enable, provider, workspace)
    except RuntimeError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=1)
    agent.thinking = think
    if resume and not _resume(agent, resume):
        raise typer.Exit(code=1)
    if task:
        _run_task(agent, task)
    else:
        _repl(agent)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
