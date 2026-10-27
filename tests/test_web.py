from tpagent.tools.web import _DDGParser, _clean_ddg_url, html_to_text


def test_html_to_text_strips_scripts_and_keeps_headings():
    html = "<html><head><title>T</title><script>x()</script></head><body><h1>Head</h1><p>Hello <b>world</b></p></body></html>"
    title, text = html_to_text(html)
    assert title == "T" and "x()" not in text
    assert "# Head" in text and "Hello world" in text


def test_ddg_parser():
    page = (
        '<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fp&rut=1">'
        'Example</a><a class="result__snippet" href="x">A snippet</a></div>'
    )
    p = _DDGParser()
    p.feed(page)
    assert p.results == [{"title": "Example", "url": "https://example.com/p", "snippet": "A snippet"}]
    assert _clean_ddg_url("//example.org/a") == "https://example.org/a"
