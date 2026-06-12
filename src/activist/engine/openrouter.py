"""Real-LLM persona engine via OpenRouter's OpenAI-compatible API.

Network calls are never made by tests or CI; opt in with
``activist run --engine openrouter``. Requires OPENROUTER_API_KEY in the
environment or a .env file.

Model rotation: candidates are tried in order — free-tier (":free") models
first, then their paid twins, then OPENROUTER_MODEL — and the engine sticks
with the first model that answers. A model that errors (rate limit, 404,
empty reply) is skipped for the rest of the run. Configure via .env:

    OPENROUTER_MODELS_FREE=google/gemma-4-31b-it:free   # repeatable line
    OPENROUTER_MODEL=anthropic/claude-3.5-sonnet        # paid fallback
    OPENROUTER_ROTATE_MODELS=true                       # false = first model only

Guardrails (char limit, URL present, opinion-key validation, pacing) are
enforced downstream in the pipeline exactly as for MockBot — the prompt asks
nicely, the code enforces.
"""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path

from ..models import (
    DraftPost,
    Mention,
    NewsItem,
    Opinion,
    OpinionChange,
    Persona,
    Reaction,
    SaidEntry,
)
from .base import POST_CHAR_LIMIT
from .mockbot import _post_id

LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def _env_file_values(key: str, env_path: Path | None = None) -> list[str]:
    """All values for a key in .env, in file order.

    python-dotenv collapses duplicate keys (last wins), but we support the
    same key repeated to build a candidate list, so parse the file directly.
    """
    path = env_path or Path(".env")
    values: list[str] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == key:
                values.append(value.strip().strip("'\""))
    if not values and os.environ.get(key):
        values.append(os.environ[key])
    return values


def candidate_models(env_path: Path | None = None) -> list[str]:
    """Free candidates (":free" variants first), then the paid fallback."""
    free: list[str] = []
    for value in _env_file_values("OPENROUTER_MODELS_FREE", env_path):
        free.extend(m.strip() for m in value.split(",") if m.strip())
    free.sort(key=lambda m: not m.endswith(":free"))  # stable: :free first
    paid = os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL)
    candidates = free + [m.strip() for m in paid.split(",") if m.strip()]
    ordered: list[str] = []
    for model in candidates:
        if model not in ordered:
            ordered.append(model)
    return ordered or [DEFAULT_MODEL]


def _rotation_enabled() -> bool:
    return os.environ.get("OPENROUTER_ROTATE_MODELS", "true").strip().lower() in {"1", "true", "yes"}


class RotatingCompleter:
    """Tries model candidates in order; sticks with the first that answers.

    Shared by the persona engine and the LLM moderator. A model that errors
    (rate limit, 404, empty reply) is skipped for the rest of the session.
    """

    def __init__(self, models: list[str], client) -> None:
        if not models:
            raise ValueError("at least one model candidate is required")
        self.models = models
        self._client = client
        self._active = 0

    @property
    def active_model(self) -> str:
        return self.models[self._active]

    def complete(self, system: str, user: str) -> str:
        last_exc: Exception | None = None
        for idx in range(self._active, len(self.models)):
            model = self.models[idx]
            try:
                response = self._client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                content = (response.choices[0].message.content or "").strip()
                if not content:
                    raise RuntimeError("empty completion")
                self._active = idx  # stick with the first model that answers
                return content
            except Exception as exc:  # noqa: BLE001 - any API failure means rotate
                last_exc = exc
                if idx + 1 < len(self.models):
                    LOGGER.warning(
                        "Model %s failed (%s); rotating to %s", model, exc, self.models[idx + 1]
                    )
                    self._active = idx + 1
        raise RuntimeError(
            f"All OpenRouter candidates failed ({', '.join(self.models)}); last error: {last_exc}"
        ) from last_exc


def make_completer(model: str | None = None) -> RotatingCompleter:
    """Env-driven factory: .env candidates, rotation switch, OpenAI client."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    from openai import OpenAI  # already a project dependency

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Put it in .env or the environment "
            "(see spec/local_poc.md §9)."
        )
    if model:
        # explicit --model bypasses env-driven candidates
        models = [m.strip() for m in model.split(",") if m.strip()]
    else:
        models = candidate_models()
    if not _rotation_enabled():
        models = models[:1]
    LOGGER.info("OpenRouter model candidates (in order): %s", ", ".join(models))
    client = OpenAI(
        base_url=os.environ.get("OPENROUTER_BASE_URL", DEFAULT_BASE_URL),
        api_key=api_key,
        timeout=120.0,
        max_retries=1,
    )
    return RotatingCompleter(models, client)

SYSTEM_TEMPLATE = """You are {name} ({handle}), a Mastodon account on the low-carbon \
lifestyle beat. Bio: {bio}

