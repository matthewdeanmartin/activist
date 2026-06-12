import pytest

from activist.relevance import is_relevant, match_topics
from tests.conftest import make_item

TOPICS = [
    "heat pumps",
    "e-bikes",
    "induction stoves",
    "home insulation",
    "EVs",
    "rooftop solar",
    "transit",
    "low-carbon diet",
]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("New heat pump posts record COP", ["heat pumps"]),
        ("Cargo bikes are eating car trips", ["e-bikes"]),
        ("Induction cooktop sales double", ["induction stoves"]),
        ("Attic insulation rebates expand", ["home insulation"]),
        ("Used EV prices fall 22%", ["EVs"]),
        ("Rooftop solar payback improves", ["rooftop solar"]),
        ("Bus rapid transit line approved", ["transit"]),
        ("Beef lifecycle emissions revised", ["low-carbon diet"]),
        ("Quarterly turbine earnings beat expectations", []),
        ("Local sports team wins championship", []),
    ],
)
def test_topic_table(title, expected):
    item = make_item(title=title, summary="", hints={})
    assert match_topics(item, TOPICS) == expected
    assert is_relevant(item, TOPICS) is (bool(expected))


def test_word_boundaries_avoid_substring_hits():
    # "evolve" must not match the "ev" synonym
    item = make_item(title="Markets evolve in every level", summary="")
    assert match_topics(item, TOPICS) == []


def test_match_in_summary_counts():
    item = make_item(title="Big news today", summary="A study about heat pumps.")
    assert match_topics(item, TOPICS) == ["heat pumps"]


def test_multiple_topics_in_beats_order():
    item = make_item(title="Pair rooftop solar with a heat pump", summary="")
    assert match_topics(item, TOPICS) == ["heat pumps", "rooftop solar"]
