"""Live RSS fetching: conditional GET, failure isolation, dedupe. No network —
everything goes through httpx.MockTransport."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from activist.config import AppConfig, FeedConfig
from activist.fetch import fetch_feed, fetch_news

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test Wire</title>
<item><title>Heat pump breakthrough</title><link>https://example.com/hp</link>
<description>A heat pumps story.</description></item>
<item><title>Sourdough tips</title><link>https://example.com/bread</link>
<description>Nothing to do with the beat.</description></item>
</channel></rss>"""


def client_with(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def make_cfg(tmp_path: Path, urls: list[str]) -> AppConfig:
    cfg = AppConfig()
    cfg.cache_dir = tmp_path / "cache"
    cfg.persona_dir = tmp_path / "persona"
    cfg.feeds = [FeedConfig(name=f"feed{i}", url=u) for i, u in enumerate(urls)]
    return cfg


def test_first_fetch_writes_validators_then_304(tmp_path: Path):
    cache = tmp_path / "cache"
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.headers))
        if request.headers.get("If-None-Match") == 'W/"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=RSS.encode(), headers={"ETag": 'W/"v1"'})

    feed = FeedConfig(name="wire", url="https://example.com/rss")
    with client_with(handler) as client:
        first = fetch_feed(client, feed, cache)
        second = fetch_feed(client, feed, cache)
    assert first.status == "ok" and len(first.items) == 2
    assert second.status == "unchanged" and second.items == []
    assert "if-none-match" not in calls[0]
    cached = json.loads(next(cache.glob("*.json")).read_text())
    assert cached["etag"] == 'W/"v1"'


def test_one_dead_feed_never_kills_the_run(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if "dead" in str(request.url):
            return httpx.Response(500)
        return httpx.Response(200, content=RSS.encode())

    cfg = make_cfg(tmp_path, ["https://example.com/dead", "https://example.com/rss"])
    with client_with(handler) as client:
        result = fetch_news(cfg, client=client, topics=["heat pumps"])
    assert result.feeds_failed == 1 and result.feeds_ok == 1
    assert len(result.new_items) == 2


def test_dedupe_across_runs_via_seen_jsonl(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode())

    cfg = make_cfg(tmp_path, ["https://example.com/rss"])
    with client_with(handler) as client:
        first = fetch_news(cfg, client=client, topics=["heat pumps"])
        second = fetch_news(cfg, client=client, topics=["heat pumps"])
    assert len(first.new_items) == 2
    assert second.new_items == [] and second.seen_skipped == 2
    seen = (cfg.persona_dir / "memory" / "seen.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in seen]
    assert len(rows) == 2
    by_title = {r["title"]: r for r in rows}
    assert by_title["Heat pump breakthrough"]["relevant"] is True
    assert by_title["Sourdough tips"]["relevant"] is False


def test_same_item_in_two_feeds_counted_once(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode())

    cfg = make_cfg(tmp_path, ["https://a.example/rss", "https://b.example/rss"])
    with client_with(handler) as client:
        result = fetch_news(cfg, client=client, topics=["heat pumps"])
    assert len(result.new_items) == 2 and result.seen_skipped == 2


def test_dry_run_touches_nothing(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS.encode(), headers={"ETag": 'W/"v1"'})

    cfg = make_cfg(tmp_path, ["https://example.com/rss"])
    with client_with(handler) as client:
        result = fetch_news(cfg, client=client, dry_run=True, topics=["heat pumps"])
    assert len(result.new_items) == 2
    assert not cfg.cache_dir.exists()
    assert not (cfg.persona_dir / "memory" / "seen.jsonl").exists()