Voice: {tone}
Rules:
{rules}

Hard constraints:
- You are a bot and never claim human experiences.
- A post must be at most {char_limit} characters INCLUDING the mandatory \
footer "{disclosure}" and the source URL.
- Every post must include the source article URL.
- You hold the opinions provided below. Your post must engage with them: \
reaffirm, push back, or change your mind. If the article genuinely changes \
your mind, say so explicitly and report the opinion change.
- If you have nothing opinionated to add, decline: return an empty post. \
Do not summarize news for its own sake.

Respond with TOML only, no prose, no code fences:

post = \"\"\"the post text, or empty to decline\"\"\"
diary_note = "one short sentence about what you read and what you did"

[[opinion_changes]]   # zero or more; only when you actually changed your mind
key = "an-existing-opinion-key"
new_stance = "the new stance"
reason = "why"
"""

USER_TEMPLATE = """## Your current opinions (TOML)
{opinions}

## Background knowledge you hold
{knowledge}

## Your recent posts (for continuity; don't repeat yourself)
{recent}

## The article
title: {title}
source: {feed}
url: {url}
published: {published}
summary: {summary}
"""

REPLY_SYSTEM_TEMPLATE = """You are {name} ({handle}), a Mastodon account on the \
low-carbon lifestyle beat. Bio: {bio}

Someone @-mentioned you and a human operator approved engaging. Draft ONE reply.

Voice: {tone}
Rules:
{rules}

Hard constraints:
- You are a bot and never claim human experiences.
- The reply must be at most {char_limit} characters INCLUDING the mandatory \
footer "{disclosure}".
- Address the author by their handle; be warm, direct, and substantive.
- Ground the reply in the opinions provided below; do not invent positions.
- No new hashtags, no @-mentions of anyone but the author.
- If the mention is hostile, bait, or engages nothing you hold an opinion \
on, decline: return an empty post. Threads do not need filler.

Respond with TOML only, no prose, no code fences:

post = \"\"\"the reply text, or empty to decline\"\"\"
diary_note = "one short sentence about what you did and why"
"""

REPLY_USER_TEMPLATE = """## Your current opinions (TOML)
{opinions}

## Background knowledge you hold
{knowledge}

## Your recent posts (for continuity)
{recent}

