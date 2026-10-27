"""Browser tool tests. Playwright parts are skipped when Chromium cannot launch."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from tpagent.tools import browser
from tpagent.tools.base import ToolResult

PAGE_HTML = """<!doctype html><html><head><title>Test Page</title></head><body>
<main><h1>Xin chào</h1><p>Đây là trang thử nghiệm của Cầm Đồ Thành Phát.</p>
<form onsubmit="event.preventDefault(); document.getElementById('out').textContent='submitted:'+this.q.value">
  <input type="text" name="q" placeholder="Tìm kiếm">
  <select name="city"><option value="hcm">HCM</option><option value="hn">Hà Nội</option></select>
  <button type="submit">Đăng nhập</button>
</form>
<a href="#second">Link</a>
<button onclick="document.getElementById('out').textContent='clicked'">Bấm</button>
<input type="hidden" name="h"><button disabled>Off</button>
<div id="out"></div></main></body></html>"""


@pytest.fixture
def page_url(tmp_path: Path) -> str:
    f = tmp_path / "page.html"
    f.write_text(PAGE_HTML, encoding="utf-8")
    return f.as_uri()


def _chromium_available() -> bool:
    async def probe() -> bool:
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                b = await p.chromium.launch(headless=True)
                await b.close()
            return True
        except Exception:  # noqa: BLE001
            return False

    return asyncio.run(probe())


needs_chromium = pytest.mark.skipif(not _chromium_available(), reason="Chromium not launchable")


def test_tools_load() -> None:
    names = {t.name for t in browser.TOOLS}
    assert {"browser_navigate", "browser_state", "browser_click", "browser_type", "browser_close"} <= names
    dangerous = {t.name for t in browser.TOOLS if t.dangerous}
    assert dangerous == {"browser_eval", "browser_submit"}
    for t in browser.TOOLS:
        assert t.schema["type"] == "object" and "browser" in t.tags


def test_format_elements() -> None:
    out = browser.format_elements([
        {"index": 0, "tag": "button", "attrs": "", "text": "Đăng nhập"},
        {"index": 1, "tag": "input", "attrs": 'type=text placeholder="Tìm"', "text": ""},
    ])
    assert out.splitlines() == ["[0] <button> Đăng nhập", '[1] <input type=text placeholder="Tìm">']
    assert "no interactive" in browser.format_elements([])


def test_default_headless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TPAGENT_BROWSER_HEADLESS", "1")
    assert browser._default_headless() is True
    monkeypatch.setenv("TPAGENT_BROWSER_HEADLESS", "0")
    assert browser._default_headless() is False


def test_scale_png_shrinks_wide_images() -> None:
    PIL = pytest.importorskip("PIL.Image")
    import io

    buf = io.BytesIO()
    PIL.new("RGB", (2048, 1000), "white").save(buf, format="PNG")
    out = PIL.open(io.BytesIO(browser._scale_png(buf.getvalue(), 1024)))
    assert out.size == (1024, 500)


@needs_chromium
def test_scan_click_type_on_static_page(monkeypatch: pytest.MonkeyPatch, page_url: str) -> None:
    monkeypatch.setenv("TPAGENT_BROWSER_HEADLESS", "1")
    monkeypatch.delenv("TPAGENT_CDP_URL", raising=False)

    async def run() -> None:
        state = await browser.browser_navigate(page_url)
        assert "Title: Test Page" in state and "Xin chào" in state
        assert '<input type=text placeholder="Tìm kiếm" name="q">' in state
        assert "Đăng nhập" in state and "<select" in state
        assert "Off" not in state.split("Text excerpt")[0]  # disabled/hidden skipped
        elements = await browser.S().scan()
        by_text = {e["text"]: e["index"] for e in elements}
        by_tag = {e["tag"]: e["index"] for e in elements}

        out = await browser.browser_type(by_tag["input"], "vàng", press_enter=True)
        assert "submitted:vàng" in out
        out = await browser.browser_click(by_text["Bấm"])
        assert "clicked" in out
        out = await browser.browser_select(by_tag["select"], "Hà Nội")
        assert "Selected" in out

        res = await browser.browser_state()
        assert isinstance(res, ToolResult) and res.image_png and res.image_png[:4] == b"\x89PNG"
        text = await browser.browser_get_text()
        assert "Cầm Đồ Thành Phát" in text

        with pytest.raises(ValueError, match="not found"):
            await browser.S().locator(999)
        assert "[0]" in await browser.browser_tabs()
        await browser.browser_new_tab()
        assert len(browser.S().pages) == 2
        await browser.browser_switch_tab(0)
        assert await browser.browser_close() == "Browser closed."

    asyncio.run(run())


@needs_chromium
def test_call_wraps_errors(page_url: str) -> None:
    os.environ["TPAGENT_BROWSER_HEADLESS"] = "1"
    tool = next(t for t in browser.TOOLS if t.name == "browser_click")

    async def run() -> None:
        await browser.browser_navigate(page_url)
        res = await tool.call(index=12345)
        assert res.is_error and "browser_state" in res.text
        await browser.browser_close()

    asyncio.run(run())
