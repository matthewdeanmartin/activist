"""Credentials from the MASTODON_ID_* env pattern and the read-only client."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

from activist.mastodon_client import (
    CredentialsError,
    MastodonCredentials,
    MastodonReader,
    notification_to_mention,
)


def set_identity(monkeypatch, name: str = "TECH") -> None:
    monkeypatch.setenv(f"MASTODON_ID_{name}_BASE_URL", "https://mas.example/")
    monkeypatch.setenv(f"MASTODON_ID_{name}_CLIENT_ID", "cid")
    monkeypatch.setenv(f"MASTODON_ID_{name}_CLIENT_SECRET", "csec")
    monkeypatch.setenv(f"MASTODON_ID_{name}_ACCESS_TOKEN", "tok")


def test_from_env_happy_path(monkeypatch):
    set_identity(monkeypatch)
    creds = MastodonCredentials.from_env("tech")  # case-insensitive
    assert creds.identity == "TECH"
    assert creds.base_url == "https://mas.example"  # trailing slash stripped
    assert creds.access_token == "tok"


def test_from_env_lists_every_missing_var(monkeypatch):
    monkeypatch.delenv("MASTODON_ID_GHOST_BASE_URL", raising=False)
    with pytest.raises(CredentialsError) as exc:
        MastodonCredentials.from_env("GHOST")
    message = str(exc.value)
    assert "MASTODON_ID_GHOST_BASE_URL" in message
    assert "MASTODON_ID_GHOST_ACCESS_TOKEN" in message


def reader_with(monkeypatch, handler) -> MastodonReader:
    set_identity(monkeypatch)
    creds = MastodonCredentials.from_env("TECH")
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=creds.base_url,
        headers={"Authorization": f"Bearer {creds.access_token}"},
    )
    return MastodonReader(creds, client=client)


def test_verify_credentials_ok(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/accounts/verify_credentials"
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(200, json={"acct": "lowwatt", "bot": True})

    reader = reader_with(monkeypatch, handler)
    account = reader.verify_credentials()
    assert account["acct"] == "lowwatt"
    reader.close()


def test_verify_credentials_bad_token_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "The access token is invalid"})

    reader = reader_with(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        reader.verify_credentials()
    reader.close()


def test_get_status(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/statuses/109501"
        return httpx.Response(200, json={"id": "109501", "visibility": "public"})

    reader = reader_with(monkeypatch, handler)
    status = reader.get_status("109501")
    assert status["visibility"] == "public"
    reader.close()


def test_get_account(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/accounts/1007"
        return httpx.Response(200, json={"id": "1007", "acct": "solarfan@mastodon.social"})

    reader = reader_with(monkeypatch, handler)
    account = reader.get_account("1007")
    assert account["acct"] == "solarfan@mastodon.social"
    reader.close()


# --- notifications + checkpointing -------------------------------------------


def test_notifications_passes_type_and_since_id(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/notifications"
        captured["params"] = dict(request.url.params.multi_items())
        # multi_items keeps both types[] occurrences distinct if repeated
        captured["raw"] = str(request.url)
        return httpx.Response(200, json=[{"id": "440000004", "type": "mention"}])

    reader = reader_with(monkeypatch, handler)
    notes = reader.notifications(types=["mention"], since_id="440000000", limit=10)
    reader.close()
    assert notes[0]["id"] == "440000004"
    assert "types%5B%5D=mention" in captured["raw"]
    assert captured["params"]["since_id"] == "440000000"
    assert captured["params"]["limit"] == "10"


# --- notification -> Mention mapping -----------------------------------------


def make_notification(**status_over) -> dict:
    status = {
        "id": "550000001",
        "created_at": "2026-06-12T14:10:00.000Z",
        "visibility": "private",
        "content": (
            '<p><span class="h-card"><a href="https://x/@lowwatt" class="mention">'
            "@<span>lowwatt</span></a></span> which heat pump should I get?</p>"
        ),
    }
    status.update(status_over)
    return {
        "id": "440000001",
        "type": "mention",
        "created_at": "2026-06-12T14:10:00.000Z",
        "account": {
            "id": "1007",
            "acct": "solarfan@mastodon.social",
            "bot": False,
            "note": "<p>Solar nerd. <a>#NoBot</a></p>",
        },
        "status": status,
    }


def test_mapping_carries_status_id_and_visibility_separately():
    mention = notification_to_mention(make_notification())
    # the dedup/checkpoint key is the NOTIFICATION id, not the status id
    assert mention.id == "440000001"
    assert mention.status_id == "550000001"
    assert mention.visibility == "private"  # a DM stays a DM


def test_mapping_strips_html_from_text_and_bio():
    mention = notification_to_mention(make_notification())
    assert "<" not in mention.text
    assert "@lowwatt which heat pump should I get?" in mention.text
    # bio is stripped so the #nobot gate sees plain text
    assert "#NoBot" in mention.author_bio
    assert "<" not in mention.author_bio


def test_mapping_normalizes_author_handle_and_bot_flag():
    note = make_notification()
    note["account"]["bot"] = True
    mention = notification_to_mention(note)
    assert mention.author == "@solarfan@mastodon.social"
    assert mention.author_is_bot is True


def test_mapping_tolerates_missing_status():
    # boosts/follows shouldn't be passed here, but never crash if they are
    mention = notification_to_mention({"id": "9", "account": {"acct": "a@b"}})
    assert mention.id == "9"
    assert mention.status_id == ""
    assert mention.visibility == ""


# --- rate-limit backoff -------------------------------------------------------


def test_notifications_sleeps_when_budget_near_zero(monkeypatch):
    reset = (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=30)).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[],
            headers={"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": reset},
        )

    slept = {}
    monkeypatch.setattr("activist.mastodon_client.time.sleep", lambda s: slept.setdefault("s", s))
    reader = reader_with(monkeypatch, handler)
    reader.notifications(types=["mention"])
    reader.close()
    assert 0 < slept["s"] <= 30


def test_notifications_does_not_sleep_with_budget(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=[], headers={"X-RateLimit-Remaining": "50", "X-RateLimit-Reset": "x"}
        )

    slept = {}
    monkeypatch.setattr("activist.mastodon_client.time.sleep", lambda s: slept.setdefault("s", s))
    reader = reader_with(monkeypatch, handler)
    reader.notifications(types=["mention"])
    reader.close()
    assert slept == {}