## The mention you are replying to
from: {author}
text: {mention_text}
"""


class OpenRouterBot:
    def __init__(self, model: str | None = None) -> None:
        self._completer = make_completer(model)

    @property
    def name(self) -> str:
        return f"openrouter:{self._completer.active_model}"

    def react(
        self,
        item: NewsItem,
        persona: Persona,
        opinions: dict[str, Opinion],
        knowledge: str,
        recent_said: list[SaidEntry],
        created: str,
    ) -> Reaction:
        system = SYSTEM_TEMPLATE.format(
            name=persona.name,
            handle=persona.handle,
            bio=persona.bio,
            tone=persona.voice_tone,
            rules="\n".join(f"- {r}" for r in persona.voice_rules),
            char_limit=POST_CHAR_LIMIT,
            disclosure=persona.disclosure,
        )
        user = USER_TEMPLATE.format(
            opinions=_opinions_toml(opinions),
            knowledge=knowledge or "(none)",
            recent="\n".join(f"- {s.date}: {s.summary}" for s in recent_said) or "(none)",
            title=item.title,
            feed=item.feed,
            url=item.url,
            published=item.published,
            summary=item.summary,
        )
        raw = self._complete(system, user)
        try:
            data = tomllib.loads(_strip_fences(raw))
        except tomllib.TOMLDecodeError as exc:
            LOGGER.warning("Model reply was not valid TOML, retrying once: %s", exc)
            raw = self._complete(
                system, user + f"\n\nYour previous reply failed to parse as TOML: {exc}. TOML only."
            )
            try:
                data = tomllib.loads(_strip_fences(raw))
            except tomllib.TOMLDecodeError:
                return Reaction(post=None, diary_note=f"Read '{item.title}' — model reply unparseable, abstained.")
        return self._to_reaction(data, item, persona, opinions, created)

    def reply(
        self,
        mention: Mention,
        persona: Persona,
        opinions: dict[str, Opinion],
        knowledge: str,
        recent_said: list[SaidEntry],
        created: str,
    ) -> Reaction:
        system = REPLY_SYSTEM_TEMPLATE.format(
            name=persona.name,
            handle=persona.handle,
            bio=persona.bio,
            tone=persona.voice_tone,
            rules="\n".join(f"- {r}" for r in persona.voice_rules),
            char_limit=POST_CHAR_LIMIT,
            disclosure=persona.disclosure,
        )
        user = REPLY_USER_TEMPLATE.format(
            opinions=_opinions_toml(opinions),
            knowledge=knowledge or "(none)",
            recent="\n".join(f"- {s.date}: {s.summary}" for s in recent_said) or "(none)",
            author=mention.author,
            mention_text=mention.text,
        )
        raw = self._complete(system, user)
        try:
            data = tomllib.loads(_strip_fences(raw))
        except tomllib.TOMLDecodeError as exc:
            LOGGER.warning("Reply was not valid TOML, retrying once: %s", exc)
            raw = self._complete(
                system, user + f"\n\nYour previous reply failed to parse as TOML: {exc}. TOML only."
            )
            try:
                data = tomllib.loads(_strip_fences(raw))
            except tomllib.TOMLDecodeError:
                return Reaction(
                    post=None,
                    diary_note=f"Mention from {mention.author} — model reply unparseable, stayed quiet.",
                )
        text = (data.get("post") or "").strip()
        diary = data.get("diary_note", f"Considered a mention from {mention.author}.")
        if not text:
            return Reaction(post=None, diary_note=diary)
        if mention.author not in text:
            text = f"{mention.author} {text}"
        if persona.disclosure not in text:
            text = f"{text}\n\n{persona.disclosure}"
        if len(text) > POST_CHAR_LIMIT:
            LOGGER.warning("Reply failed guardrails (%d chars), abstaining.", len(text))
            return Reaction(
                post=None,
                diary_note=f"Reply to {mention.author} failed guardrails; stayed quiet.",
            )
        keys = [k for k in opinions][:1] or ["reply"]
        return Reaction(
            post=DraftPost(
                id=_post_id(mention.id, keys[0]),
                created=created,
                status="draft",
                text=text,
                char_count=len(text),
                source_url="",
                source_title=f"mention from {mention.author}",
                opinion_keys=keys,
                engine=self.name,
                reply_to_id=mention.id,
                reply_to_author=mention.author,
                reply_to_text=mention.text,
            ),
            diary_note=diary,
        )

    def _complete(self, system: str, user: str) -> str:
        return self._completer.complete(system, user)

    def _to_reaction(
        self,
        data: dict,
        item: NewsItem,
        persona: Persona,
        opinions: dict[str, Opinion],
        created: str,
    ) -> Reaction:
        text = (data.get("post") or "").strip()
        diary = data.get("diary_note", f"Read '{item.title}'.")
        changes: list[OpinionChange] = []
        keys: list[str] = []
        for raw_change in data.get("opinion_changes", []):
            key = raw_change.get("key", "")
            if key not in opinions:
                LOGGER.warning("Dropping opinion change for unknown key %r", key)
                continue
            changes.append(
                OpinionChange(
                    key=key,
                    old_stance=opinions[key].stance,
                    new_stance=raw_change.get("new_stance", ""),
                    trigger_item=item.id,
                    reason=raw_change.get("reason", ""),
                )
            )
            keys.append(key)
        if not text:
            return Reaction(post=None, opinion_changes=changes, diary_note=diary)
        if persona.disclosure not in text:
            text = f"{text}\n\n{persona.disclosure}"
        if item.url not in text or len(text) > POST_CHAR_LIMIT:
            LOGGER.warning("Post failed guardrails (url present / %d chars), abstaining.", len(text))
            return Reaction(
                post=None, opinion_changes=[], diary_note=f"Read '{item.title}' — draft failed guardrails."
            )
        if not keys:
            # Post engages opinions even when none changed; attribute by topic.
            keys = [op.key for op in opinions.values()][:1] or ["unattributed"]
        return Reaction(
            post=DraftPost(
                id=_post_id(item.id, keys[0]),
                created=created,
                status="draft",
                text=text,
                char_count=len(text),
                source_url=item.url,
                source_title=item.title,
                opinion_keys=keys,
                engine=self.name,
                opinion_change=changes[0] if changes else None,
            ),
            opinion_changes=changes,
            diary_note=diary,
        )


def _opinions_toml(opinions: dict[str, Opinion]) -> str:
    lines: list[str] = []
    for op in opinions.values():
        lines.append(f"[{op.key}]")
        lines.append(f'topic = "{op.topic}"')
        lines.append(f'stance = "{op.stance}"')
        lines.append(f"strength = {op.strength}")
        lines.append(f'basis = "{op.basis}"')
        lines.append("")
    return "\n".join(lines) or "(none relevant)"


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()
