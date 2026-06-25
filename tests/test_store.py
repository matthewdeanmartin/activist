"""SQLite content queue: round-trips, lifecycle legality, CAS races."""

from __future__ import annotations

from pathlib import Path

import pytest

from activist.models import DraftPost, Flag, OpinionChange
from activist.store import (
    APPROVED,
    FAILED,
    PENDING,
    PUBLISHED,
    PUBLISHING,
    REJECTED,
    ContentRow,
    IllegalTransition,
    StaleStatus,
    Store,
    UnknownContent,
    row_from_draft,
)


def make_row(**overrides) -> ContentRow:
    defaults = dict(
        id="a3f9c1d20e77",
        kind="post",
        status=PENDING,
        text="Heat pumps rule. https://example.com/x\n🤖 bot post, human approved",
        created="2026-06-11T09:00:00",
        identity="TECH",
        source_url="https://example.com/x",
        source_title="A heat pump article",
        opinion_keys=["heat-pump-top-pick"],
        flags=[{"severity": "warn", "policy": "app", "rule": "tone", "detail": "meh"}],
        engine="mockbot",
    )
    defaults.update(overrides)
    return ContentRow(**defaults)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "queue.db")


def test_round_trip_preserves_json_fields(store: Store):
    row = make_row(opinion_change={"key": "k", "old_stance": "a", "new_stance": "b",
                                   "trigger_item": "t", "reason": "r"})
    store.add_pending(row)
    got = store.get(row.id)
    assert got.opinion_keys == ["heat-pump-top-pick"]
    assert got.opinion_change["new_stance"] == "b"
    assert got.flags[0]["severity"] == "warn"
    assert got.status == PENDING
    assert got.char_count == len(row.text)


def test_full_legal_lifecycle(store: Store):
    store.add_pending(make_row())
    store.transition("a3f9c1d20e77", PENDING, APPROVED, "human")
    store.transition("a3f9c1d20e77", APPROVED, PUBLISHING, "poster")
    store.mark_published(
        "a3f9c1d20e77",
        "status-123",
        "2026-06-11T10:00:00",
        "https://mastodon.example/@bot/123",
    )
    row = store.get("a3f9c1d20e77")
    assert row.status == PUBLISHED
    assert row.mastodon_status_id == "status-123"
    assert row.published_url == "https://mastodon.example/@bot/123"
    actions = [e.action for e in store.events("a3f9c1d20e77")]
    assert actions == ["created", "approve", "claim", "publish"]


def test_every_illegal_transition_raises(store: Store):
    store.add_pending(make_row())
    for src, dst in [
        (PENDING, PUBLISHED),     # can't skip approval
        (PENDING, PUBLISHING),    # poster can't claim unapproved content
        (REJECTED, APPROVED),     # rejected is terminal
        (PUBLISHED, PENDING),     # published is terminal
        (FAILED, PUBLISHING),     # retry goes through approved
    ]:
        with pytest.raises(IllegalTransition):
            store.transition("a3f9c1d20e77", src, dst, "test")


def test_lost_cas_race_raises_stale(store: Store):
    store.add_pending(make_row())
    store.transition("a3f9c1d20e77", PENDING, REJECTED, "human")
    # A second actor still believes the row is pending — legal pair, stale row.
    with pytest.raises(StaleStatus, match="found rejected"):
        store.transition("a3f9c1d20e77", PENDING, APPROVED, "human")


def test_unknown_content(store: Store):
    with pytest.raises(UnknownContent):
        store.get("nope")
    with pytest.raises(UnknownContent):
        store.transition("nope", PENDING, APPROVED, "human")


def test_failed_retry_path(store: Store):
    store.add_pending(make_row())
    store.transition("a3f9c1d20e77", PENDING, APPROVED, "human")
    store.transition("a3f9c1d20e77", APPROVED, PUBLISHING, "poster")
    store.transition("a3f9c1d20e77", PUBLISHING, FAILED, "poster", "HTTP 500")
    store.transition("a3f9c1d20e77", FAILED, APPROVED, "human")  # retry
    assert store.get("a3f9c1d20e77").status == APPROVED


def test_release_for_backoff_hides_until_not_before(store: Store):
    store.add_pending(make_row(scheduled_for="2026-06-11T09:00:00+00:00"))
    store.transition("a3f9c1d20e77", PENDING, APPROVED, "human")
    store.transition("a3f9c1d20e77", APPROVED, PUBLISHING, "poster")
    store.release_for_backoff(
        "a3f9c1d20e77",
        "2026-06-11T10:00:00+00:00",
        detail="HTTP 429",
    )
    row = store.get("a3f9c1d20e77")
    assert row.status == APPROVED
    assert row.not_before == "2026-06-11T10:00:00+00:00"
    assert store.due_approved("TECH", "2026-06-11T09:30:00+00:00") == []
    assert [r.id for r in store.due_approved("TECH", "2026-06-11T10:00:00+00:00")] == [
        "a3f9c1d20e77"
    ]


