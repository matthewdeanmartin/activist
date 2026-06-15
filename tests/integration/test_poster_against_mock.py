"""The full poster pipeline (claim -> publish -> receipt) against the mock.

``tests/test_poster.py`` already proves the poster's state machine with a
dry-run transport. This suite swaps in the *real* ``MastodonTransport`` pointed
at ``mastodon_mock`` and asserts the live publish path writes through: rows reach
``published`` with a real status id, the toot is actually on the server, and the
idempotency key prevents a re-tick from double-posting.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import httpx

from activist.config import AppConfig
from activist.poster import poster_tick
from activist.store import APPROVED, PENDING, PUBLISHED, Store
from activist.transport import MastodonTransport
from tests.test_store import make_row

# The seeded bot row identity. The token (bot_token) is what actually selects
# the server-side account; the row's identity only has to match cfg.mastodon_id.
IDENTITY = "BOT"
PER_HOUR = 60  # 1-minute spacing so two staggered slots can both publish


def make_cfg(tmp_path: Path) -> AppConfig:
    cfg = AppConfig()
    cfg.db_path = tmp_path / "queue.db"
    cfg.dryrun_log = tmp_path / "published_dryrun.jsonl"
    cfg.poster_lock = tmp_path / "poster.lock"
    cfg.mastodon_id = IDENTITY
    cfg.default_visibility = "unlisted"
    return cfg


def approve(store: Store, row_id: str, text: str, slot: str) -> None:
    store.add_pending(make_row(id=row_id, identity=IDENTITY, text=text, scheduled_for=slot))
    store.transition(row_id, PENDING, APPROVED, "human")


def test_poster_tick_publishes_live_to_the_mock(
    tmp_path: Path, bot_transport: MastodonTransport, mock_server_url: str
) -> None:
    cfg = make_cfg(tmp_path)
    store = Store(cfg.db_path)
    approve(store, "live-post-1", "Heat pumps work below freezing; the myth is decades out of date.", "2026-06-01T09:00:00")

    tick = poster_tick(cfg, store, bot_transport, per_hour=PER_HOUR)

    assert tick.published == ["live-post-1"]
    assert not tick.failed and not tick.requeued

    row = store.get("live-post-1")
    assert row.status == PUBLISHED
    # A real, server-assigned id — not a dry-run placeholder.
    assert row.mastodon_status_id and not row.mastodon_status_id.startswith("dryrun-")
    assert row.published_at

    # And it's genuinely on the server.
    with httpx.Client(base_url=mock_server_url, headers={"Authorization": "Bearer bot_token"}) as client:
        fetched = client.get(f"/api/v1/statuses/{row.mastodon_status_id}")
        fetched.raise_for_status()
        assert "below freezing" in fetched.json()["content"]
        assert fetched.json()["visibility"] == "unlisted"


def test_second_tick_is_idempotent_no_double_post(
    tmp_path: Path, bot_transport: MastodonTransport
) -> None:
    """Re-running the tick on a row the server already has must not duplicate it.

    We force the situation by publishing once, then resetting the local row to
    approved (as if the DB write had been lost after the POST landed). The
    Idempotency-Key (= content id) makes the second publish return the same
    status instead of creating a new one.
    """
    cfg = make_cfg(tmp_path)
    store = Store(cfg.db_path)
    approve(store, "idem-row-1", "post once even across a crash", "2026-06-01T09:00:00")

    first = poster_tick(cfg, store, bot_transport, per_hour=PER_HOUR)
    assert first.published == ["idem-row-1"]
    first_status_id = store.get("idem-row-1").mastodon_status_id

    # Simulate a lost receipt write: row is back to approved (and its published
    # clock cleared so pacing doesn't defer it), but the server still has it.
    # PUBLISHED->APPROVED isn't a legal in-app transition, so we force it in SQL
    # to reproduce the crash-after-POST scenario directly.
    with sqlite3.connect(cfg.db_path) as conn:
        conn.execute(
            "UPDATE content SET status=?, mastodon_status_id='', published_at='' WHERE id=?",
            (APPROVED, "idem-row-1"),
        )
    second = poster_tick(cfg, store, bot_transport, per_hour=PER_HOUR)

    assert second.published == ["idem-row-1"]
    # Same server id both times → no duplicate toot.
    assert store.get("idem-row-1").mastodon_status_id == first_status_id


def test_publish_failure_marks_row_failed(tmp_path: Path, mock_server_url: str) -> None:
    """A 4xx from the server lands the row in ``failed`` (the error taxonomy).

    We point the transport's writer at a token the mock rejects, so the POST
    422/401s and the poster records the failure rather than publishing.
    """
    from activist.mastodon_client import MastodonCredentials, MastodonWriter

    cfg = make_cfg(tmp_path)
    store = Store(cfg.db_path)
    approve(store, "doomed-1", "this will fail to post", "2026-06-01T09:00:00")

    bad_writer = MastodonWriter(
        MastodonCredentials(
            identity=IDENTITY,
            base_url=mock_server_url,
            client_id="x",
            client_secret="y",
            access_token="not-a-real-token",
        )
    )
    transport = MastodonTransport(writer=bad_writer, require_gate=False)
    try:
        tick = poster_tick(cfg, store, transport, per_hour=PER_HOUR)
    finally:
        transport.close()

    assert tick.published == []
    assert tick.failed == ["doomed-1"]
    assert store.get("doomed-1").status == "failed"
