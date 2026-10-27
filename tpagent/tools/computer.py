"""Desktop control tools (Anthropic computer-use style loop).

Flow: computer_screenshot (downscaled, max 1280 wide) -> model looks at the
image -> computer_click(x, y) in screenshot coordinates -> mapped to real
pixels. pyautogui / mss / pillow are imported lazily; without them or without
a display every tool returns a clear error instead of crashing.
"""
from __future__ import annotations

import io
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

from .base import Tool, ToolResult

MAX_WIDTH = 1280
_SAFETY = " SAFETY: never type passwords, OTP codes or card numbers; ask the user to enter them."


@dataclass(frozen=True)
class ScreenGeometry:
    """Real screen size plus the factor used to shrink screenshots."""

    real_w: int
    real_h: int
    scale: float  # shot_px * scale == real_px

    @property
    def shot_w(self) -> int:
        return round(self.real_w / self.scale)

    @property
    def shot_h(self) -> int:
        return round(self.real_h / self.scale)

    def to_real(self, x: float, y: float) -> tuple[int, int]:
        rx = min(max(round(x * self.scale), 0), self.real_w - 1)
        ry = min(max(round(y * self.scale), 0), self.real_h - 1)
        return rx, ry


def compute_geometry(real_w: int, real_h: int, max_width: int = MAX_WIDTH) -> ScreenGeometry:
    scale = max(1.0, real_w / max_width)
    return ScreenGeometry(real_w, real_h, scale)


class DesktopUnavailable(RuntimeError):
    pass


_geometry: ScreenGeometry | None = None


def _gui() -> Any:
    """Import pyautogui lazily and fail with an actionable message."""
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        raise DesktopUnavailable("No display found (DISPLAY unset). Desktop control needs a graphical session.")
    try:
        import pyautogui
    except Exception as e:  # noqa: BLE001 - ImportError or Xlib display errors
        raise DesktopUnavailable(f"pyautogui unavailable: {e}. Install: pip install pyautogui mss pillow") from e
    pyautogui.FAILSAFE = True  # move mouse to a screen corner to abort
    pyautogui.PAUSE = 0.05
    return pyautogui


def _geometry_now() -> ScreenGeometry:
    global _geometry
    if _geometry is None:
        w, h = _gui().size()
        _geometry = compute_geometry(int(w), int(h))
    return _geometry


def _grab_png() -> bytes:
    try:
        import mss
        from PIL import Image
    except ImportError as e:
        raise DesktopUnavailable(f"missing dependency: {e}. Install: pip install mss pillow") from e
    geo = _geometry_now()  # also validates that a display exists
    grabber = getattr(mss, "MSS", None) or mss.mss
    with grabber() as sct:
        raw = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    if geo.scale > 1.0:
        img = img.resize((geo.shot_w, geo.shot_h))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _guard(fn: Any) -> Any:
    """Turn DesktopUnavailable into a non-crashing error ToolResult."""

    def wrapper(**kwargs: Any) -> str | ToolResult:
        try:
            return fn(**kwargs)
        except DesktopUnavailable as e:
            return ToolResult(text=f"computer tools unavailable: {e}", is_error=True)

    wrapper.__name__ = fn.__name__
    return wrapper


# --- tool functions ---------------------------------------------------------
def computer_screenshot() -> ToolResult:
    png = _grab_png()
    geo = _geometry_now()
    return ToolResult(
        text=(f"Screenshot {geo.shot_w}x{geo.shot_h} (real screen {geo.real_w}x{geo.real_h}, "
              f"scale {geo.scale:.3f}). Use screenshot coordinates for computer_* tools."),
        image_png=png,
    )


def computer_click(x: int, y: int, button: str = "left") -> str:
    gui = _gui()
    rx, ry = _geometry_now().to_real(x, y)
    if button == "double":
        gui.doubleClick(rx, ry)
    else:
        gui.click(rx, ry, button="right" if button == "right" else "left")
    return f"{button} click at ({x},{y}) -> real ({rx},{ry})"


def computer_move(x: int, y: int) -> str:
    rx, ry = _geometry_now().to_real(x, y)
    _gui().moveTo(rx, ry, duration=0.1)
    return f"moved to ({x},{y}) -> real ({rx},{ry})"


def computer_type(text: str) -> str:
    gui = _gui()
    if text.isascii():
        gui.write(text, interval=0.01)
    else:  # pyautogui.write drops non-ASCII (Vietnamese); go through clipboard
        _paste_unicode(gui, text)
    return f"typed {len(text)} chars"


