from pathlib import Path

from activist import state
from activist.models import SaidEntry
from tests.conftest import make_opinion

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_load_persona_from_repo_seed():
    persona = state.load_persona(REPO_ROOT / "persona" / "persona.toml")
    assert persona.name == "Lowwatt"
    assert "heat pumps" in persona.topics
    assert persona.max_posts_per_run == 6
    assert persona.disclosure.startswith("🤖")


def test_opinions_round_trip(tmp_path):
    # the pristine snapshot: the live persona/opinions.toml mutates with runs
    original = state.load_opinions(REPO_ROOT / "tests" / "seed_opinions.toml")
    assert "heat-pump-top-pick" in original
    assert original["heat-pump-top-pick"].subject == "Brand XYZ's HP-9"
    assert original["heat-pump-top-pick"].history[0]["trigger"] == "initial seed"

    out = tmp_path / "opinions.toml"
    state.save_opinions(out, original)
    reloaded = state.load_opinions(out)
    assert reloaded == original
    # key order preserved (git-diff friendliness)
    assert list(reloaded) == list(original)


def test_save_opinion_without_subject(tmp_path):
    op = make_opinion(subject="")
    out = tmp_path / "opinions.toml"
    state.save_opinions(out, {op.key: op})
    assert state.load_opinions(out)[op.key].subject == ""


def test_knowledge_sections_filters_by_topic():
    path = REPO_ROOT / "persona" / "knowledge.md"
    text = state.knowledge_sections(path, ["heat pumps"])
    assert "## Heat pumps" in text
    assert "COP" in text
    assert "E-bikes" not in text
    both = state.knowledge_sections(path, ["heat pumps", "transit"])
    assert "## Heat pumps" in both and "## Transit" in both
    assert state.knowledge_sections(path, ["nonexistent topic"]) == ""
    assert state.knowledge_sections(path.with_name("missing.md"), ["heat pumps"]) == ""


def test_seen_memory_round_trip(tmp_path):
    mem = tmp_path / "memory"
    assert state.load_seen_ids(mem) == set()
    state.append_seen(mem, [{"id": "aaa", "url": "u", "title": "t", "date_seen": "d", "topics": [], "relevant": False}])
    state.append_seen(mem, [{"id": "bbb", "url": "u", "title": "t", "date_seen": "d", "topics": ["EVs"], "relevant": True}])
    assert state.load_seen_ids(mem) == {"aaa", "bbb"}


def test_said_memory_round_trip(tmp_path):
    mem = tmp_path / "memory"
    assert state.load_said(mem) == []
    entries = [
        SaidEntry(date=f"2026-06-{i:02d}", post_id=f"p{i}", topic="EVs", opinion_keys=["used-ev-value"], summary=f"s{i}")
        for i in range(1, 8)
    ]
    state.append_said(mem, entries)
    last = state.load_said(mem, n=5)
    assert len(last) == 5
    assert last[-1].summary == "s7"
    assert last[0].summary == "s3"


def test_diary_appends_dated_section(tmp_path):
    mem = tmp_path / "memory"
    state.append_diary(mem, "2026-06-11", "mockbot", ["note one", "note two"])
    text = (mem / "diary.md").read_text(encoding="utf-8")
    assert "## 2026-06-11 (mockbot)" in text
    assert "- note one" in text
    state.append_diary(mem, "2026-06-12", "mockbot", [])  # no notes, no section
    assert "2026-06-12" not in (mem / "diary.md").read_text(encoding="utf-8")
