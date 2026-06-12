"""Rate limiting is ordinary code: parsing, strictest-limit math, slot times."""

from pathlib import Path

import pytest

from activist.moderation.policies import load_instance_policy
from activist.ratelimit import (
    assign_slots,
    effective_hourly_limit,
    parse_hourly_limit,
    slot_time,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("limited to one post per hour/24 per day", 1),
        ("less than one post per hour", 1),
        ("no more than 4 posts per hour", 4),
        ("two posts per hour are fine", 2),
        ("no rate language here", None),
    ],
)
def test_parse_hourly_limit(text, expected):
    assert parse_hourly_limit(text) == expected


def test_real_instance_policies_parse():
    policies_dir = REPO_ROOT / "policies"
    assert parse_hourly_limit(load_instance_policy(policies_dir, "infosec.exchange")) == 1
    assert parse_hourly_limit(load_instance_policy(policies_dir, "mas.to")) == 1


def test_effective_limit_is_strictest():
    assert effective_hourly_limit(4, {}) == 4
    assert effective_hourly_limit(4, {"strict.example": "one post per hour"}) == 1
    assert effective_hourly_limit(2, {"loose.example": "6 posts per hour"}) == 2
    assert effective_hourly_limit(4, {"silent.example": "no rate language"}) == 4
    # never below 1, even with nonsense input
    assert effective_hourly_limit(0, {}) == 1


def test_slot_times_at_app_pacing():
    # 4/hour -> 15-minute spacing from 09:00
    assert assign_slots(5, "2026-06-11", 4) == [
        "2026-06-11T09:00:00",
        "2026-06-11T09:15:00",
        "2026-06-11T09:30:00",
        "2026-06-11T09:45:00",
        "2026-06-11T10:00:00",
    ]


def test_slot_times_at_strict_instance_pacing():
    # 1/hour -> hourly spacing
    assert assign_slots(3, "2026-06-11", 1) == [
        "2026-06-11T09:00:00",
        "2026-06-11T10:00:00",
        "2026-06-11T11:00:00",
    ]


def test_slot_time_floors_interval_at_one_minute():
    assert slot_time("2026-06-11", 1, 120) == "2026-06-11T09:01:00"
