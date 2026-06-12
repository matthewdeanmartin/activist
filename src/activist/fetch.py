"""Live RSS/Atom fetching with a conditional-GET cache (fetcher Phase F1).

Each feed gets a small JSON sidecar in the cache dir holding the ETag /
Last-Modified the server sent; the next request sends them back and a 304
skips parsing entirely. One dead feed never kills the run.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import __version__, relevance, state
from .config import AppConfig, FeedConfig
from .digest import digest_item
from .ingest import parse_feed_bytes
from .models import NewsItem

LOGGER = logging.getLogger(__name__)

USER_AGENT = f"activist/{__version__} (+https://github.com/matthewdeanmartin/activist)"
TIMEOUT = httpx.Timeout(20.0)

OK = "ok"
UNCHANGED = "unchanged"  # 304
FAILED = "failed"


@dataclass
class FeedOutcome:
    name: str
    url: str
    status: str  # OK | UNCHANGED | FAILED
    items: list[NewsItem] = field(default_factory=list)
    detail: str = ""


@dataclass
class FetchResult:
    outcomes: list[FeedOutcome] = field(default_factory=list)
    new_items: list[NewsItem] = field(default_factory=list)
    seen_skipped: int = 0
    relevant_topics: dict[str, list[str]] = field(default_factory=dict)  # item id → topics

    @property
    def feeds_ok(self) -> int:
        return sum(1 for o in self.outcomes if o.status == OK)

    @property
    def feeds_unchanged(self) -> int:
        return sum(1 for o in self.outcomes if o.status == UNCHANGED)

    @property
    def feeds_failed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == FAILED)


def make_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True
    )


def _cache_path(cache_dir: Path, url: str) -> Path:
    return cache_dir / (hashlib.sha256(url.encode("utf-8")).hexdigest()[:12] + ".json")


def _load_validators(cache_dir: Path, url: str) -> dict:
    path = _cache_path(cache_dir, url)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_validators(cache_dir: Path, url: str, response: httpx.Response) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _cache_path(cache_dir, url).write_text(
        json.dumps(
            {
                "url": url,
                "etag": response.headers.get("ETag", ""),
                "last_modified": response.headers.get("Last-Modified", ""),
                "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
        ),
        encoding="utf-8",
    )


def fetch_feed(
    client: httpx.Client, feed: FeedConfig, cache_dir: Path, write_cache: bool = True
) -> FeedOutcome:
    """Fetch one feed; 304 and any HTTP/parse failure degrade, never raise."""
    headers = {}
    validators = _load_validators(cache_dir, feed.url)
    if validators.get("etag"):
        headers["If-None-Match"] = validators["etag"]
    if validators.get("last_modified"):
        headers["If-Modified-Since"] = validators["last_modified"]
    try:
        response = client.get(feed.url, headers=headers)
    except httpx.HTTPError as exc:
        LOGGER.warning("Feed %s failed: %s", feed.name, exc)
        return FeedOutcome(feed.name, feed.url, FAILED, detail=str(exc))
    if response.status_code == 304:
        return FeedOutcome(feed.name, feed.url, UNCHANGED)
    if response.status_code != 200:
        LOGGER.warning("Feed %s returned HTTP %s", feed.name, response.status_code)
        return FeedOutcome(feed.name, feed.url, FAILED, detail=f"HTTP {response.status_code}")
    if write_cache:
        _save_validators(cache_dir, feed.url, response)
    items = parse_feed_bytes(response.content, source=feed.name)
    return FeedOutcome(feed.name, feed.url, OK, items=items)


def fetch_news(
    cfg: AppConfig,
    client: httpx.Client | None = None,
    dry_run: bool = False,
    topics: list[str] | None = None,
) -> FetchResult:
    """Fetch all configured feeds, digest, and dedupe against seen.jsonl.

    Unless ``dry_run``, new items are appended to persona/memory/seen.jsonl
    with the same row shape the pipeline writes (id, url, title, date_seen,
    topics, relevant). ``topics`` defaults to the persona's beats.
    """
    own_client = client is None
    if client is None:
        client = make_client()
    if topics is None:
        persona = state.load_persona(cfg.persona_dir / "persona.toml")
        topics = persona.topics
    result = FetchResult()
    try:
        seen_ids = state.load_seen_ids(cfg.persona_dir / "memory")
        today = dt.date.today().isoformat()
        seen_rows: list[dict] = []
        found_ids: set[str] = set()
        for feed in cfg.feeds:
            outcome = fetch_feed(client, feed, cfg.cache_dir, write_cache=not dry_run)
            result.outcomes.append(outcome)
            for item in outcome.items:
                if item.id in seen_ids or item.id in found_ids:
                    result.seen_skipped += 1
                    continue
                found_ids.add(item.id)
                # Dedupe BEFORE digesting: never fetch bodies for old items.
                digest_item(item, client=client, fetch_body=cfg.fetch_article_body)
                matched = relevance.match_topics(item, topics)
                result.new_items.append(item)
                result.relevant_topics[item.id] = matched
                seen_rows.append(
                    {
                        "id": item.id,
                        "url": item.url,
                        "title": item.title,
                        "date_seen": today,
                        "topics": matched,
                        "relevant": bool(matched),
                    }
                )
        if not dry_run and seen_rows:
            state.append_seen(cfg.persona_dir / "memory", seen_rows)
    finally:
        if own_client:
            client.close()
    return result
