"""Dataclasses shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NewsItem:
    """One article pulled from a feed."""

    id: str  # sha256(url)[:12]
    feed: str
    title: str
    url: str
    published: str
    summary: str
    hints: dict[str, str] = field(default_factory=dict)


@dataclass
class Opinion:
    """One held opinion, loaded from persona/opinions.toml."""

    key: str
    topic: str
    stance: str
    strength: float  # 0..1 conviction; below CONVICTION_THRESHOLD it can be swayed
    since: str
    basis: str
    subject: str = ""  # short phrase, e.g. "Brand XYZ's HP-9"
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Persona:
    """Identity and voice, loaded from persona/persona.toml."""

    name: str
    handle: str
    bio: str
    disclosure: str
    voice_tone: str
    voice_rules: list[str]
    topics: list[str]
    max_posts_per_run: int = 6


@dataclass
class OpinionChange:
    key: str
    old_stance: str
    new_stance: str
    trigger_item: str  # NewsItem.id
    reason: str


@dataclass
class DraftPost:
    id: str
    created: str
    status: str  # always "draft" in this phase
    text: str  # the would-be toot, including disclosure footer
    char_count: int  # Mastodon default limit is 500
    source_url: str
    source_title: str
    opinion_keys: list[str]
    engine: str
    opinion_change: OpinionChange | None = None


@dataclass
class SaidEntry:
    """One line of persona/memory/said.jsonl."""

    date: str
    post_id: str
    topic: str
    opinion_keys: list[str]
    summary: str


@dataclass
class Reaction:
    """What an engine produced for one NewsItem."""

    post: DraftPost | None  # None = "read it, nothing worth saying"
    opinion_changes: list[OpinionChange] = field(default_factory=list)
    reinforcements: list[str] = field(default_factory=list)  # opinion keys to strengthen
    pushbacks: list[dict[str, str]] = field(default_factory=list)  # {key, reason}
    diary_note: str = ""
