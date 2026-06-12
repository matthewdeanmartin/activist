"""Phase 3: consent gates (ordinary code), mock reply drafting, full run."""

import shutil
from pathlib import Path

import pytest

from activist import state
from activist.engine import MockBot
from activist.models import Mention
from activist.queue_io import read_feed
from activist.replies import ReplyRunConfig, consent_skip_reason, load_mentions, run_replies
from tests.conftest import make_opinion, make_persona

DATE = "2026-06-11"
HANDLE = "@lowwatt@example.invalid"


def make_mention(**overrides) -> Mention:
    defaults = dict(
        id="m-test",
        author="@solarfan@mastodon.social",
        text=f"{HANDLE} which heat pump should I get?",
        author_bio="Solar nerd.",
        author_is_bot=False,
        created="2026-06-11T14:00:00",
        hints={"asks": "heat-pump-top-pick"},
    )
    defaults.update(overrides)
    return Mention(**defaults)


# --- consent gates ------------------------------------------------------------


def test_gate_allows_a_plain_summons():
    assert consent_skip_reason(make_mention(), make_persona(), set()) is None


def test_gate_already_handled():
    reason = consent_skip_reason(make_mention(), make_persona(), {"m-test"})
    assert reason == "already handled"


def test_gate_requires_explicit_mention():
    mention = make_mention(text="someone should ask lowwatt about heat pumps")
    assert "summon" in consent_skip_reason(mention, make_persona(), set())


def test_gate_respects_nobot():
    mention = make_mention(author_bio="Privacy please. #NoBot")
    assert "#nobot" in consent_skip_reason(mention, make_persona(), set())


def test_gate_blocks_bot_authors():
    mention = make_mention(author_is_bot=True)
    assert "bot" in consent_skip_reason(mention, make_persona(), set())


# --- mock reply engine ----------------------------------------------------------


def reply(mention, opinions):
    return MockBot().reply(
        mention, make_persona(), opinions, knowledge="", recent_said=[], created="2026-06-11T09:00:00"
    )


def test_reply_answers_from_held_opinion():
    opinion = make_opinion()
    reaction = reply(make_mention(), {opinion.key: opinion})
    post = reaction.post
    assert post is not None
    assert post.text.startswith("@solarfan@mastodon.social")
    assert opinion.stance in post.text
    assert "🤖 bot post, human approved" in post.text
    assert post.reply_to_id == "m-test"
    assert post.reply_to_author == "@solarfan@mastodon.social"
    assert post.source_url == ""
    assert post.char_count <= 500


def test_hostile_mention_is_declined():
    reaction = reply(make_mention(hints={"hostile": "true"}), {})
    assert reaction.post is None
    assert "hostile" in reaction.diary_note


def test_no_engaged_opinion_stays_quiet():
    reaction = reply(make_mention(hints={}), {})
    assert reaction.post is None
    assert "stayed quiet" in reaction.diary_note


# --- full run against the fixture file -----------------------------------------


@pytest.fixture
def workspace(tmp_path, repo_root):
    shutil.copytree(repo_root / "persona", tmp_path / "persona")
    shutil.copyfile(
        repo_root / "tests" / "seed_opinions.toml", tmp_path / "persona" / "opinions.toml"
    )
    memory = tmp_path / "persona" / "memory"
    shutil.rmtree(memory, ignore_errors=True)
    memory.mkdir()
    shutil.copyfile(
        repo_root / "fixtures" / "mentions-sample.toml", tmp_path / "mentions.toml"
    )
    return tmp_path


def make_config(workspace, **overrides) -> ReplyRunConfig:
    defaults = dict(
        mentions_path=workspace / "mentions.toml",
        persona_dir=workspace / "persona",
        out_dir=workspace / "out",
        date=DATE,
        engine=MockBot(),
    )
    defaults.update(overrides)
    return ReplyRunConfig(**defaults)


def test_fixture_file_parses():
    mentions = load_mentions(
        Path(__file__).resolve().parents[1] / "fixtures" / "mentions-sample.toml"
    )
    assert len(mentions) == 7
    assert mentions[0].hints == {"asks": "heat-pump-top-pick"}
    assert mentions[3].author_is_bot is True


def test_full_reply_run(workspace):
    result = run_replies(make_config(workspace))

    # 7 mentions: 3 gated (nobot, not summoned, bot author), 4 reach the engine,
    # of which 1 hostile declined and 1 abstained -> 2 replies.
    assert result.mentions_total == 7
    assert result.mentions_eligible == 4
    assert len(result.posts) == 2

    data = read_feed(result.replies_toml)
    assert data["run"]["kind"] == "replies"
    assert data["run"]["posts"] == 2
    by_author = {p["reply_to_author"]: p for p in data["post"]}
    assert set(by_author) == {"@solarfan@mastodon.social", "@cargodad@sfba.social"}

    heat = by_author["@solarfan@mastodon.social"]
    assert "heat pump" in heat["text"].lower()
    assert heat["reply_to_text"].startswith(HANDLE)
    assert "🤖 bot post, human approved" in heat["text"]

    # replies are paced like posts: 4/hour -> 15-minute slots
    assert [p["created"] for p in data["post"]] == [
        "2026-06-11T09:00:00",
        "2026-06-11T09:15:00",
    ]

    # memory: every non-skipped mention is recorded; gated+declined+replied
    handled = state.load_handled_mentions(workspace / "persona" / "memory")
    assert len(handled) == 7

    html_text = result.replies_html.read_text(encoding="utf-8")
    assert "replying to" in html_text
    assert "@solarfan@mastodon.social" in html_text


def test_second_reply_run_is_deduped(workspace):
    run_replies(make_config(workspace))
    second = run_replies(make_config(workspace, out_dir=workspace / "out2"))
    assert second.mentions_eligible == 0
    assert second.posts == []


def test_instance_policy_tightens_reply_pacing(workspace):
    result = run_replies(
        make_config(
            workspace,
            instance_policies={"infosec.exchange": "limited to one post per hour"},
        )
    )
    data = read_feed(result.replies_toml)
    assert data["run"]["posts_per_hour"] == 1
    assert [p["created"] for p in data["post"]] == [
        "2026-06-11T09:00:00",
        "2026-06-11T10:00:00",
    ]


def test_dry_state_writes_no_memory(workspace):
    run_replies(make_config(workspace, dry_state=True))
    assert state.load_handled_mentions(workspace / "persona" / "memory") == set()


def test_moderating_replies_raises_no_reply_exempt_flags(workspace):
    from activist.moderation import ModerationContext, moderate_feed

    result = run_replies(make_config(workspace))
    persona = state.load_persona(workspace / "persona" / "persona.toml")
    mod = moderate_feed(
        result.replies_toml,
        ModerationContext(disclosure=persona.disclosure, app_policy="(policy)"),
    )
    # replies @-mention their author and carry no source link; neither is a flag
    assert mod.errors == 0
    assert mod.flags == []
