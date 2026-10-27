"""Web tools: web_fetch (URL -> readable text) and web_search (DuckDuckGo HTML)."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .base import Tool

FETCH_LIMIT = 20_000
UA = "Mozilla/5.0 (X11; Linux x86_64) TPAgent/0.1 (+https://github.com/tpagent)"
DDG_URL = "https://html.duckduckgo.com/html/"
SKIP_TAGS = {"script", "style", "noscript", "svg", "head", "template"}
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre", "blockquote"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "title":
            self._in_title = True
        if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            self.parts.append("#" * int(tag[1]) + " ")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(raw: str) -> tuple[str, str]:
    """Return (title, readable text) from an HTML document."""
    p = _TextExtractor()
    p.feed(raw)
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return p.title.strip(), text.strip()


async def web_fetch(url: str, max_chars: int = FETCH_LIMIT) -> str:
    """Fetch a URL and return readable text (HTML stripped), truncated."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers={"User-Agent": UA}) as client:
        resp = await client.get(url)
    ctype = resp.headers.get("content-type", "")
    body = resp.text
    if "html" in ctype or body.lstrip()[:200].lower().startswith(("<!doctype", "<html")):
        title, body = html_to_text(body)
        body = (f"# {title}\n\n" if title else "") + body
    limit = max(1_000, min(int(max_chars), FETCH_LIMIT))
    if len(body) > limit:
        body = body[:limit] + f"\n\n... [truncated, {len(body) - limit} more chars]"
    return f"[{resp.status_code}] {resp.url}\n\n{body}"


class _DDGParser(HTMLParser):
    """Collect result title/url/snippet from html.duckduckgo.com markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._mode: str | None = None  # "title" | "snippet"
        self._cur: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = dict(attrs)
        cls = a.get("class", "") or ""
        if tag == "a" and "result__a" in cls:
            self._cur = {"title": "", "url": _clean_ddg_url(a.get("href", "")), "snippet": ""}
            self._mode = "title"
        elif tag == "a" and "result__snippet" in cls and self._cur is not None:
            self._mode = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._mode == "title":
            self._mode = None
        elif tag == "a" and self._mode == "snippet" and self._cur is not None:
            self.results.append({k: v.strip() for k, v in self._cur.items()})
            self._cur, self._mode = None, None

    def handle_data(self, data: str) -> None:
        if self._cur is not None and self._mode:
            self._cur[self._mode] += data


def _clean_ddg_url(href: str) -> str:
    """DDG wraps links as //duckduckgo.com/l/?uddg=<encoded>."""
    if "uddg=" in href:
        q = parse_qs(urlparse(href).query)
        return unquote(q.get("uddg", [href])[0])
    return href if href.startswith("http") else "https:" + href if href.startswith("//") else href


async def web_search(query: str, max_results: int = 8) -> str:
    """Search the web via DuckDuckGo and return top results (title, url, snippet)."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers={"User-Agent": UA}) as client:
            resp = await client.post(DDG_URL, data={"q": query, "kl": "wt-wt"})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return f"Error: search failed ({type(e).__name__}: {e}). Try web_fetch on a known URL instead."
    parser = _DDGParser()
    parser.feed(resp.text)
    results = parser.results[: max(1, min(int(max_results), 10))]
    if not results:
        return "No results (DuckDuckGo may have rate-limited or changed its markup)."
    return "\n\n".join(
        f"{i}. {html.unescape(r['title'])}\n   {r['url']}\n   {html.unescape(r['snippet'])}" for i, r in enumerate(results, 1)
    )


TOOLS: list[Tool] = [
    Tool(
        "web_fetch",
        "Fetch a web page or API URL and return its readable text (HTML stripped, max 20k chars).",
        {"type": "object", "properties": {"url": {"type": "string"},
                                          "max_chars": {"type": "integer", "default": FETCH_LIMIT}}, "required": ["url"]},
        web_fetch, tags=["web", "read"],
    ),
    Tool(
        "web_search",
        "Search the web (DuckDuckGo). Returns up to 8 results with title, URL and snippet.",
        {"type": "object", "properties": {"query": {"type": "string"},
                                          "max_results": {"type": "integer", "default": 8}}, "required": ["query"]},
        web_search, tags=["web", "read"],
    ),
]
