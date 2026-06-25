"""Fetcher Phase F2: the full live chain fetch → engine → moderate → store.

The repo's fixture feeds are served through httpx.MockTransport, so MockBot
produces the same known reactions as the e2e fixture run — but arriving via
"live" HTTP into the queue store instead of a feed.toml.
"""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import httpx
import pytest

from activist import state
from activist.config import AppConfig, FeedConfig
from activist.engine import MockBot
from activist.fetch import run_news_chain
from activist.ratelimit import continued_slot
from activist.store import PENDING, Store

NOW = dt.datetime(2026, 6, 12, 9, 0, 0, tzinfo=dt.UTC)


@pytest.fixture
def workspace(tmp_path, repo_root):
    """Same pristine-seed staging as test_e2e: pinned opinions, empty memory."""
    shutil.copytree(repo_root / "persona", tmp_path / "persona")
    shutil.copyfile(
        repo_root / "tests" / "seed_opinions.toml", tmp_path / "persona" / "opinions.toml"
    )
    memory = tmp_path / "persona" / "memory"
    shutil.rmtree(memory, ignore_errors=True)
    memory.mkdir()
    return tmp_path


def make_cfg(workspace: Path, repo_root: Path) -> AppConfig:
    cfg = AppConfig()
    cfg.persona_dir = workspace / "persona"
    cfg.cache_dir = workspace / "cache"
    cfg.db_path = workspace / "data" / "queue.db"
    cfg.out_dir = workspace / "out"
    cfg.policies_dir = repo_root / "policies"
    cfg.feeds = [
        FeedConfig(name=path.stem, url=f"https://wire.example/{path.name}")
        for path in sorted((repo_root / "fixtures" / "feeds").glob("*.xml"))
    ]
    return cfg


def fixture_client(repo_root: Path) -> httpx.Client:
    feeds_dir = repo_root / "fixtures" / "feeds"

    def handler(request: httpx.Request) -> httpx.Response:
        path = feeds_dir / request.url.path.lstrip("/")
        if not path.exists():
            return httpx.Response(404)
        return httpx.Response(200, content=path.read_bytes())

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_chain_queues_moderated_spaced_drafts(workspace, repo_root):
    cfg = make_cfg(workspace, repo_root)
    store = Store(cfg.db_path)
    with fixture_client(repo_root) as client:
        result = run_news_chain(cfg, MockBot(), store, client=client, now=NOW)

    # Same engine outcomes as the fixture e2e run: 8 items, 5 drafts.
    assert len(result.fetch.new_items) == 8
    assert len(result.posts) == 5
    assert result.inserted == 5 and result.duplicates == 0

    rows = store.list_by_status(PENDING)
    assert len(rows) == 5
    # Clean fixture posts carry footer + source link, so no error flags.
    assert result.errors == 0
    changed = [r for r in rows if r.opinion_change]
    assert len(changed) == 1
    assert changed[0].opinion_change["key"] == "heat-pump-top-pick"
    assert all(r.identity == "TECH" and r.kind == "post" for r in rows)

    # Slots spaced at the persona's 4/hour = 15 minutes, starting from now.
    slots = sorted(r.scheduled_for for r in rows)
    assert slots[0] == "2026-06-12T09:00:00+00:00"
    parsed = [dt.datetime.fromisoformat(s) for s in slots]
    assert all((b - a) == dt.timedelta(minutes=15) for a, b in zip(parsed, parsed[1:]))

    # Persona state applied exactly like the fixture path.
    opinions = state.load_opinions(cfg.persona_dir / "opinions.toml")
    assert "GW-200" in opinions["heat-pump-top-pick"].stance
    assert len(state.load_seen_ids(cfg.persona_dir / "memory")) == 8

    # Ops event recorded for the UI strip; debug artifacts written.
    assert "5 drafts queued" in store.last_event("fetch").detail
    assert result.feed_html is not None and result.feed_html.exists()


