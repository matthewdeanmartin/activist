from pathlib import Path

from activist import ingest

FEEDS = Path(__file__).resolve().parents[1] / "fixtures" / "feeds"


def test_parse_rss_fixture():
    items = ingest.parse_feed(FEEDS / "cleantechnica-sample.xml")
    assert len(items) == 3
    first = items[0]
    assert first.feed == "CleanTech Sample Wire"
    assert first.title.startswith("ABC GW-200")
    assert first.url == "https://example.com/cleantech/abc-gw200-review"
    assert len(first.id) == 12
    # HTML stripped from description
    assert "<p>" not in first.summary
    assert "GW-200" in first.summary
    # hints parsed
    assert first.hints["challenges"] == "heat-pump-top-pick"
    assert first.hints["subject"] == "ABC's GW-200"
    # item without a hint element has empty hints
    assert items[2].hints == {}


def test_parse_atom_fixture():
    items = ingest.parse_feed(FEEDS / "canarymedia-sample.xml")
    assert len(items) == 3
    assert items[0].feed == "Canary Sample Wire"
    assert items[0].url == "https://example.com/canary/ebike-carshare-pilot"
    assert items[0].hints["challenges"] == "ebike-vs-car"
    assert items[0].published == "2026-06-08T10:00:00Z"


def test_malformed_feed_degrades_to_empty(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<rss><channel><item>unclosed", encoding="utf-8")
    assert ingest.parse_feed(bad) == []


def test_unknown_root_degrades_to_empty(tmp_path):
    weird = tmp_path / "weird.xml"
    weird.write_text("<opml></opml>", encoding="utf-8")
    assert ingest.parse_feed(weird) == []


def test_parse_hints_grammar():
    hints = ingest.parse_hints("challenges=key-a; claim=COP of 3.4 at -20C; subject=ABC's GW-200")
    assert hints == {
        "challenges": "key-a",
        "claim": "COP of 3.4 at -20C",
        "subject": "ABC's GW-200",
    }
    assert ingest.parse_hints(None) == {}
    assert ingest.parse_hints("no-equals-sign-here") == {}


def test_item_id_is_stable():
    assert ingest.item_id("https://example.com/a") == ingest.item_id("https://example.com/a")
    assert ingest.item_id("https://example.com/a") != ingest.item_id("https://example.com/b")


def test_parse_fixtures_dir_sorted_by_filename():
    items = ingest.parse_fixtures_dir(FEEDS)
    assert len(items) == 8
    # canarymedia < cleantechnica < heatpumped
    assert items[0].feed == "Canary Sample Wire"
    assert items[3].feed == "CleanTech Sample Wire"
    assert items[6].feed == "Heat Pumped Sample Wire"
