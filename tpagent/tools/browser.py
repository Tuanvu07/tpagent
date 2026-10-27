"""Browser tools (Playwright, browser-use style).

Interactive elements are numbered with `data-tp-index` so cheap models click
by number instead of parsing raw HTML. A single lazy `BrowserSession` holds
the Chromium instance for the whole agent run.

Env:
  TPAGENT_BROWSER_HEADLESS=1/0  force headless/headed (default: headed if a
                                display exists, else headless)
  TPAGENT_CDP_URL=http://localhost:9222  attach to a running Chrome instead
"""
from __future__ import annotations

import io
import os
import sys
from typing import Any

from .base import Tool, ToolResult, truncate

NAV_TIMEOUT_MS = 30_000
ACTION_TIMEOUT_MS = 10_000
MAX_ELEMENTS = 150
TEXT_EXCERPT = 2_000
SCREENSHOT_MAX_WIDTH = 1024

# Runs in the page: tag visible interactive elements and describe them.
_SCAN_JS = r"""
(max) => {
  const sel = 'a,button,input,select,textarea,[role=button],[role=link],[role=tab],' +
              '[role=menuitem],[role=checkbox],[onclick],[contenteditable=true],summary';
  document.querySelectorAll('[data-tp-index]').forEach(e => e.removeAttribute('data-tp-index'));
  const out = []; let i = 0;
  const vis = (e) => {
    const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' &&
           r.bottom > 0 && r.top < innerHeight * 3;
  };
  const clip = (t, n) => (t || '').replace(/\s+/g, ' ').trim().slice(0, n);
  for (const e of document.querySelectorAll(sel)) {
    if (i >= max) break;
    if (e.disabled || e.type === 'hidden' || !vis(e)) continue;
    e.setAttribute('data-tp-index', String(i));
    const tag = e.tagName.toLowerCase(); const a = [];
    if (e.type && tag === 'input') a.push('type=' + e.type);
    for (const k of ['placeholder', 'name', 'aria-label', 'title', 'href', 'value']) {
      const v = e.getAttribute(k);
      if (v && !(k === 'value' && (e.type === 'password'))) a.push(k + '="' + clip(v, 60) + '"');
    }
    if (e.getAttribute('role')) a.push('role=' + e.getAttribute('role'));
    let text = clip(e.innerText || e.textContent, 80);
    if (tag === 'select') text = [...e.options].slice(0, 8).map(o => o.value).join('|');
    out.push({ index: i, tag, attrs: a.join(' '), text });
    i++;
  }
  return out;
}
"""

_TEXT_JS = """
() => {
  const root = document.querySelector('main, article, [role=main]') || document.body;
  return root ? root.innerText : '';
}
"""


def _default_headless() -> bool:
    env = os.environ.get("TPAGENT_BROWSER_HEADLESS")
    if env in ("0", "1"):
        return env == "1"
    if sys.platform.startswith("linux"):
        return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return False


def _scale_png(png: bytes, max_width: int) -> bytes:
    try:
        from PIL import Image
    except ImportError:
        return png
    img = Image.open(io.BytesIO(png))
    if img.width <= max_width:
        return png
    ratio = max_width / img.width
    img = img.resize((max_width, int(img.height * ratio)))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def format_elements(elements: list[dict[str, Any]]) -> str:
    """Render the JS scan output as a compact numbered list."""
    lines = []
    for el in elements:
        attrs = f" {el['attrs']}" if el["attrs"] else ""
        text = f" {el['text']}" if el["text"] else ""
        lines.append(f"[{el['index']}] <{el['tag']}{attrs}>{text}")
    return "\n".join(lines) if lines else "(no interactive elements found)"


