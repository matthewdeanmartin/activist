from activist.models import DraftPost, OpinionChange
from activist.queue_io import read_feed, write_feed
from activist.render import render_feed

RUN_META = {
    "date": "2026-06-11",
    "engine": "mockbot",
    "persona_name": "Lowwatt",
    "persona_handle": "@lowwatt@example.invalid",
    "persona_bio": "test bio",
    "items_ingested": 2,
    "items_relevant": 2,
    "posts": 2,
    "diary": "Read 'a thing'.\nPaced out: held one.",
}


def make_post(**overrides) -> DraftPost:
    defaults = dict(
        id="aaa111bbb222",
        created="2026-06-11T09:00:00",
        status="draft",
        text="Hello world. https://example.com/article\n\n🤖 bot post, human approved",
        char_count=70,
        source_url="https://example.com/article",
        source_title="An article",
        opinion_keys=["used-ev-value"],
        engine="mockbot",
        opinion_change=None,
    )
    defaults.update(overrides)
    return DraftPost(**defaults)


def test_feed_toml_round_trip(tmp_path):
    change = OpinionChange(
        key="heat-pump-top-pick", old_stance="old", new_stance="new", trigger_item="i1", reason="data"
    )
    posts = [make_post(), make_post(id="ccc333ddd444", opinion_change=change)]
    feed = tmp_path / "feed.toml"
    write_feed(feed, RUN_META, posts)
    data = read_feed(feed)
    assert data["run"]["date"] == "2026-06-11"
    assert len(data["post"]) == 2
    assert "opinion_change" not in data["post"][0]
    assert data["post"][1]["opinion_change"]["new_stance"] == "new"


def test_render_basics(tmp_path):
    change = OpinionChange(
        key="heat-pump-top-pick", old_stance="old stance", new_stance="new stance", trigger_item="i1", reason="data"
    )
    posts = [make_post(opinion_change=change)]
    feed = tmp_path / "feed.toml"
    write_feed(feed, RUN_META, posts)
    out = render_feed(feed)
    html_text = out.read_text(encoding="utf-8")

    assert out.name == "feed.html"
    assert "Hello world." in html_text
    assert '<a href="https://example.com/article">' in html_text  # autolinked
    assert "Changed my mind" in html_text  # change strip
    assert "old stance" in html_text and "new stance" in html_text
    assert "Simulation" in html_text  # never-posted banner
    assert "Paced out: held one." in html_text  # diary in footer


def test_render_escapes_html(tmp_path):
    posts = [
        make_post(
            text='<script>alert("x")</script> https://example.com/a?b=1&c=2\n\n🤖 bot',
            source_title='<img src=x onerror=alert(1)> & "quotes"',
        )
    ]
    feed = tmp_path / "feed.toml"
    write_feed(feed, RUN_META, posts)
    html_text = render_feed(feed).read_text(encoding="utf-8")
    assert "<script>" not in html_text
    assert "&lt;script&gt;" in html_text
    assert "<img src=x" not in html_text


def test_render_flags_over_limit_posts(tmp_path):
    long_text = "x" * 600
    posts = [make_post(text=long_text, char_count=len(long_text))]
    feed = tmp_path / "feed.toml"
    write_feed(feed, RUN_META, posts)
    html_text = render_feed(feed).read_text(encoding="utf-8")
    assert 'class="badge over"' in html_text
    assert "600/500" in html_text


def test_render_empty_run(tmp_path):
    feed = tmp_path / "feed.toml"
    write_feed(feed, {**RUN_META, "posts": 0, "diary": ""}, [])
    html_text = render_feed(feed).read_text(encoding="utf-8")
    assert "No posts this run" in html_text
    assert "No opinions changed" in html_text
