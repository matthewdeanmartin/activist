"""Article digestion: normalization, truncation, body extraction."""

from __future__ import annotations

import httpx

from activist.digest import digest_item, extract_article_text, normalize_text, truncate
from tests.conftest import make_item

ARTICLE_HTML = """<html><head>
<meta property="og:description" content="A short og summary.">
</head><body>
<nav>Home | About | Subscribe</nav>
<article><h1>Heat pump breakthrough</h1>
<p>{body}</p>
<script>track();</script>
</article>
<footer>© Example</footer>
</body></html>"""


def test_normalize_collapses_whitespace():
    assert normalize_text("  a\n\n b\t c  ") == "a b c"


def test_truncate_breaks_on_word_boundary():
    text = "word " * 1000
    out = truncate(text.strip(), cap=50)
    assert len(out) <= 51 and out.endswith("…")
    assert not out[:-1].endswith(" ")  # no trailing space before the ellipsis


def test_truncate_leaves_short_text_alone():
    assert truncate("short", cap=50) == "short"


def test_extract_prefers_article_and_drops_chrome():
    body = "Independent testing shows a COP of 3.4 at -20C. " * 5
    text = extract_article_text(ARTICLE_HTML.format(body=body))
    assert "COP of 3.4" in text
    assert "Subscribe" not in text and "track()" not in text and "©" not in text


def test_extract_falls_back_to_og_description():
    html = '<html><head><meta property="og:description" content="A short og summary."></head><body><p>x</p></body></html>'
    assert extract_article_text(html) == "A short og summary."


def test_digest_item_keeps_summary_on_fetch_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    item = make_item(summary="The   RSS\nsummary.")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        digest_item(item, client=client, fetch_body=True)
    assert item.summary == "The RSS summary."


def test_digest_item_upgrades_to_article_body():
    body = "Much longer article text with real detail. " * 10
    html = ARTICLE_HTML.format(body=body)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    item = make_item(summary="Thin RSS stub.")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        digest_item(item, client=client, fetch_body=True)
    assert "real detail" in item.summary
    assert len(item.summary) <= 2001  # SUMMARY_CAP plus the ellipsis


def test_digest_item_without_body_fetch_only_normalizes():
    item = make_item(summary="  spaced   out  ")
    digest_item(item)
    assert item.summary == "spaced out"