def _paste_unicode(gui: Any, text: str) -> None:
    try:
        import pyperclip

        pyperclip.copy(text)
        gui.hotkey("command" if sys.platform == "darwin" else "ctrl", "v")
    except Exception:  # noqa: BLE001 - no clipboard backend, type what we can
        gui.write(text.encode("ascii", "ignore").decode(), interval=0.01)


def computer_key(keys: str) -> str:
    parts = [k.strip().lower() for k in keys.split("+") if k.strip()]
    if not parts:
        raise ValueError("keys is empty")
    gui = _gui()
    if len(parts) == 1:
        gui.press(parts[0])
    else:
        gui.hotkey(*parts)
    return f"pressed {'+'.join(parts)}"


def computer_scroll(x: int, y: int, direction: str = "down", amount: int = 5) -> str:
    gui = _gui()
    rx, ry = _geometry_now().to_real(x, y)
    gui.moveTo(rx, ry)
    if direction in ("left", "right"):
        gui.hscroll(amount if direction == "right" else -amount)
    else:
        gui.scroll(-amount if direction == "down" else amount)
    return f"scrolled {direction} {amount} at ({x},{y})"


def computer_drag(x1: int, y1: int, x2: int, y2: int) -> str:
    gui = _gui()
    geo = _geometry_now()
    a, b = geo.to_real(x1, y1), geo.to_real(x2, y2)
    gui.moveTo(*a)
    gui.dragTo(*b, duration=0.4, button="left")
    return f"dragged ({x1},{y1}) -> ({x2},{y2})"


def open_app_command(name: str, system: str | None = None) -> list[str]:
    system = system or platform.system()
    if system == "Windows":
        return ["cmd", "/c", "start", "", name]
    if system == "Darwin":
        return ["open", "-a", name]
    if shutil.which(name):
        return [name]
    return ["xdg-open", name]


def computer_open_app(name: str) -> str:
    cmd = open_app_command(name)
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)  # noqa: S603
    time.sleep(1.5)
    return f"launched: {' '.join(cmd)}"


def computer_wait(seconds: float = 1) -> str:
    time.sleep(min(max(seconds, 0), 10))
    return f"waited {seconds}s"


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


_XY = {"x": {"type": "integer", "description": "x in screenshot pixels"},
       "y": {"type": "integer", "description": "y in screenshot pixels"}}

TOOLS: list[Tool] = [
    Tool("computer_screenshot", "Take a screenshot of the desktop (downscaled). Coordinates for other computer_* "
         "tools are in this screenshot's pixel space.", _schema({}), _guard(computer_screenshot), tags=["computer"]),
    Tool("computer_click", "Click at (x,y) of the last screenshot. button: left|right|double." + _SAFETY,
         _schema({**_XY, "button": {"type": "string", "enum": ["left", "right", "double"]}}, ["x", "y"]),
         _guard(computer_click), dangerous=True, tags=["computer"]),
    Tool("computer_move", "Move the mouse to (x,y) without clicking." + _SAFETY, _schema(_XY, ["x", "y"]),
         _guard(computer_move), dangerous=True, tags=["computer"]),
    Tool("computer_type", "Type text at the current focus (Unicode goes via clipboard)." + _SAFETY,
         _schema({"text": {"type": "string"}}, ["text"]), _guard(computer_type), dangerous=True, tags=["computer"]),
    Tool("computer_key", "Press a key or combo, e.g. 'enter', 'ctrl+c', 'alt+tab'." + _SAFETY,
         _schema({"keys": {"type": "string"}}, ["keys"]), _guard(computer_key), dangerous=True, tags=["computer"]),
    Tool("computer_scroll", "Scroll at (x,y) in direction up|down|left|right by `amount` notches." + _SAFETY,
         _schema({**_XY, "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                  "amount": {"type": "integer"}}, ["x", "y"]), _guard(computer_scroll), dangerous=True,
         tags=["computer"]),
    Tool("computer_drag", "Drag with the left button from (x1,y1) to (x2,y2)." + _SAFETY,
         _schema({k: {"type": "integer"} for k in ("x1", "y1", "x2", "y2")}, ["x1", "y1", "x2", "y2"]),
         _guard(computer_drag), dangerous=True, tags=["computer"]),
    Tool("computer_open_app", "Open an application by name (Windows: start, macOS: open -a, Linux: binary or "
         "xdg-open)." + _SAFETY, _schema({"name": {"type": "string"}}, ["name"]), _guard(computer_open_app),
         dangerous=True, tags=["computer"]),
    Tool("computer_wait", "Wait up to 10 seconds for the UI to update.",
         _schema({"seconds": {"type": "number", "maximum": 10}}), _guard(computer_wait), tags=["computer"]),
]

__all__ = ["TOOLS", "ScreenGeometry", "compute_geometry", "open_app_command", "DesktopUnavailable"]