class BrowserSession:
    """Lazy singleton around async Playwright."""

    _instance: BrowserSession | None = None

    def __init__(self) -> None:
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self.page: Any = None

    @classmethod
    def get(cls) -> BrowserSession:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self) -> Any:
        if self.page is not None and not self.page.is_closed():
            return self.page
        from playwright.async_api import async_playwright

        if self._pw is None:
            self._pw = await async_playwright().start()
        cdp = os.environ.get("TPAGENT_CDP_URL")
        if cdp:
            self._browser = await self._pw.chromium.connect_over_cdp(cdp)
            self._context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
        else:
            self._browser = await self._pw.chromium.launch(headless=_default_headless())
            self._context = await self._browser.new_context(viewport={"width": 1280, "height": 900}, locale="vi-VN")
        self._context.set_default_timeout(ACTION_TIMEOUT_MS)
        self.page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        return self.page

    async def close(self) -> None:
        if self._browser is not None and not os.environ.get("TPAGENT_CDP_URL"):
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        self._pw = self._browser = self._context = self.page = None

    @property
    def pages(self) -> list[Any]:
        return list(self._context.pages) if self._context else []

    async def settle(self) -> None:
        try:
            await self.page.wait_for_load_state("load", timeout=NAV_TIMEOUT_MS)
            await self.page.wait_for_load_state("networkidle", timeout=3_000)
        except Exception:  # noqa: BLE001 - slow pages are fine, we still scan
            pass

    async def scan(self) -> list[dict[str, Any]]:
        page = await self.start()
        return await page.evaluate(_SCAN_JS, MAX_ELEMENTS)

    async def state_text(self) -> str:
        page = await self.start()
        elements = await self.scan()
        excerpt = truncate((await page.evaluate(_TEXT_JS)).strip(), TEXT_EXCERPT)
        tabs = f" (tabs: {len(self.pages)})" if len(self.pages) > 1 else ""
        return (
            f"URL: {page.url}\nTitle: {await page.title()}{tabs}\n\n"
            f"Interactive elements (click/type by [index]):\n{format_elements(elements)}\n\n"
            f"Text excerpt:\n{excerpt}"
        )

    async def locator(self, index: int) -> Any:
        page = await self.start()
        loc = page.locator(f"[data-tp-index='{index}']")
        if await loc.count() == 0:
            await self.scan()
            loc = page.locator(f"[data-tp-index='{index}']")
            if await loc.count() == 0:
                raise ValueError(f"Element [{index}] not found; page changed. Call browser_state and use a fresh index.")
        return loc.first

    async def screenshot(self) -> bytes:
        page = await self.start()
        return _scale_png(await page.screenshot(type="png"), SCREENSHOT_MAX_WIDTH)


# --- tool functions ---------------------------------------------------------
S = BrowserSession.get


async def browser_navigate(url: str) -> str:
    page = await S().start()
    if "://" not in url:
        url = "https://" + url
    await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
    await S().settle()
    return await S().state_text()


async def browser_state() -> ToolResult:
    return ToolResult(text=await S().state_text(), image_png=await S().screenshot())


