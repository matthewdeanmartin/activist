"""Shared builders for unit tests; e2e copies the real persona/ and fixtures/."""

from __future__ import annotations

from pathlib import Path

import pytest

from activist.models import NewsItem, Opinion, Persona

REPO_ROOT = Path(__file__).resolve().parents[1]


def make_persona(**overrides) -> Persona:
    defaults = dict(
        name="Lowwatt",
        handle="@lowwatt@example.invalid",
        bio="test bio",
        disclosure="🤖 bot post, human approved",
        voice_tone="enthusiast friend",
        voice_rules=[],
        topics=["heat pumps", "e-bikes", "EVs", "transit"],
        max_posts_per_run=6,
        posts_per_hour=4,
    )
    defaults.update(overrides)
    return Persona(**defaults)


def make_opinion(**overrides) -> Opinion:
    defaults = dict(
        key="heat-pump-top-pick",
        topic="heat pumps",
        stance="Brand XYZ's HP-9 is the best cold-climate heat pump",
        strength=0.8,
        since="2026-04-02",
        basis="NEEP field data",
        subject="Brand XYZ's HP-9",
        history=[],
    )
    defaults.update(overrides)
    return Opinion(**defaults)


def make_item(**overrides) -> NewsItem:
    defaults = dict(
        id="abc123def456",
        feed="Test Wire",
        title="ABC GW-200 posts COP 3.4 at -20C",
        url="https://example.com/gw200",
        published="2026-06-08",
        summary="Independent testing of a heat pump.",
        hints={},
    )
    defaults.update(overrides)
    return NewsItem(**defaults)


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT
