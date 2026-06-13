"""Admin UI Phase U2: approve / reject / edit, CAS races, edit re-moderation."""

from __future__ import annotations

from pathlib import Path

import pytest

from activist.config import AppConfig
from activist.moderation import ModerationContext
from activist.models import Flag
from activist.store import APPROVED, FAILED, PENDING, PUBLISHED, REJECTED, Store
from activist.web import create_app
from tests.test_store import make_row

DISCLOSURE = "🤖 bot post, human approved"
GOOD_TEXT = f"Heat pumps still win. https://example.com/x\n{DISCLOSURE}"


class FakeLlmModerator:
    name = "fake-llm"

    def review(self, post, ctx):
        return [Flag("warn", "app", "llm-tone", f"reviewed {len(post['text'])} chars")]


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
    s.add_pending(
        make_row(id="reply1", kind="reply", text=f"answer\n{DISCLOSURE}",
                 in_reply_to_status_id="109501", reply_to_author="@fan@mas.to")
    )
    return s


@pytest.fixture
def client(store: Store, tmp_path: Path):
    ctx = ModerationContext(disclosure=DISCLOSURE, app_policy="")
    app = create_app(
        AppConfig(db_path=tmp_path / "queue.db"),
        store=store,
        mod_ctx=ctx,
        llm_moderator=FakeLlmModerator(),
    )
    app.config["TESTING"] = True
    return app.test_client()


# --- status transitions -------------------------------------------------------


def test_approve(client, store):
    resp = client.post("/content/pend1/act/approve")
    assert resp.status_code == 302
    assert store.get("pend1").status == APPROVED


def test_reject_records_reason(client, store):
    client.post("/content/pend1/act/reject", data={"reason": "off-voice"})
    row = store.get("pend1")
    assert row.status == REJECTED and row.rejected_reason == "off-voice"
    assert any(e.action == "reject" and e.detail == "off-voice" for e in store.events("pend1"))


def test_unapprove(client, store):
    client.post("/content/appr1/act/unapprove")
    assert store.get("appr1").status == PENDING


def test_retry_failed(client, store):
    client.post("/content/fail1/act/retry")
    assert store.get("fail1").status == APPROVED


def test_lost_race_flashes_and_changes_nothing(client, store):
    store.transition("pend1", PENDING, REJECTED, "human")  # someone else won
    html = client.post(
        "/content/pend1/act/approve", follow_redirects=True
    ).get_data(as_text=True)
    assert "another process got there first" in html
    assert store.get("pend1").status == REJECTED


def test_unknown_action_and_id_404(client):
    assert client.post("/content/pend1/act/promote").status_code == 404
    assert client.post("/content/ghost/act/approve").status_code == 404


def test_next_param_redirects_to_list(client):
    resp = client.post("/content/pend1/act/approve", data={"next": "/?status=pending_review"})
    assert resp.headers["Location"] == "/?status=pending_review"


# --- edits ---------------------------------------------------------------------


def test_clean_edit_preserves_original_once(client, store):
    client.post("/content/pend1/edit", data={"text": GOOD_TEXT + " Updated."})
    row = store.get("pend1")
    assert row.text.endswith("Updated.")
    assert row.original_text == GOOD_TEXT
    assert row.flags == []  # footer + link intact → clean

    client.post("/content/pend1/edit", data={"text": GOOD_TEXT + " Again."})
    assert store.get("pend1").original_text == GOOD_TEXT  # still the first original


def test_edit_introducing_violations_gets_reflagged(client, store):
    bad = "x" * 501  # no footer, no link, over limit
    client.post("/content/pend1/edit", data={"text": bad})
    rules = {f["rule"] for f in store.get("pend1").flags}
    assert {"char-limit", "missing-disclosure", "missing-source-link"} <= rules


def test_edit_reply_with_new_link_flags_unverified(client, store):
    client.post(
        "/content/reply1/edit",
        data={"text": f"see https://made.up/proof\n{DISCLOSURE}"},
    )
    flags = store.get("reply1").flags
    assert any(f["rule"] == "unverified-link" for f in flags)
    # replies are exempt from missing-source-link
    assert not any(f["rule"] == "missing-source-link" for f in flags)


def test_edit_approved_row_is_allowed(client, store):
    client.post("/content/appr1/edit", data={"text": GOOD_TEXT + " tweak"})
    row = store.get("appr1")
    assert row.status == APPROVED and row.text.endswith("tweak")


def test_edit_published_row_refused(client, store):
    html = client.post(
        "/content/pub1/edit", data={"text": GOOD_TEXT + " sneaky"}, follow_redirects=True
    ).get_data(as_text=True)
    assert "Not editable" in html
    assert store.get("pub1").text == GOOD_TEXT


def test_empty_edit_refused(client, store):
    client.post("/content/pend1/edit", data={"text": "   "})
    assert store.get("pend1").text == GOOD_TEXT


def test_llm_recheck_replaces_flags_without_editing_text(client, store):
    before = store.get("pend1").text
    client.post("/content/pend1/recheck-llm")
    row = store.get("pend1")
    assert row.text == before
    assert row.original_text is None
    rules = {f["rule"] for f in row.flags}
    assert "llm-tone" in rules
    assert any(e.action == "recheck" for e in store.events("pend1"))


def test_llm_recheck_published_row_refused(client, store):
    before_flags = store.get("pub1").flags
    html = client.post("/content/pub1/recheck-llm", follow_redirects=True).get_data(as_text=True)
    assert "Not re-checkable" in html
    assert store.get("pub1").flags == before_flags


# --- rendering ----------------------------------------------------------------


def test_detail_shows_action_buttons_by_status(client):
    pend = client.get("/content/pend1").get_data(as_text=True)
    assert "approve" in pend and "reject" in pend and "save edit" in pend
    assert "re-check with LLM" in pend
    appr = client.get("/content/appr1").get_data(as_text=True)
    assert "un-approve" in appr and "save edit" in appr
    pub = client.get("/content/pub1").get_data(as_text=True)
    assert "save edit" not in pub and "un-approve" not in pub
    fail = client.get("/content/fail1").get_data(as_text=True)
    assert "retry" in fail


def test_list_quick_actions_only_on_pending(client):
    pending = client.get("/?status=pending_review").get_data(as_text=True)
    assert "act/approve" in pending
    published = client.get("/?status=published").get_data(as_text=True)
    assert "act/approve" not in published
