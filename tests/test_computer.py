"""Computer tool tests: no display required."""
from __future__ import annotations

import asyncio
import builtins
import importlib
import sys

import pytest

from tpagent.tools import computer
from tpagent.tools.base import ToolResult


def test_tools_load_and_flags() -> None:
    names = [t.name for t in computer.TOOLS]
    assert names[0] == "computer_screenshot" and "computer_click" in names and "computer_open_app" in names
    safe = {t.name for t in computer.TOOLS if not t.dangerous}
    assert safe == {"computer_screenshot", "computer_wait"}
    for t in computer.TOOLS:
        assert "computer" in t.tags and t.schema["type"] == "object"
        if t.dangerous:
            assert "password" in t.description.lower()


def test_geometry_mapping() -> None:
    geo = computer.compute_geometry(2560, 1440)
    assert geo.scale == 2.0 and (geo.shot_w, geo.shot_h) == (1280, 720)
    assert geo.to_real(640, 360) == (1280, 720)
    assert geo.to_real(1279, 719) == (2558, 1438)
    assert geo.to_real(99999, -5) == (2559, 0)  # clamped
    small = computer.compute_geometry(1024, 768)
    assert small.scale == 1.0 and small.to_real(10, 20) == (10, 20)
    odd = computer.compute_geometry(1920, 1080)
    assert (odd.shot_w, odd.shot_h) == (1280, 720)


def test_open_app_command_per_platform() -> None:
    assert computer.open_app_command("notepad", "Windows") == ["cmd", "/c", "start", "", "notepad"]
    assert computer.open_app_command("Safari", "Darwin") == ["open", "-a", "Safari"]
    assert computer.open_app_command("definitely-not-a-binary-xyz", "Linux") == ["xdg-open", "definitely-not-a-binary-xyz"]
    assert computer.open_app_command("sh", "Linux") == ["sh"]


def test_no_display_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(computer, "_geometry", None)
    click = next(t for t in computer.TOOLS if t.name == "computer_click")
    res = asyncio.run(click.call(x=1, y=2))
    assert isinstance(res, ToolResult) and res.is_error and "display" in res.text.lower()
    shot = next(t for t in computer.TOOLS if t.name == "computer_screenshot")
    res = asyncio.run(shot.call())
    assert res.is_error and res.image_png is None


def test_missing_optional_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Module imports and TOOLS load even when pyautogui/mss/PIL are missing."""
    real_import = builtins.__import__

    def fake_import(name: str, *a: object, **k: object) -> object:
        if name.split(".")[0] in {"pyautogui", "mss", "PIL"}:
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    for mod in ("pyautogui", "mss", "PIL"):
        monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(computer, "_geometry", None)

    reloaded = importlib.reload(computer)
    assert len(reloaded.TOOLS) == 9
    res = asyncio.run(reloaded.TOOLS[0].call())
    assert res.is_error and "pip install" in res.text
    type_tool = next(t for t in reloaded.TOOLS if t.name == "computer_type")
    res = asyncio.run(type_tool.call(text="abc"))
    assert res.is_error and "pyautogui" in res.text


def test_key_parsing_requires_input(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeGui:
        pressed: list[tuple[str, ...]] = []

        def press(self, k: str) -> None:
            self.pressed.append((k,))

        def hotkey(self, *k: str) -> None:
            self.pressed.append(k)

    gui = FakeGui()
    monkeypatch.setattr(computer, "_gui", lambda: gui)
    assert computer.computer_key("Ctrl + C") == "pressed ctrl+c"
    assert computer.computer_key("enter") == "pressed enter"
    assert gui.pressed == [("ctrl", "c"), ("enter",)]
    with pytest.raises(ValueError):
        computer.computer_key(" + ")


def test_wait_clamps() -> None:
    assert computer.computer_wait(0) == "waited 0s"
