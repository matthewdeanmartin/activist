"""Full pipeline run against the repo's seed persona and fixtures, in a tmp dir."""

import shutil

import pytest

from activist import state
from activist.engine import MockBot
from activist.pipeline import RunConfig, run
from activist.queue_io import read_feed

DATE = "2026-06-11"


@pytest.fixture
def workspace(tmp_path, repo_root):
    """Repo persona/fixtures, but reset to the pristine seed.

    The live persona/ mutates with every real run (opinions change, memory
    fills with seen items), so tests pin opinions to tests/seed_opinions.toml
    and start with empty memory.
    """
    shutil.copytree(repo_root / "persona", tmp_path / "persona")
    shutil.copytree(repo_root / "fixtures", tmp_path / "fixtures")
    shutil.copyfile(
        repo_root / "tests" / "seed_opinions.toml", tmp_path / "persona" / "opinions.toml"
    )
    memory = tmp_path / "persona" / "memory"
    shutil.rmtree(memory, ignore_errors=True)
    memory.mkdir()
    return tmp_path


def make_config(workspace, **overrides) -> RunConfig:
    defaults = dict(
        fixtures_dir=workspace / "fixtures" / "feeds",
        persona_dir=workspace / "persona",
        out_dir=workspace / "out",
        date=DATE,
        engine=MockBot(),
    )
    defaults.update(overrides)
    return RunConfig(**defaults)


def test_full_run(workspace):
    result = run(make_config(workspace))

    # The seed fixtures: 8 items, 7 on the beat, 5 survive pacing/abstention.
    assert result.items_ingested == 8
    assert result.items_relevant == 7
    assert len(result.posts) == 5

    data = read_feed(result.feed_toml)
    assert data["run"]["posts"] == 5

    # Exactly one changed-my-mind post, and it's the heat pump flip.
    changed = [p for p in data["post"] if "opinion_change" in p]
    assert len(changed) == 1
    assert changed[0]["opinion_change"]["key"] == "heat-pump-top-pick"
    assert "GW-200" in changed[0]["opinion_change"]["new_stance"]
    assert "used to be my top pick" in changed[0]["text"]

    # One pushback post (ebike challenge against strength 0.9).
    assert sum("I'm not convinced" in p["text"] for p in data["post"]) == 1

    # Every post carries the disclosure footer, its source URL, and fits.
    for post in data["post"]:
        assert "🤖 bot post, human approved" in post["text"]
        assert post["source_url"] in post["text"]
        assert post["char_count"] <= 500

    # State was applied.
    opinions = state.load_opinions(workspace / "persona" / "opinions.toml")
    assert "GW-200" in opinions["heat-pump-top-pick"].stance
    assert opinions["heat-pump-top-pick"].since == DATE
    assert opinions["heat-pump-top-pick"].history[-1]["date"] == DATE
    assert opinions["used-ev-value"].strength == 0.65  # 0.6 + 0.05
    assert opinions["induction-stove"].strength == 0.75
    assert opinions["beef-biggest-lever"].strength == 0.75
    # Pushback recorded in history without a stance change.
    assert opinions["ebike-vs-car"].stance.startswith("an e-bike replaces")
    assert "pushed back" in opinions["ebike-vs-car"].history[-1]["trigger"]

    memory = workspace / "persona" / "memory"
    assert len(state.load_seen_ids(memory)) == 8
    assert len(state.load_said(memory, n=10)) == 5
    diary = (memory / "diary.md").read_text(encoding="utf-8")
    assert "Paced out" in diary  # second heat-pump item held (one post per key)
    assert "nothing to add" in diary  # transit item abstained

    html_text = result.feed_html.read_text(encoding="utf-8")
    assert "changed my mind" in html_text
    assert "Lowwatt" in html_text


def test_second_run_is_deduped(workspace):
    run(make_config(workspace))
    second = run(make_config(workspace, out_dir=workspace / "out2"))
    assert second.items_ingested == 8  # parsed again...
    assert second.items_relevant == 0  # ...but everything already seen
    assert second.posts == []
    html_text = second.feed_html.read_text(encoding="utf-8")
    assert "No posts this run" in html_text


def test_dry_state_leaves_persona_untouched(workspace):
    before_opinions = (workspace / "persona" / "opinions.toml").read_text(encoding="utf-8")
    result = run(make_config(workspace, dry_state=True))
    assert len(result.posts) == 5
    assert (workspace / "persona" / "opinions.toml").read_text(encoding="utf-8") == before_opinions
    assert not (workspace / "persona" / "memory" / "seen.jsonl").exists()


def test_max_posts_cap(workspace):
    result = run(make_config(workspace, max_posts=2))
    assert len(result.posts) == 2
    diary = (workspace / "persona" / "memory" / "diary.md").read_text(encoding="utf-8")
    assert diary.count("Paced out") >= 3


def test_determinism_across_runs(workspace, tmp_path):
    first = run(make_config(workspace, dry_state=True))
    second = run(make_config(workspace, dry_state=True, out_dir=workspace / "out2"))
    assert first.feed_toml.read_text(encoding="utf-8") == second.feed_toml.read_text(encoding="utf-8")