def test_chain_second_run_adds_nothing(workspace, repo_root):
    cfg = make_cfg(workspace, repo_root)
    store = Store(cfg.db_path)
    with fixture_client(repo_root) as client:
        run_news_chain(cfg, MockBot(), store, client=client, now=NOW)
        second = run_news_chain(
            cfg, MockBot(), store, client=client, now=NOW + dt.timedelta(hours=1)
        )
    assert second.fetch.seen_skipped == 8
    assert second.posts == [] and second.inserted == 0
    assert store.counts()[PENDING] == 5


def test_chain_dry_run_touches_nothing(workspace, repo_root):
    cfg = make_cfg(workspace, repo_root)
    store = Store(cfg.db_path)
    before_opinions = (cfg.persona_dir / "opinions.toml").read_text(encoding="utf-8")
    with fixture_client(repo_root) as client:
        result = run_news_chain(cfg, MockBot(), store, client=client, now=NOW, dry_run=True)
    assert len(result.posts) == 5  # full preview...
    assert store.counts()[PENDING] == 0  # ...but nothing landed
    assert (cfg.persona_dir / "opinions.toml").read_text(encoding="utf-8") == before_opinions
    assert not (cfg.persona_dir / "memory" / "seen.jsonl").exists()
    assert not cfg.cache_dir.exists()
    assert not cfg.out_dir.exists()


class CountingBot:
    """Wraps MockBot to count engine.react() calls without changing its logic."""

    name = "mockbot"

    def __init__(self):
        self._inner = MockBot()
        self.calls = 0

    def react(self, *args, **kwargs):
        self.calls += 1
        return self._inner.react(*args, **kwargs)

    def reply(self, *args, **kwargs):
        return self._inner.reply(*args, **kwargs)


def test_chain_engine_call_budget_caps_calls_and_defers_rest(workspace, repo_root):
    """A low call_budget stops paying for engine.react() once spent, and the
    items it never got to are left off seen.jsonl (deferred, not dropped) so
    a later run with budget can still pick them up."""
    cfg = make_cfg(workspace, repo_root)
    cfg.engine_call_budget = 3
    store = Store(cfg.db_path)
    bot = CountingBot()
    with fixture_client(repo_root) as client:
        result = run_news_chain(cfg, bot, store, client=client, now=NOW)

    assert bot.calls == 3
    assert len(result.posts) <= 3
    # Full fixture run (no budget) sees and marks all 8 items; the budgeted
    # run must mark fewer, since some were deferred rather than evaluated.
    assert len(state.load_seen_ids(cfg.persona_dir / "memory")) < 8


def test_chain_engine_call_budget_then_unbudgeted_run_picks_up_rest(workspace, repo_root):
    """Items deferred by the budget aren't lost -- a follow-up run without a
    (or with a higher) budget reconsiders them, since they were never marked
    seen."""
    cfg = make_cfg(workspace, repo_root)
    cfg.engine_call_budget = 3
    store = Store(cfg.db_path)
    with fixture_client(repo_root) as client:
        run_news_chain(cfg, MockBot(), store, client=client, now=NOW)
        cfg.engine_call_budget = None
        second = run_news_chain(cfg, MockBot(), store, client=client, now=NOW + dt.timedelta(hours=1))

    # Together the two runs see everything the unbudgeted single run would.
    assert len(state.load_seen_ids(cfg.persona_dir / "memory")) == 8
    assert len(second.posts) > 0  # the deferred items got their engine.react() this time


def test_continued_slot_from_empty_queue():
    assert continued_slot(0, 4, NOW, None) == "2026-06-12T09:00:00+00:00"
    assert continued_slot(2, 4, NOW, None) == "2026-06-12T09:30:00+00:00"


def test_continued_slot_after_future_backlog():
    # The queue already stretches past now: continue after it, spaced.
    last = "2026-06-12T11:00:00+00:00"
    assert continued_slot(0, 4, NOW, last) == "2026-06-12T11:15:00+00:00"
    assert continued_slot(1, 4, NOW, last) == "2026-06-12T11:30:00+00:00"


def test_continued_slot_ignores_stale_history():
    # Everything queued is long published; new drafts start from now.
    assert continued_slot(0, 4, NOW, "2026-06-01T09:00:00+00:00") == "2026-06-12T09:00:00+00:00"


def test_continued_slot_one_per_hour():
    assert continued_slot(1, 1, NOW, None) == "2026-06-12T10:00:00+00:00"