def test_counts_and_listing(store: Store):
    store.add_pending(make_row(id="one"))
    store.add_pending(make_row(id="two"))
    store.transition("two", PENDING, APPROVED, "human")
    counts = store.counts()
    assert counts[PENDING] == 1 and counts[APPROVED] == 1 and counts[PUBLISHED] == 0
    assert [r.id for r in store.list_by_status(PENDING)] == ["one"]


def test_duplicate_id_rejected(store: Store):
    import sqlite3

    store.add_pending(make_row())
    with pytest.raises(sqlite3.IntegrityError):
        store.add_pending(make_row())


def test_two_store_instances_share_one_db(tmp_path: Path):
    """The fetcher and the UI each hold their own Store over the same file."""
    a = Store(tmp_path / "q.db")
    b = Store(tmp_path / "q.db")
    a.add_pending(make_row())
    b.transition("a3f9c1d20e77", PENDING, APPROVED, "human")
    assert a.get("a3f9c1d20e77").status == APPROVED


def test_kv_roundtrip(store: Store):
    assert store.get_kv("since_id", "0") == "0"
    store.set_kv("since_id", "123")
    store.set_kv("since_id", "456")
    assert store.get_kv("since_id") == "456"


def test_update_flags_does_not_preserve_original(store: Store):
    store.add_pending(make_row(flags=[]))
    flags = [{"severity": "warn", "policy": "app", "rule": "llm", "detail": "check"}]
    store.update_flags("a3f9c1d20e77", flags)
    row = store.get("a3f9c1d20e77")
    assert row.flags == flags
    assert row.original_text is None
    assert any(e.action == "recheck" for e in store.events("a3f9c1d20e77"))


def test_row_from_draft_maps_reply_fields():
    post = DraftPost(
        id="d1",
        created="2026-06-11T10:00:00",
        status="draft",
        text="answer",
        char_count=6,
        source_url="",
        source_title="",
        opinion_keys=["k"],
        engine="mockbot",
        opinion_change=OpinionChange("k", "old", "new", "item", "why"),
        reply_to_id="109501",
        reply_to_author="@fan@mas.to",
        reply_to_text="question?",
    )
    flags = [Flag("warn", "app", "unverified-link", "model URL")]
    row = row_from_draft(post, flags, identity="TECH")
    assert row.kind == "reply"
    assert row.in_reply_to_status_id == "109501"
    assert row.scheduled_for == post.created
    assert row.flags[0]["rule"] == "unverified-link"
    assert row.opinion_change["reason"] == "why"


# --- delete (admin site §4) ---------------------------------------------------


def test_delete_removes_row_but_keeps_history(store: Store):
    store.add_pending(make_row(id="junk"))
    store.delete("junk")
    assert not store.has("junk")
    # the audit trail survives the row it described
    actions = {e.action for e in store.events("junk")}
    assert "delete" in actions


def test_delete_refuses_published(store: Store):
    store.add_pending(make_row(id="p"))
    store.transition("p", PENDING, APPROVED, "human")
    store.transition("p", APPROVED, PUBLISHING, "poster")
    store.transition("p", PUBLISHING, PUBLISHED, "poster")
    with pytest.raises(IllegalTransition):
        store.delete("p")
    assert store.has("p")


def test_delete_refuses_publishing(store: Store):
    store.add_pending(make_row(id="p"))
    store.transition("p", PENDING, APPROVED, "human")
    store.transition("p", APPROVED, PUBLISHING, "poster")
    with pytest.raises(IllegalTransition):
        store.delete("p")
    assert store.has("p")


def test_delete_unknown_raises(store: Store):
    with pytest.raises(UnknownContent):
        store.delete("ghost")


def test_upcoming_is_approved_for_identity_in_slot_order(store: Store):
    store.add_pending(make_row(id="b", identity="TECH", scheduled_for="2026-06-11T10:00:00"))
    store.add_pending(make_row(id="a", identity="TECH", scheduled_for="2026-06-11T09:00:00"))
    store.add_pending(make_row(id="other", identity="DMV", scheduled_for="2026-06-11T08:00:00"))
    for cid in ("a", "b", "other"):
        store.transition(cid, PENDING, APPROVED, "human")
    # a pending row for TECH must NOT appear (upcoming = approved only)
    store.add_pending(make_row(id="pend", identity="TECH"))
    rows = store.upcoming("TECH")
    assert [r.id for r in rows] == ["a", "b"]