async def browser_click(index: int) -> str:
    loc = await S().locator(index)
    try:
        await loc.click(timeout=ACTION_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 - overlays; fall back to JS click
        await loc.evaluate("e => e.click()")
    await S().settle()
    return f"Clicked [{index}].\n\n" + await S().state_text()


async def browser_type(index: int, text: str, press_enter: bool = False) -> str:
    loc = await S().locator(index)
    await loc.click(timeout=ACTION_TIMEOUT_MS)
    await loc.fill(text)
    if press_enter:
        await loc.press("Enter")
        await S().settle()
    return f"Typed into [{index}].\n\n" + await S().state_text()


async def browser_select(index: int, value: str) -> str:
    loc = await S().locator(index)
    try:
        await loc.select_option(value=value)
    except Exception:  # noqa: BLE001 - try by visible label
        await loc.select_option(label=value)
    return f"Selected '{value}' in [{index}].\n\n" + await S().state_text()


async def browser_submit(index: int) -> str:
    loc = await S().locator(index)
    submitted = await loc.evaluate("e => { const f = e.form || e.closest('form'); if (f) { f.requestSubmit(); return true; } return false; }")
    if not submitted:
        await loc.press("Enter")
    await S().settle()
    return f"Submitted form of [{index}].\n\n" + await S().state_text()


async def browser_scroll(direction: str = "down", amount: int = 600) -> str:
    page = await S().start()
    dy = amount if direction == "down" else -amount
    await page.mouse.wheel(0, dy)
    await page.wait_for_timeout(300)
    return await S().state_text()


async def browser_back() -> str:
    page = await S().start()
    await page.go_back(timeout=NAV_TIMEOUT_MS)
    await S().settle()
    return await S().state_text()


async def browser_get_text() -> str:
    page = await S().start()
    return truncate((await page.evaluate(_TEXT_JS)).strip(), 15_000)


async def browser_screenshot() -> ToolResult:
    page = await S().start()
    return ToolResult(text=f"Screenshot of {page.url}", image_png=await S().screenshot())


async def browser_tabs() -> str:
    await S().start()
    cur = S().page
    lines = [f"{'*' if p is cur else ' '} [{i}] {await p.title()} — {p.url}" for i, p in enumerate(S().pages)]
    return "\n".join(lines)


async def browser_new_tab(url: str = "about:blank") -> str:
    await S().start()
    S().page = await S()._context.new_page()
    return await browser_navigate(url) if url != "about:blank" else "Opened blank tab."


async def browser_switch_tab(i: int) -> str:
    await S().start()
    pages = S().pages
    if not 0 <= i < len(pages):
        raise ValueError(f"Tab {i} does not exist (0..{len(pages) - 1}).")
    S().page = pages[i]
    await S().page.bring_to_front()
    return await S().state_text()


async def browser_wait(seconds: float = 2) -> str:
    page = await S().start()
    await page.wait_for_timeout(min(max(seconds, 0), 10) * 1000)
    return await S().state_text()


async def browser_eval(js: str) -> str:
    page = await S().start()
    result = await page.evaluate(js)
    return truncate(str(result), 10_000)


async def browser_close() -> str:
    await S().close()
    return "Browser closed."


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


_IDX = {"index": {"type": "integer", "description": "Element index from browser_state"}}
_SAFETY = " Never enter passwords or payment details unless the user explicitly provided them for this task."

TOOLS: list[Tool] = [
    Tool("browser_navigate", "Open a URL in the browser and return the page state (numbered interactive elements + text).",
         _schema({"url": {"type": "string"}}, ["url"]), browser_navigate, tags=["browser"]),
    Tool("browser_state", "Current page: URL, title, numbered interactive elements, text excerpt, and a screenshot.",
         _schema({}), browser_state, tags=["browser"]),
    Tool("browser_click", "Click element [index] from browser_state; returns the new page state.",
         _schema(_IDX, ["index"]), browser_click, tags=["browser"]),
    Tool("browser_type", "Clear and type text into input [index]; optionally press Enter to submit." + _SAFETY,
         _schema({**_IDX, "text": {"type": "string"}, "press_enter": {"type": "boolean", "default": False}},
                 ["index", "text"]), browser_type, tags=["browser"]),
    Tool("browser_select", "Choose an option (by value or visible label) in <select> element [index].",
         _schema({**_IDX, "value": {"type": "string"}}, ["index", "value"]), browser_select, tags=["browser"]),
    Tool("browser_submit", "Submit the form containing element [index] (e.g. a login or search form). Dangerous: sends data to the site." + _SAFETY,
         _schema(_IDX, ["index"]), browser_submit, dangerous=True, tags=["browser"]),
    Tool("browser_scroll", "Scroll the page up or down by `amount` pixels (default 600).",
         _schema({"direction": {"type": "string", "enum": ["up", "down"]}, "amount": {"type": "integer"}}),
         browser_scroll, tags=["browser"]),
    Tool("browser_back", "Go back to the previous page.", _schema({}), browser_back, tags=["browser"]),
    Tool("browser_get_text", "Readable main text of the page (up to 15k chars).", _schema({}), browser_get_text,
         tags=["browser"]),
    Tool("browser_screenshot", "Screenshot of the current page (scaled to 1024px wide).", _schema({}),
         browser_screenshot, tags=["browser"]),
    Tool("browser_tabs", "List open tabs; * marks the active one.", _schema({}), browser_tabs, tags=["browser"]),
    Tool("browser_new_tab", "Open a new tab, optionally navigating to url.", _schema({"url": {"type": "string"}}),
         browser_new_tab, tags=["browser"]),
    Tool("browser_switch_tab", "Switch to tab number i from browser_tabs.",
         _schema({"i": {"type": "integer"}}, ["i"]), browser_switch_tab, tags=["browser"]),
    Tool("browser_wait", "Wait up to 10 seconds for the page to settle, then return state.",
         _schema({"seconds": {"type": "number", "maximum": 10}}), browser_wait, tags=["browser"]),
    Tool("browser_eval", "Run JavaScript in the page and return the result. Dangerous: can change site data.",
         _schema({"js": {"type": "string"}}, ["js"]), browser_eval, dangerous=True, tags=["browser"]),
    Tool("browser_close", "Close the browser and free resources.", _schema({}), browser_close, tags=["browser"]),
]

__all__ = ["TOOLS", "BrowserSession", "format_elements"]
