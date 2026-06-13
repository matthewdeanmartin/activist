"""The moderator seam, mirroring the PersonaEngine seam.

A moderator reviews one draft post (as its feed.toml dict) and returns
flags. The deterministic MockModerator always runs; an LLM moderator can
be layered on top for the policy reading code can't do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..models import Flag


@dataclass
class ModerationContext:
    disclosure: str  # the required footer, from persona.toml
    app_policy: str  # text of packaged governing_policy.md, or an override
    instance_policies: dict[str, str] = field(default_factory=dict)  # domain -> policy text


class ModeratorEngine(Protocol):
    @property
    def name(self) -> str: ...

    def review(self, post: dict, ctx: ModerationContext) -> list[Flag]:
        """Flags for one post. Rate limiting is the scheduler's job, not ours."""
        ...
