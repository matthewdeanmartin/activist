"""Moderation pass: deterministic content rules and the feed round-trip.

Rate limiting is intentionally absent: it lives in activist.ratelimit and
is enforced by the scheduler, not judged by the moderator.
"""

from pathlib import Path

import pytest

from activist.moderation import ModerationContext, MockModerator, moderate_feed
from activist.moderation.policies import load_app_policy, load_instance_policy
from activist.queue_io import read_feed, write_feed
from tests.test_render import RUN_META, make_post

REPO_ROOT = Path(__file__).resolve().parents[1]
DISCLOSURE = "🤖 bot post, human approved"

GOOD_TEXT = f"Induction wins again. https://example.com/article\n\n{DISCLOSURE}"


def ctx(**overrides) -> ModerationContext:
    defaults = dict(disclosure=DISCLOSURE, app_policy="(policy text)", instance_policies={})
    defaults.update(overrides)
    return ModerationContext(**defaults)


def review(text: str, context: ModerationContext | None = None, **post_fields) -> list:
    post = {"text": text, "char_count": len(text), **post_fields}
    return MockModerator().review(post, context or ctx())


def rules(flags) -> set[str]:
    return {f.rule for f in flags}


# --- deterministic rules ------------------------------------------------------


def test_clean_post_has_no_flags():
    assert review(GOOD_TEXT) == []


def test_char_limit():
    flags = review("x" * 480 + " https://e.com\n\n" + DISCLOSURE)
    assert "char-limit" in rules(flags)
    assert all(f.severity == "error" for f in flags if f.rule == "char-limit")


def test_missing_disclosure():
    assert "missing-disclosure" in rules(review("No footer here https://e.com/a"))


def test_missing_source_link():
    assert "missing-source-link" in rules(review(f"No link at all.\n\n{DISCLOSURE}"))


def test_popular_hashtag_is_error_uncommon_is_warn():
    flags = review(f"Read this #news #LowwattBeat https://e.com/a\n\n{DISCLOSURE}")
    by_rule = {f.rule: f for f in flags}
    assert by_rule["popular-hashtag"].severity == "error"
    assert "#news" in by_rule["popular-hashtag"].detail
    assert by_rule["hashtag"].severity == "warn"
    assert "#LowwattBeat" in by_rule["hashtag"].detail


def test_url_fragment_is_not_a_hashtag():
    flags = review(f"See https://e.com/page#section\n\n{DISCLOSURE}")
    assert "hashtag" not in rules(flags) and "popular-hashtag" not in rules(flags)


def test_cold_mention():
    flags = review(f"Hey @someone look at this https://e.com/a\n\n{DISCLOSURE}")
    assert "cold-mention" in rules(flags)


def test_human_experience_claims():
    flags = review(f"I installed one in my garage last week. https://e.com/a\n\n{DISCLOSURE}")
    assert "human-claim" in rules(flags)


def test_opinion_phrases_are_not_human_claims():
    # "changed my mind", "my top pick", "my confidence" are owned opinions, not experiences
    text = f"XYZ used to be my top pick but this changed my mind. https://e.com/a\n\n{DISCLOSURE}"
    assert "human-claim" not in rules(review(text))


def test_no_rate_limit_rules_exist():
    # rate limiting is the scheduler's job (activist.ratelimit), never the moderator's
    context = ctx(instance_policies={"strict.example": "bots are limited to one post per hour."})
    for position in range(20):
        assert review(GOOD_TEXT, context=context) == [], f"flagged at position {position}"


def test_replies_may_mention_their_author():
    text = f"@asker@mas.to Good question — I think induction wins.\n\n{DISCLOSURE}"
    flags = review(text, reply_to_id="m-001")
    assert "cold-mention" not in rules(flags)
    assert "missing-source-link" not in rules(flags)  # replies don't need a source
    assert flags == []


def test_reply_with_model_invented_link_is_flagged():
    text = f"@asker@mas.to See https://example.com/heat-pump-testing for data.\n\n{DISCLOSURE}"
    flags = review(text, reply_to_id="m-001")
    assert rules(flags) == {"unverified-link"}
    assert "https://example.com/heat-pump-testing" in flags[0].detail
    assert flags[0].severity == "warn"


def test_reply_exemptions_do_not_apply_to_top_level_posts():
    text = f"@someone@mas.to look at this\n\n{DISCLOSURE}"
    flags = review(text)  # no reply_to_id
    assert "cold-mention" in rules(flags)
    assert "missing-source-link" in rules(flags)


# --- policy loading -----------------------------------------------------------


def test_missing_instance_policy_raises():
    with pytest.raises(FileNotFoundError, match="no-such-instance"):
        load_instance_policy(REPO_ROOT / "policies", "no-such-instance")


def test_app_policy_loads():
    assert "Human Oversight" in load_app_policy()


# --- feed round-trip ----------------------------------------------------------


def make_feed(tmp_path, texts):
    posts = []
    for i, text in enumerate(texts):
        posts.append(make_post(id=f"post{i:08d}", text=text, char_count=len(text)))
    feed = tmp_path / "feed.toml"
    write_feed(feed, {**RUN_META, "posts": len(posts)}, posts)
    return feed


def test_moderate_feed_writes_flags_and_renders(tmp_path):
    feed = make_feed(tmp_path, [GOOD_TEXT, "no link no footer"])
    result = moderate_feed(feed, ctx())

    assert result.posts == 2
    assert result.flagged_posts == 1
    assert result.errors == 2  # missing-disclosure + missing-source-link
    assert result.warns == 0

    data = read_feed(feed)
    assert "flags" not in data["post"][0]
    flagged = data["post"][1]["flags"]
    assert {f["rule"] for f in flagged} == {"missing-disclosure", "missing-source-link"}
    assert data["run"]["moderation"]["engine"] == "mockmod"
    assert data["run"]["moderation"]["errors"] == 2

    html_text = result.feed_html.read_text(encoding="utf-8")
    assert "Moderation flags" in html_text
    assert "missing-disclosure" in html_text
    assert "moderated by mockmod" in html_text


def test_moderation_is_idempotent(tmp_path):
    feed = make_feed(tmp_path, ["no link no footer"])
    first = moderate_feed(feed, ctx())
    second = moderate_feed(feed, ctx())
    assert first.errors == second.errors
    data = read_feed(feed)
    assert len(data["post"][0]["flags"]) == second.errors  # not duplicated


def test_moderation_never_drops_posts(tmp_path):
    feed = make_feed(tmp_path, ["bad " * 200, "no link no footer", GOOD_TEXT])
    moderate_feed(feed, ctx())
    assert len(read_feed(feed)["post"]) == 3
