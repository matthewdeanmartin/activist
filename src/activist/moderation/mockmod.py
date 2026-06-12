"""Deterministic moderator: the code-enforceable content rules from the app
policy (docs/draft_governing_policy.md).

Rate limiting is deliberately NOT here — pacing is enforced upstream by the
scheduler (activist.ratelimit) when drafts are created. This moderator only
judges content. These checks ALWAYS run, regardless of which moderation
engine is chosen; an LLM moderator is layered on top for the judgment calls
(tone, sarcasm, controversy) that regexes can't make.

Replies (posts with ``reply_to_id``) are exempt from two rules: they may
@-mention the person they answer, and they don't need a source link.
"""

from __future__ import annotations

import re

from ..engine.base import POST_CHAR_LIMIT
from ..models import Flag
from .base import ModerationContext

# Generic/popular tags the app policy bans outright (§5); any other hashtag
# is a warn because popularity can't be verified offline.
POPULAR_TAGS = {"news", "tech", "ai", "climate", "politics", "mastodon", "fediverse"}

HASHTAG_RE = re.compile(r"(?<!\S)#(\w+)")
MENTION_RE = re.compile(r"(?<!\S)@\w+")
URL_RE = re.compile(r"https?://\S+")

# App policy §1: no first-person human experience claims.
HUMAN_CLAIM_RES = [
    re.compile(
        r"\bI\s+(attended|visited|drove|rode|met|grew\s+up|bought|installed|cooked|ate|own)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmy\s+(house|home|apartment|family|kids?|wife|husband|partner|car|garage|kitchen|neighborhood)\b",
        re.IGNORECASE,
    ),
]


class MockModerator:
    name = "mockmod"

    def review(self, post: dict, ctx: ModerationContext) -> list[Flag]:
        text = post.get("text", "")
        is_reply = bool(post.get("reply_to_id"))
        flags: list[Flag] = []

        if post.get("char_count", len(text)) > POST_CHAR_LIMIT:
            flags.append(
                Flag(
                    severity="error",
                    policy="app",
                    rule="char-limit",
                    detail=f"{post.get('char_count')} chars exceeds the {POST_CHAR_LIMIT}-char limit.",
                )
            )

        if ctx.disclosure and ctx.disclosure not in text:
            flags.append(
                Flag(
                    severity="error",
                    policy="app",
                    rule="missing-disclosure",
                    detail=f'Required bot disclosure "{ctx.disclosure}" is missing.',
                )
            )

        if not is_reply and not URL_RE.search(text):
            flags.append(
                Flag(
                    severity="error",
                    policy="app",
                    rule="missing-source-link",
                    detail="Post does not link its source article.",
                )
            )

        if is_reply:
            # Replies have no pipeline-supplied source, so any URL in one was
            # invented by the engine — a hallucinated citation until verified.
            for url in URL_RE.findall(text):
                flags.append(
                    Flag(
                        severity="warn",
                        policy="app",
                        rule="unverified-link",
                        detail=f"Reply contains a link the pipeline didn't supply: {url} — verify it exists.",
                    )
                )

        for tag in HASHTAG_RE.findall(text):
            if tag.lower() in POPULAR_TAGS:
                flags.append(
                    Flag(
                        severity="error",
                        policy="app",
                        rule="popular-hashtag",
                        detail=f"#{tag} is a popular/generic tag; policy forbids tag-surfing.",
                    )
                )
            else:
                flags.append(
                    Flag(
                        severity="warn",
                        policy="app",
                        rule="hashtag",
                        detail=f"#{tag}: only uncommon discoverability tags are allowed; verify.",
                    )
                )

        if not is_reply and MENTION_RE.search(text):
            flags.append(
                Flag(
                    severity="error",
                    policy="app",
                    rule="cold-mention",
                    detail="Top-level posts must not @-mention users (mentions only in replies).",
                )
            )

        for pattern in HUMAN_CLAIM_RES:
            match = pattern.search(text)
            if match:
                flags.append(
                    Flag(
                        severity="error",
                        policy="app",
                        rule="human-claim",
                        detail=f'"{match.group(0)}" reads as a human experience claim.',
                    )
                )

        return flags
