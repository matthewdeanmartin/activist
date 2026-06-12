import dataclasses

from activist.engine.mockbot import MockBot
from activist.models import SaidEntry
from tests.conftest import make_item, make_opinion, make_persona

CREATED = "2026-06-11T09:00:00"


def react(item, opinions, recent_said=None):
    bot = MockBot()
    return bot.react(
        item, make_persona(), opinions, knowledge="", recent_said=recent_said or [], created=CREATED
    )


def challenge_item(**hint_overrides):
    hints = {
        "challenges": "heat-pump-top-pick",
        "claim": "ABC's new GW-200 just posted a COP of 3.4 at -20C",
        "subject": "ABC's GW-200",
        "new_stance": "ABC's GW-200 is the best cold-climate heat pump",
    }
    hints.update(hint_overrides)
    return make_item(hints=hints)


def test_challenge_below_threshold_changes_mind():
    opinion = make_opinion(strength=0.8)
    reaction = react(challenge_item(), {opinion.key: opinion})

    assert reaction.post is not None
    assert "used to be my top pick" in reaction.post.text
    assert "changed my mind" in reaction.post.text
    assert reaction.post.source_url in reaction.post.text
    assert "🤖 bot post, human approved" in reaction.post.text
    assert reaction.post.opinion_keys == ["heat-pump-top-pick"]
    assert reaction.post.char_count == len(reaction.post.text) <= 500

    assert len(reaction.opinion_changes) == 1
    change = reaction.opinion_changes[0]
    assert change.key == "heat-pump-top-pick"
    assert change.old_stance == opinion.stance
    assert change.new_stance == "ABC's GW-200 is the best cold-climate heat pump"
    assert change.trigger_item == "abc123def456"  # the NewsItem id
    assert reaction.post.opinion_change == change


def test_challenge_at_threshold_pushes_back():
    opinion = make_opinion(strength=0.9)
    reaction = react(challenge_item(), {opinion.key: opinion})

    assert reaction.post is not None
    assert "I'm not convinced" in reaction.post.text
    assert reaction.opinion_changes == []
    assert reaction.post.opinion_change is None
    assert reaction.pushbacks == [
        {"key": "heat-pump-top-pick", "reason": "ABC's new GW-200 just posted a COP of 3.4 at -20C"}
    ]


def test_support_reinforces():
    opinion = make_opinion(strength=0.8)
    item = make_item(hints={"supports": "heat-pump-top-pick", "claim": "installs are up 40%"})
    reaction = react(item, {opinion.key: opinion})

    assert reaction.post is not None
    assert "This is why I keep saying" in reaction.post.text
    assert reaction.reinforcements == ["heat-pump-top-pick"]
    assert reaction.opinion_changes == []


def test_support_with_prior_said_gets_continuity_callback():
    opinion = make_opinion(strength=0.8)
    item = make_item(hints={"supports": "heat-pump-top-pick", "claim": "installs are up 40%"})
    prior = SaidEntry(
        date="2026-06-01",
        post_id="aaa",
        topic="heat pumps",
        opinion_keys=["heat-pump-top-pick"],
        summary="reaffirmed on heat pumps: XYZ is top pick",
    )
    reaction = react(item, {opinion.key: opinion}, recent_said=[prior])

    assert reaction.post is not None
    assert 'Last time I said "reaffirmed on heat pumps: XYZ is top pick"' in reaction.post.text


def test_no_hints_abstains_with_diary_note():
    opinion = make_opinion()
    reaction = react(make_item(hints={}), {opinion.key: opinion})
    assert reaction.post is None
    assert "nothing to add" in reaction.diary_note


def test_hint_for_unknown_opinion_abstains():
    reaction = react(challenge_item(challenges="no-such-key"), {})
    assert reaction.post is None
    assert "unknown opinion" in reaction.diary_note


def test_determinism():
    opinion = make_opinion(strength=0.8)
    first = react(challenge_item(), {opinion.key: dataclasses.replace(opinion)})
    second = react(challenge_item(), {opinion.key: dataclasses.replace(opinion)})
    assert first == second
