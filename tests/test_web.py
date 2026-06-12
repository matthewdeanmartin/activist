"""Read-only dashboard (admin UI Phase U1) against a seeded temp store."""

from __future__ import annotations

from pathlib import Path

import pytest

from activist.config import AppConfig
from activist.store import APPROVED, PENDING, REJECTED, Store
from activist.web import create_app
from tests.test_store import make_row


@pytest.fixture
def store(tmp_path: Path) -> Store:
    s = Store(tmp_path / "queue.db")
    s.add_pending(
        make_row(
            id="pending1",
            text='I think <script>alert("xss")</script> heat pumps win. https://example.com/hp',
            source_title="<b>Sneaky</b> title",
            opinion_change={"key": "heat-pump-top-pick", "old_stance": "XYZ best",
                            "new_stance": "ABC best", "trigger_item": "t", "reason": "new COP data"},
        )
    )
    s.add_pending(
        make_row(
            id="reply1",
            kind="reply",
            flags=[{"severity": "warn", "policy": "app", "rule": "unverified-link",
                    "detail": "model-supplied URL"}],
            reply_to_author="@fan@mas.to",
            reply_to_text="what about cold climates?",
            in_reply_to_status_id="109501",
        )
    )
    s.add_pending(make_row(id="done1"))
    s.transition("done1", PENDING, APPROVED, "human")
    s.transition("done1", APPROVED, "publishing", "poster")
    s.transition("done1", "publishing", "published", "poster")
    s.add_pending(make_row(id="nope1"))
    s.transition("nope1", PENDING, REJECTED, "human", "off-voice")
    s.log_event("-", "fetcher", "fetch", "2 new, 5 seen, 0 failed")
    return s


@pytest.fixture
def client(store: Store, tmp_path: Path):
    app = create_app(AppConfig(db_path=tmp_path / "queue.db"), store=store)
    app.config["TESTING"] = True
    return app.test_client()


def test_queue_defaults_to_pending(client):
    html = client.get("/").get_data(as_text=True)
    assert "pending1" in html and "reply1" in html
    assert "done1" not in html and "nope1" not in html


def test_status_filter_and_counts(client):
    html = client.get("/?status=published").get_data(as_text=True)
    assert "done1" in html and "pending1" not in html
    # tab badges come from store.counts()
    assert ">2</span>" in html  # pending count
    assert "last fetch" in html and "2 new, 5 seen, 0 failed" in html


def test_unknown_status_404(client):
    assert client.get("/?status=bogus").status_code == 404


def test_detail_renders_strips_and_history(client):
    html = client.get("/content/pending1").get_data(as_text=True)
    assert "changed my mind on" in html and "ABC best" in html and "new COP data" in html
    assert "created" in html  # event log row
    # text is escaped, never executed
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert "<b>Sneaky</b>" not in html
    # URLs in post text get linkified
    assert 'href="https://example.com/hp"' in html


def test_detail_reply_strip_and_flags(client):
    html = client.get("/content/reply1").get_data(as_text=True)
    assert "replying to" in html and "@fan@mas.to" in html
    assert "unverified-link" in html and "model-supplied URL" in html


def test_detail_404(client):
    assert client.get("/content/missing").status_code == 404


def test_rejected_shows_reason_via_event(client):
    html = client.get("/content/nope1").get_data(as_text=True)
    assert "reject" in html and "off-voice" in html


def test_published_archive_route(client):
    html = client.get("/published").get_data(as_text=True)
    assert "done1" in html
