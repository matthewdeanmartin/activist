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
    posts_per_hour: int = 4  # app policy §3 pacing; scheduler enforces it


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
    created: str  # scheduled slot, spaced to satisfy the effective hourly limit
    status: str  # always "draft" in this phase
    text: str  # the would-be toot, including disclosure footer
    char_count: int  # Mastodon default limit is 500
    source_url: str
    source_title: str
    opinion_keys: list[str]
    engine: str
    opinion_change: OpinionChange | None = None
    # set only on reply drafts (Phase 3)
    reply_to_id: str = ""  # notification/mention id — the dedup key, not for threading
    reply_to_author: str = ""
    reply_to_text: str = ""
    # the real Mastodon status this reply threads onto (fetcher F3). Empty on
    # fixture replies and top-level posts; the poster needs it for in_reply_to_id.
    reply_to_status_id: str = ""
    # match the audience of what we answer — never widen a DM into a public reply.
    # "" means "use the config default" (top-level posts always leave this empty).
    visibility: str = ""


@dataclass
class Mention:
    """One inbound mention (simulated from a fixture file in this phase)."""

    id: str  # the notification id — the checkpoint/dedup key, NOT the status id
    author: str  # full handle, e.g. "@solarfan@mastodon.social"
    text: str
    author_bio: str = ""
    author_is_bot: bool = False
    created: str = ""
    hints: dict[str, str] = field(default_factory=dict)  # fixture-only, like NewsItem.hints
    # carried from the live API (fetcher F3); empty on fixture mentions.
    status_id: str = ""  # the status to thread the reply onto (in_reply_to_id)
    visibility: str = ""  # public | unlisted | private | direct — the reply must match


@dataclass
class SaidEntry:
    """One line of persona/memory/said.jsonl."""

    date: str
    post_id: str
    topic: str
    opinion_keys: list[str]
    summary: str


@dataclass
class Flag:
    """One moderation finding attached to a post. Flags never drop posts."""

    severity: str  # "error" | "warn"
    policy: str  # "app" or an instance domain, e.g. "infosec.exchange"
    rule: str  # short id, e.g. "char-limit", "human-claim"
    detail: str


@dataclass
class Reaction:
    """What an engine produced for one NewsItem."""

    post: DraftPost | None  # None = "read it, nothing worth saying"
    opinion_changes: list[OpinionChange] = field(default_factory=list)
    reinforcements: list[str] = field(default_factory=list)  # opinion keys to strengthen
    pushbacks: list[dict[str, str]] = field(default_factory=list)  # {key, reason}
    diary_note: str = ""
