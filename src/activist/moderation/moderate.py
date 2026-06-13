"""Moderation orchestrator: feed.toml in, feed.toml + flags out.

Posts are flagged, never dropped — the human adjudicates. MockModerator's
deterministic checks always run; an optional LLM moderator adds judgment
calls on top. Re-moderating a feed replaces prior flags (idempotent).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..models import Flag
from ..queue_io import read_feed, write_feed_doc
from ..render import render_feed
from .base import ModerationContext, ModeratorEngine
from .mockmod import MockModerator


@dataclass
class ModerationResult:
    feed_toml: Path
    feed_html: Path
    posts: int = 0
    errors: int = 0
    warns: int = 0
    flagged_posts: int = 0
    flags: list[Flag] = field(default_factory=list)


def moderate_post(
    post: dict,
    ctx: ModerationContext,
    llm_moderator: ModeratorEngine | None = None,
) -> list[Flag]:
    """Flags for one post dict — the inline seam the live fetch chain uses
    before a draft ever reaches the queue store."""
    flags = MockModerator().review(post, ctx)
    if llm_moderator is not None:
        flags.extend(llm_moderator.review(post, ctx))
    return flags


def moderate_feed(
    feed_path: Path,
    ctx: ModerationContext,
    llm_moderator: ModeratorEngine | None = None,
) -> ModerationResult:
    doc = read_feed(feed_path)
    posts = doc.get("post", [])
    mock = MockModerator()
    engines = f"{mock.name}+{llm_moderator.name}" if llm_moderator else mock.name

    result = ModerationResult(feed_toml=feed_path, feed_html=feed_path.with_suffix(".html"))
    result.posts = len(posts)
    for post in posts:
        flags = mock.review(post, ctx)
        if llm_moderator is not None:
            flags.extend(llm_moderator.review(post, ctx))
        post.pop("flags", None)  # idempotent re-moderation
        if flags:
            post["flags"] = [asdict(f) for f in flags]
            result.flagged_posts += 1
        result.flags.extend(flags)

    result.errors = sum(f.severity == "error" for f in result.flags)
    result.warns = sum(f.severity == "warn" for f in result.flags)
    doc["run"]["moderation"] = {
        "engine": engines,
        "instances": sorted(ctx.instance_policies),
        "errors": result.errors,
        "warns": result.warns,
    }
    write_feed_doc(feed_path, doc)
    result.feed_html = render_feed(feed_path)
    return result
