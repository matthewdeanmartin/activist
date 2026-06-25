"""FastAPI admin site: reads, action buttons per status, CAS 409s, delete,
the already-posted 501 stubs (spec/admin_site.md §8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from activist.api import create_api
from activist.config import AppConfig
from activist.moderation import ModerationContext
from activist.models import Flag
from activist.store import APPROVED, FAILED, PENDING, PUBLISHED, REJECTED, Store
from tests.test_store import make_row

DISCLOSURE = "🤖 bot post, human approved"
GOOD_TEXT = f"Heat pumps still win. https://example.com/x\n{DISCLOSURE}"


class FakeLlmModerator:
    name = "fake-llm"

    def review(self, post, ctx):
        return [Flag("warn", "app", "llm-tone", "reviewed")]


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "queue.db")
    s.add_pending(make_row(id="pend1", text=GOOD_TEXT))
    s.add_pending(make_row(id="appr1", text=GOOD_TEXT))
    s.transition("appr1", PENDING, APPROVED, "human")
    s.add_pending(make_row(id="fail1", text=GOOD_TEXT))
    s.transition("fail1", PENDING, APPROVED, "human")
    s.transition("fail1", APPROVED, "publishing", "poster")
    s.transition("fail1", "publishing", FAILED, "poster", "HTTP 500")
    s.add_pending(make_row(id="pub1", text=GOOD_TEXT))
    s.transition("pub1", PENDING, APPROVED, "human")
    s.transition("pub1", APPROVED, "publishing", "poster")
    s.transition("pub1", "publishing", PUBLISHED, "poster")
    return s


@pytest.fixture
def client(store: Store, tmp_path: Path, enable_network):
    # Starlette's TestClient runs the ASGI app via an anyio blocking portal,
    # which opens a loopback socketpair. pytest-network (patched on by this
    # project) would reject that, so depend on enable_network — same pattern
    # tests/integration/conftest.py uses for the mock Mastodon server.
    ctx = ModerationContext(disclosure=DISCLOSURE, app_policy="")
    app = create_api(
        AppConfig(db_path=tmp_path / "queue.db"),
        store=store,
        mod_ctx=ctx,
        llm_moderator=FakeLlmModerator(),
    )
    with TestClient(app) as test_client:
        yield test_client


# --- reads ------------------------------------------------------------------


def test_queue_default_is_pending(client):
    resp = client.get("/api/queue")
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert ids == {"pend1"}


def test_queue_unknown_status_404(client):
    assert client.get("/api/queue", params={"status": "bogus"}).status_code == 404


def test_upcoming_lists_approved_for_identity(client):
    rows = client.get("/api/upcoming").json()
    assert {r["id"] for r in rows} == {"appr1"}
    assert all(r["status"] == APPROVED for r in rows)


def test_content_detail_includes_events(client):
    body = client.get("/api/content/pend1").json()
    assert body["content"]["id"] == "pend1"
    assert any(e["action"] == "created" for e in body["events"])
    assert body["content"]["char_count"] == len(GOOD_TEXT)


def test_counts(client):
    counts = client.get("/api/counts").json()
    assert counts[PENDING] == 1 and counts[PUBLISHED] == 1


# --- transitions ------------------------------------------------------------


def test_approve(client, store):
    resp = client.post("/api/content/pend1/approve")
    assert resp.status_code == 200 and resp.json()["status"] == APPROVED
    assert store.get("pend1").status == APPROVED


def test_reject_records_reason(client, store):
    client.post("/api/content/pend1/reject", json={"reason": "off-voice"})
    row = store.get("pend1")
    assert row.status == REJECTED and row.rejected_reason == "off-voice"


def test_unapprove_puts_back_in_queue(client, store):
    client.post("/api/content/appr1/unapprove")
    assert store.get("appr1").status == PENDING


def test_retry(client, store):
    client.post("/api/content/fail1/retry")
    assert store.get("fail1").status == APPROVED


def test_illegal_transition_409(client):
    # pub1 is published; approve expects pending -> 409 illegal (CAS lost / illegal)
    resp = client.post("/api/content/pub1/approve")
    assert resp.status_code == 409


def test_lost_race_returns_409(client, store):
    store.transition("pend1", PENDING, REJECTED, "human")  # another tab won
    resp = client.post("/api/content/pend1/approve")
    assert resp.status_code == 409
    assert store.get("pend1").status == REJECTED


def test_unknown_id_404(client):
    assert client.post("/api/content/ghost/approve").status_code == 404


# --- edit / edit-approve / recheck ------------------------------------------


def test_edit_remoderates(client, store):
    resp = client.post("/api/content/pend1/edit", json={"text": "x" * 501})
    assert resp.status_code == 200
    rules = {f["rule"] for f in store.get("pend1").flags}
    assert "char-limit" in rules


def test_edit_preserves_original(client, store):
    client.post("/api/content/pend1/edit", json={"text": GOOD_TEXT + " more"})
    assert store.get("pend1").original_text == GOOD_TEXT


def test_empty_edit_422(client):
    assert client.post("/api/content/pend1/edit", json={"text": "  "}).status_code == 422


def test_edit_published_409(client, store):
    resp = client.post("/api/content/pub1/edit", json={"text": GOOD_TEXT + " x"})
    assert resp.status_code == 409
    assert store.get("pub1").text == GOOD_TEXT


def test_edit_approve_in_one_call(client, store):
    resp = client.post("/api/content/pend1/edit-approve", json={"text": GOOD_TEXT + " ok"})
    assert resp.status_code == 200
    row = store.get("pend1")
    assert row.status == APPROVED and row.text.endswith("ok")


def test_recheck_llm_replaces_flags(client, store):
    client.post("/api/content/pend1/recheck-llm")
    assert any(f["rule"] == "llm-tone" for f in store.get("pend1").flags)


# --- delete -----------------------------------------------------------------


def test_delete_pending(client, store):
    assert client.delete("/api/content/pend1").status_code == 204
    assert not store.has("pend1")


def test_delete_published_refused_409(client, store):
    assert client.delete("/api/content/pub1").status_code == 409
    assert store.has("pub1")


def test_delete_unknown_404(client):
    assert client.delete("/api/content/ghost").status_code == 404


# --- already-posted live edit/delete are stubbed (501) ----------------------


def test_edit_published_live_501(client):
    resp = client.post("/api/content/pub1/edit-published", json={"text": "x"})
    assert resp.status_code == 501


def test_delete_published_live_501(client):
    assert client.delete("/api/content/pub1/published").status_code == 501


# --- profile / personas -----------------------------------------------------


def test_profile_surfaces_engine_and_counts(client):
    body = client.get("/api/profile").json()
    assert body["engine"]["engine"]  # mockbot by default
    assert body["counts"][PENDING] == 1
    assert body["live_edit_available"] is False
