"""Poster Phase P1: claim CAS, pacing backstop, dry-run transport, lockfile."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import pytest

from activist.config import AppConfig
from activist.poster import PosterLock, poster_tick
from activist.store import APPROVED, FAILED, PENDING, PUBLISHED, Store
from activist.transport import DryRunTransport, MastodonTransport, PublishReceipt
from tests.test_store import make_row

PER_HOUR = 4  # 15-minute spacing


def make_cfg(tmp_path: Path) -> AppConfig:
    cfg = AppConfig()
    cfg.db_path = tmp_path / "queue.db"
    cfg.dryrun_log = tmp_path / "published_dryrun.jsonl"
    cfg.poster_lock = tmp_path / "poster.lock"
    return cfg


def approved_row(store: Store, row_id: str, slot: str) -> None:
    store.add_pending(make_row(id=row_id, scheduled_for=slot))
    store.transition(row_id, PENDING, APPROVED, "human")


def backdate_publish(db: Path, row_id: str, when: str) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE content SET published_at=? WHERE id=?", (when, row_id))


def test_dry_run_publishes_one_and_defers_backlog(tmp_path):
    cfg = make_cfg(tmp_path)
    store = Store(cfg.db_path)
    approved_row(store, "one", "2026-06-01T09:00:00")
    approved_row(store, "two", "2026-06-01T09:15:00")
    transport = DryRunTransport(cfg.dryrun_log)

    tick = poster_tick(cfg, store, transport, per_hour=PER_HOUR)
    # Both slots are long past (backlog), but the backstop allows only one
    # publish per spacing window no matter what the queue says.
    assert tick.due == 2
    assert tick.published == ["one"] and tick.deferred_pacing == 1
    row = store.get("one")
    assert row.status == PUBLISHED
    assert row.mastodon_status_id.startswith("dryrun-")
    assert row.published_url == cfg.dryrun_log.as_uri()
    assert row.published_at
    assert store.get("two").status == APPROVED

    lines = [json.loads(l) for l in cfg.dryrun_log.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1
    assert lines[0]["content_id"] == "one" and lines[0]["text"] == row.text

    # Once the spacing window has passed, the next tick drains the next row.
    backdate_publish(cfg.db_path, "one", "2026-06-01T09:00:00")
    second = poster_tick(cfg, store, transport, per_hour=PER_HOUR)
    assert second.published == ["two"]

    # And a third tick (after the window) finds nothing due.
    backdate_publish(cfg.db_path, "two", "2026-06-01T09:15:00")
    third = poster_tick(cfg, store, transport, per_hour=PER_HOUR)
    assert third.due == 0 and third.published == []


def test_future_slots_are_not_due(tmp_path):
    cfg = make_cfg(tmp_path)
    store = Store(cfg.db_path)
    future = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=2)).isoformat(timespec="seconds")
    approved_row(store, "later", future)
    tick = poster_tick(cfg, store, DryRunTransport(cfg.dryrun_log), per_hour=PER_HOUR)
    assert tick.due == 0
    assert store.get("later").status == APPROVED


def test_pending_rows_are_never_picked_up(tmp_path):
    cfg = make_cfg(tmp_path)
    store = Store(cfg.db_path)
    store.add_pending(make_row(id="unreviewed", scheduled_for="2026-06-01T09:00:00"))
    tick = poster_tick(cfg, store, DryRunTransport(cfg.dryrun_log), per_hour=PER_HOUR)
    assert tick.due == 0


class RacyStore(Store):
    """Simulates the human un-approving between the due query and the claim."""

    def due_approved(self, identity, now):
        rows = super().due_approved(identity, now)
        for row in rows:
            self.transition(row.id, APPROVED, PENDING, "human", "changed my mind")
        return rows


def test_lost_claim_race_skips_row(tmp_path):
    cfg = make_cfg(tmp_path)
    store = RacyStore(cfg.db_path)
    approved_row(store, "contested", "2026-06-01T09:00:00")
    tick = poster_tick(cfg, store, DryRunTransport(cfg.dryrun_log), per_hour=PER_HOUR)
    assert tick.skipped_race == 1 and tick.published == []
    assert store.get("contested").status == PENDING
    assert not cfg.dryrun_log.exists()


class ExplodingTransport:
    name = "exploding"

    def publish(self, row) -> PublishReceipt:
        raise RuntimeError("HTTP 500 from nowhere")


def test_transport_failure_lands_in_failed(tmp_path):
    cfg = make_cfg(tmp_path)
    store = Store(cfg.db_path)
    approved_row(store, "doomed", "2026-06-01T09:00:00")
    tick = poster_tick(cfg, store, ExplodingTransport(), per_hour=PER_HOUR)
    assert tick.failed == ["doomed"]
    row = store.get("doomed")
    assert row.status == FAILED
    assert any(
        e.action == "fail" and "HTTP 500" in e.detail for e in store.events("doomed")
    )
    # failed rows are not retried automatically — the next tick ignores them
    second = poster_tick(cfg, store, DryRunTransport(cfg.dryrun_log), per_hour=PER_HOUR)
    assert second.due == 0


def test_identity_isolation(tmp_path):
    cfg = make_cfg(tmp_path)  # cfg.mastodon_id == "TECH"
    store = Store(cfg.db_path)
    store.add_pending(make_row(id="other", identity="DMV", scheduled_for="2026-06-01T09:00:00"))
    store.transition("other", PENDING, APPROVED, "human")
    tick = poster_tick(cfg, store, DryRunTransport(cfg.dryrun_log), per_hour=PER_HOUR)
    assert tick.due == 0
    assert store.get("other").status == APPROVED


def test_mastodon_transport_refuses_to_exist():
    with pytest.raises(NotImplementedError, match="Phase P2|gated"):
        MastodonTransport()


def test_poster_lock_mutual_exclusion(tmp_path):
    lock_path = tmp_path / "poster.lock"
    with PosterLock(lock_path):
        assert lock_path.exists()
        with pytest.raises(RuntimeError, match="another poster"):
            with PosterLock(lock_path):
                pass
    assert not lock_path.exists()  # released on exit
    with PosterLock(lock_path):  # and reusable
        pass
