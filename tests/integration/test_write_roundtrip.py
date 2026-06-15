"""Read-write round-trips of activist's Mastodon client against the mock server.

This is the safe stand-in for the live tests the project has deliberately
avoided: every write here hits a local ``mastodon_mock`` instance, never a real
account. Assertions check *shape and stateful behaviour* (post -> read-back ->
delete -> 404), so they would hold against real Mastodon too.
"""

from __future__ import annotations

import httpx
import pytest

from activist.mastodon_client import (
    MastodonReader,
    MastodonWriter,
    notification_to_mention,
)


def test_post_status_then_read_it_back(bot_writer: MastodonWriter, bot_reader: MastodonReader) -> None:
    text = "heat pumps move heat, they don't make it — 3-4x more efficient than resistance heat."
    result = bot_writer.post_status(text, idempotency_key="content-roundtrip-1", visibility="unlisted")

    assert result.status_id
    assert result.created_at

    fetched = bot_reader.get_status(result.status_id)
    assert str(fetched["id"]) == result.status_id
    assert text in fetched["content"]
    assert fetched["visibility"] == "unlisted"


def test_idempotency_key_dedupes_a_repeated_post(bot_writer: MastodonWriter) -> None:
    """The single most important guarantee in the poster: same key -> same status.

    A crash between POST and the local DB write means the poster retries with the
    same content id as the Idempotency-Key. Mastodon (and the mock) must return
    the *existing* status rather than creating a duplicate.
    """
    key = "content-idempotent-7"
    first = bot_writer.post_status("post once, retry safely", idempotency_key=key)
    second = bot_writer.post_status("post once, retry safely", idempotency_key=key)

    assert first.status_id == second.status_id


def test_distinct_keys_create_distinct_statuses(bot_writer: MastodonWriter) -> None:
    a = bot_writer.post_status("first distinct", idempotency_key="content-distinct-a")
    b = bot_writer.post_status("second distinct", idempotency_key="content-distinct-b")
    assert a.status_id != b.status_id


def test_reply_threads_onto_an_inbound_mention(
    bot_writer: MastodonWriter,
    bot_reader: MastodonReader,
    human_writer: MastodonWriter,
) -> None:
    """End-to-end of the reply path the bot exists for.

    The human posts a public mention; the bot maps the notification to a
    Mention, then publishes a reply threaded onto that status. The reply must
    carry ``in_reply_to_id`` and match the mention's visibility.
    """
    mention_status = human_writer.post_status(
        "@activistbot is the HP-9 really the best cold-climate unit?",
        idempotency_key="human-mention-1",
        visibility="public",
    )

    # The bot sees it as a notification → Mention (the real ingest mapping).
    notifs = bot_reader.notifications(types=["mention"], limit=10)
    matching = [n for n in notifs if str((n.get("status") or {}).get("id")) == mention_status.status_id]
    assert matching, "bot should have a mention notification for the human's post"
    mention = notification_to_mention(matching[0])
    assert mention.status_id == mention_status.status_id
    assert mention.visibility == "public"

    reply = bot_writer.post_status(
        "Per NEEP field data it leads at -15C, yes — caveats on install quality.",
        idempotency_key="content-reply-1",
        in_reply_to_id=mention.status_id,
        visibility=mention.visibility,
    )

    fetched = bot_reader.get_status(reply.status_id)
    assert str(fetched["in_reply_to_id"]) == mention_status.status_id
    assert fetched["visibility"] == "public"


def test_empty_status_is_rejected_with_422(bot_writer: MastodonWriter) -> None:
    """A real instance 422s an empty post; the bot must see the failure.

    Exercises the validation gap found (and fixed) in mastodon_mock while
    proving activist out — without it, an accidental empty draft would get a
    phantom success and a blank toot on the timeline.
    """
    with pytest.raises(httpx.HTTPStatusError) as exc:
        bot_writer.post_status("", idempotency_key="content-empty-1")
    assert exc.value.response.status_code == 422


def test_over_length_status_is_rejected_with_422(bot_writer: MastodonWriter) -> None:
    with pytest.raises(httpx.HTTPStatusError) as exc:
        bot_writer.post_status("x" * 501, idempotency_key="content-toolong-1")
    assert exc.value.response.status_code == 422


def test_delete_status_then_it_404s(bot_writer: MastodonWriter, bot_reader: MastodonReader) -> None:
    """The "oh no" tool: a published post can be retracted and is then gone."""
    result = bot_writer.post_status("this one gets retracted", idempotency_key="content-delete-1")
    bot_reader.get_status(result.status_id)  # exists now

    bot_writer.delete_status(result.status_id)

    with pytest.raises(httpx.HTTPStatusError) as exc:
        bot_reader.get_status(result.status_id)
    assert exc.value.response.status_code == 404


def test_posted_status_appears_in_account_timeline(
    bot_writer: MastodonWriter, mock_server_url: str
) -> None:
    """Stateful proof through a fresh read client: the post shows up on the wire."""
    marker = "timeline-visibility-marker-9f3c"
    result = bot_writer.post_status(marker, idempotency_key="content-timeline-1")

    # Read the bot's own account id, then its statuses, with a plain client.
    with httpx.Client(
        base_url=mock_server_url,
        headers={"Authorization": "Bearer bot_token"},
        timeout=httpx.Timeout(10.0),
    ) as client:
        whoami = client.get("/api/v1/accounts/verify_credentials")
        whoami.raise_for_status()
        account_id = whoami.json()["id"]

        statuses = client.get(f"/api/v1/accounts/{account_id}/statuses", params={"limit": 40})
        statuses.raise_for_status()
        ids = {str(s["id"]) for s in statuses.json()}

    assert result.status_id in ids
