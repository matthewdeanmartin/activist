"""LLM moderator via OpenRouter, layered on top of MockModerator's checks.

It handles the judgment calls regexes can't: tone, sarcasm, controversy,
impersonation vibes, and reading instance policy prose against the post.
Uses the same free-first model rotation as the persona engine.
"""

from __future__ import annotations

import logging
import tomllib

from ..engine.openrouter import _strip_fences, make_completer
from ..models import Flag
from .base import ModerationContext

LOGGER = logging.getLogger(__name__)

# Instance policy files are scraped pages; keep prompts bounded.
POLICY_TEXT_LIMIT = 8000

SYSTEM_PROMPT = """You are a strict but fair Mastodon moderation assistant for a \
human-in-the-loop bot. You receive the bot's governing policy, optional server \
(instance) policies, and ONE draft post. Decide whether the post violates any \
policy. Judgment calls (tone, sarcasm, rage-bait, controversy, human \
impersonation, off-mission content) are YOUR job; mechanical checks (length, \
links, hashtags, rate) are already handled elsewhere — do not repeat them.

Respond with TOML only, no prose, no code fences. Zero or more flags:

[[flags]]
severity = "error"            # "error" = clear violation, "warn" = borderline
policy = "app"                # "app" or the instance domain the rule comes from
rule = "short-kebab-id"
detail = "one sentence explaining the problem, quoting the offending phrase"

If the post is compliant, respond with exactly: flags = []
Do not invent rules that are not in the provided policies."""

USER_TEMPLATE = """## App governing policy
{app_policy}

{instance_sections}

## The draft post (verbatim)
{text}
"""


class OpenRouterModerator:
    def __init__(self, model: str | None = None) -> None:
        self._completer = make_completer(model)

    @property
    def name(self) -> str:
        return f"openrouter:{self._completer.active_model}"

    def review(self, post: dict, ctx: ModerationContext) -> list[Flag]:
        instance_sections = "\n\n".join(
            f"## Instance policy: {domain}\n{text[:POLICY_TEXT_LIMIT]}"
            for domain, text in ctx.instance_policies.items()
        )
        user = USER_TEMPLATE.format(
            app_policy=ctx.app_policy[:POLICY_TEXT_LIMIT],
            instance_sections=instance_sections,
            text=post.get("text", ""),
        )
        raw = self._completer.complete(SYSTEM_PROMPT, user)
        try:
            data = tomllib.loads(_strip_fences(raw))
        except tomllib.TOMLDecodeError as exc:
            LOGGER.warning("Moderator reply was not valid TOML, retrying once: %s", exc)
            raw = self._completer.complete(
                SYSTEM_PROMPT,
                user + f"\n\nYour previous reply failed to parse as TOML: {exc}. TOML only.",
            )
            try:
                data = tomllib.loads(_strip_fences(raw))
            except tomllib.TOMLDecodeError:
                return [
                    Flag(
                        severity="warn",
                        policy="app",
                        rule="moderator-unparseable",
                        detail="LLM moderator reply could not be parsed; review manually.",
                    )
                ]
        valid_policies = {"app", *ctx.instance_policies}
        flags: list[Flag] = []
        for raw_flag in data.get("flags", []):
            severity = raw_flag.get("severity", "warn")
            if severity not in {"error", "warn"}:
                severity = "warn"
            policy = raw_flag.get("policy", "app")
            if policy not in valid_policies:
                policy = "app"
            flags.append(
                Flag(
                    severity=severity,
                    policy=policy,
                    rule=raw_flag.get("rule", "llm-flag"),
                    detail=raw_flag.get("detail", ""),
                )
            )
        return flags
