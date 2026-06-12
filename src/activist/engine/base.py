"""The engine seam: everything upstream and downstream of this is shared."""

from __future__ import annotations

from typing import Protocol

from ..models import Mention, NewsItem, Opinion, Persona, Reaction, SaidEntry

# Mastodon's default per-post character limit.
POST_CHAR_LIMIT = 500

# At or above this conviction strength, a challenge gets pushback instead of
# a change of mind.
CONVICTION_THRESHOLD = 0.85


class PersonaEngine(Protocol):
    @property
    def name(self) -> str: ...

    def react(
        self,
        item: NewsItem,
        persona: Persona,
        opinions: dict[str, Opinion],
        knowledge: str,
        recent_said: list[SaidEntry],
        created: str,
    ) -> Reaction: ...

    def reply(
        self,
        mention: Mention,
        persona: Persona,
        opinions: dict[str, Opinion],
        knowledge: str,
        recent_said: list[SaidEntry],
        created: str,
    ) -> Reaction:
        """Draft a reply to an inbound mention that already passed consent gates."""
        ...
