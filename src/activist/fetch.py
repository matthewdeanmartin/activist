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

from . import __version__, ratelimit, relevance, state
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
                "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
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
    mark_seen: bool | None = None,
) -> FetchResult:
    """Fetch all configured feeds, digest, and dedupe against seen.jsonl.

    Unless ``dry_run``, new items are appended to persona/memory/seen.jsonl
    with the same row shape the pipeline writes (id, url, title, date_seen,
    topics, relevant). ``topics`` defaults to the persona's beats.

    ``mark_seen`` defaults to ``not dry_run``; the full chain passes False
    because the engine pass writes richer seen rows itself.
    """
    if mark_seen is None:
        mark_seen = not dry_run
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
        if mark_seen and seen_rows:
            state.append_seen(cfg.persona_dir / "memory", seen_rows)
    finally:
        if own_client:
            client.close()
    return result


@dataclass
class ChainResult:
    """One full fetch→engine→moderate→store pass (fetcher Phase F2)."""

    fetch: FetchResult
    posts: list = field(default_factory=list)  # DraftPosts the engine produced
    inserted: int = 0
    duplicates: int = 0
    errors: int = 0  # moderation error flags across inserted drafts
    warns: int = 0
    feed_toml: Path | None = None  # legacy debug artifact, if written
    feed_html: Path | None = None
    log_lines: list[str] = field(default_factory=list)


def run_news_chain(
    cfg: AppConfig,
    engine,
    store,
    dry_run: bool = False,
    client: httpx.Client | None = None,
    now: dt.datetime | None = None,
    llm_moderator=None,
) -> ChainResult:
    """fetch → digest → dedupe → engine → moderate → pending_review rows.

    ``dry_run`` previews the whole chain without touching the cache,
    persona/, the store, or out/.
    """
    import sqlite3

    from .moderation import ModerationContext, moderate_post
    from .moderation.policies import load_app_policy, load_instance_policy
    from .pipeline import apply_engine_state, react_to_items
    from .queue_io import write_feed, _post_dict
    from .store import row_from_draft

    persona = state.load_persona(cfg.persona_dir / "persona.toml")
    opinions = state.load_opinions(cfg.persona_dir / "opinions.toml")
    memory_dir = cfg.persona_dir / "memory"
    seen_ids = state.load_seen_ids(memory_dir)
    recent_said = state.load_said(memory_dir, n=5)
    instance_policies = {
        domain: load_instance_policy(cfg.policies_dir, domain)
        for domain in cfg.instances
        if domain not in cfg.instance_rate_limits
    }
    app_limit = cfg.rate_limit_posts_per_hour or persona.posts_per_hour
    per_hour = ratelimit.effective_hourly_limit(
        app_limit, instance_policies, cfg.instance_rate_limits
    )
    now = ratelimit.aware_utc(now or dt.datetime.now(dt.UTC))
    date = now.date().isoformat()

    fetch_result = fetch_news(
        cfg, client=client, dry_run=dry_run, topics=persona.topics, mark_seen=False
    )
    result = ChainResult(fetch=fetch_result)
    result.log_lines.append(
        f"FETCH feeds_ok={fetch_result.feeds_ok} unchanged={fetch_result.feeds_unchanged} "
        f"failed={fetch_result.feeds_failed} new={len(fetch_result.new_items)} "
        f"seen={fetch_result.seen_skipped}"
    )
    result.log_lines.append(
        f"PACING {per_hour}/hour (app={app_limit}, instances={sorted(cfg.instances)})"
    )

    last_slot = store.last_scheduled_for(cfg.mastodon_id)
    out = react_to_items(
        fetch_result.new_items,
        persona=persona,
        opinions=opinions,
        knowledge_path=cfg.persona_dir / "knowledge.md",
        seen_ids=seen_ids,
        recent_said=recent_said,
        date=date,
        engine=engine,
        max_posts=persona.max_posts_per_run,
        slot_for=lambda index: ratelimit.continued_slot(index, per_hour, now, last_slot),
        engine_call_budget=cfg.engine_call_budget,
    )
    result.posts = out.posts
    result.log_lines.extend(out.log_lines)

    ctx = ModerationContext(
        disclosure=persona.disclosure,
        app_policy=load_app_policy(cfg.app_policy),
        instance_policies=instance_policies,
    )
    rows = []
    for post in out.posts:
        flags = moderate_post(_post_dict(post), ctx, llm_moderator)
        result.errors += sum(f.severity == "error" for f in flags)
        result.warns += sum(f.severity == "warn" for f in flags)
        rows.append(row_from_draft(post, flags, identity=cfg.mastodon_id))

    if dry_run:
        result.log_lines.append("DRY-RUN store, persona/, and out/ untouched")
        return result

    for row in rows:
        try:
            store.add_pending(row)
            result.inserted += 1
        except sqlite3.IntegrityError:
            result.duplicates += 1
            result.log_lines.append(f"DUPLICATE {row.id} already queued; skipped")

    apply_engine_state(cfg.persona_dir, date, engine.name, opinions, out)
    store.log_event(
        "-",
        "fetcher",
        "fetch",
        f"{len(fetch_result.new_items)} new items, {result.inserted} drafts queued, "
        f"{fetch_result.feeds_failed} feeds failed",
    )

    if cfg.write_artifacts and out.posts:
        run_dir = cfg.out_dir / date
        result.feed_toml = run_dir / "fetch-feed.toml"
        write_feed(
            result.feed_toml,
            {
                "date": date,
                "engine": engine.name,
                "persona_name": persona.name,
                "persona_handle": persona.handle,
                "persona_bio": persona.bio,
                "items_ingested": len(fetch_result.new_items),
                "items_relevant": out.relevant_count,
                "posts": len(out.posts),
                "posts_per_hour": per_hour,
                "instances": sorted(instance_policies),
                "diary": "\n".join(out.diary),
            },
            out.posts,
        )
        from . import render

        result.feed_html = render.render_feed(result.feed_toml)
    return result
