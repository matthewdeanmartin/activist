"""Phase 3: reply drafts for inbound mentions (simulated from fixtures).

Consent rules from the governing policy are enforced HERE, in ordinary code,
before any engine sees the mention: the bot only answers when explicitly
summoned, respects #nobot, never talks to other bots (no loops), and never
re-replies to a mention it already handled. The engine only decides what to
say — never whether it is allowed to speak.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import ratelimit, relevance, render, state
from .engine import PersonaEngine
from .ingest import parse_hints
from .models import DraftPost, Mention, Persona, SaidEntry
from .queue_io import write_feed

LOGGER = logging.getLogger(__name__)


@dataclass
class ReplyRunConfig:
    mentions_path: Path
    persona_dir: Path
    out_dir: Path
    date: str
    engine: PersonaEngine
    dry_state: bool = False
    max_replies: int | None = None  # None = persona's max_posts_per_run
    instance_policies: dict[str, str] = field(default_factory=dict)


@dataclass
class ReplyRunResult:
    replies_toml: Path
    replies_html: Path
    posts: list[DraftPost] = field(default_factory=list)
    mentions_total: int = 0
    mentions_eligible: int = 0
    log_lines: list[str] = field(default_factory=list)


def load_mentions(path: Path) -> list[Mention]:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    mentions: list[Mention] = []
    for raw in data.get("mention", []):
        mentions.append(
            Mention(
                id=raw["id"],
                author=raw["author"],
                text=raw.get("text", ""),
                author_bio=raw.get("author_bio", ""),
                author_is_bot=raw.get("author_is_bot", False),
                created=raw.get("created", ""),
                hints=parse_hints(raw.get("hint", "")),
            )
        )
    return mentions


def consent_skip_reason(mention: Mention, persona: Persona, handled_ids: set[str]) -> str | None:
    """The governing policy's consent gates. None means the engine may draft."""
    if mention.id in handled_ids:
        return "already handled"
    if persona.handle not in mention.text:
        return "did not summon the bot (no explicit @mention)"
    if "#nobot" in mention.author_bio.lower():
        return "author opted out (#nobot in bio)"
    if mention.author_is_bot:
        return "author is a bot (no bot-to-bot loops)"
    return None


def run_replies(cfg: ReplyRunConfig) -> ReplyRunResult:
    persona = state.load_persona(cfg.persona_dir / "persona.toml")
    opinions = state.load_opinions(cfg.persona_dir / "opinions.toml")
    knowledge_path = cfg.persona_dir / "knowledge.md"
    memory_dir = cfg.persona_dir / "memory"
    handled_ids = state.load_handled_mentions(memory_dir)
    recent_said = state.load_said(memory_dir, n=5)
    max_replies = cfg.max_replies if cfg.max_replies is not None else persona.max_posts_per_run
    per_hour = ratelimit.effective_hourly_limit(persona.posts_per_hour, cfg.instance_policies)

    mentions = load_mentions(cfg.mentions_path)
    log: list[str] = [
        f"REPLIES date={cfg.date} engine={cfg.engine.name} mentions={cfg.mentions_path}",
        f"PACING {per_hour}/hour (app={persona.posts_per_hour}, instances={sorted(cfg.instance_policies)})",
    ]

    posts: list[DraftPost] = []
    diary: list[str] = []
    said_entries: list[SaidEntry] = []
    handled_rows: list[dict] = []
    eligible = 0

    for mention in mentions:
        skip = consent_skip_reason(mention, persona, handled_ids)
        if skip == "already handled":
            log.append(f"MENTION {mention.id} from {mention.author} SKIP {skip}")
            continue
        if skip is not None:
            log.append(f"MENTION {mention.id} from {mention.author} GATE {skip}")
            handled_rows.append(_handled(mention, cfg.date, "gated", skip))
            continue
        eligible += 1

        topics = relevance.match_topics_text(mention.text, persona.topics)
        relevant_ops = {
            key: op
            for key, op in opinions.items()
            if op.topic in topics or key == mention.hints.get("asks", "")
        }
        knowledge = state.knowledge_sections(knowledge_path, topics)
        created = ratelimit.slot_time(cfg.date, len(posts), per_hour)
        reaction = cfg.engine.reply(
            mention, persona, relevant_ops, knowledge, recent_said, created
        )
        if reaction.diary_note:
            diary.append(reaction.diary_note)

        if reaction.post is None:
            log.append(f"MENTION {mention.id} from {mention.author} DECLINED")
            handled_rows.append(_handled(mention, cfg.date, "declined", reaction.diary_note))
            continue
        if len(posts) >= max_replies:
            diary.append(f"Paced out: had a reply for {mention.author} but held it (rate limit).")
            log.append(f"MENTION {mention.id} from {mention.author} PACED-OUT")
            continue

        posts.append(reaction.post)
        handled_rows.append(_handled(mention, cfg.date, "replied", reaction.post.id))
        key = reaction.post.opinion_keys[0] if reaction.post.opinion_keys else ""
        topic = opinions[key].topic if key in opinions else ""
        said_entries.append(
            SaidEntry(
                date=cfg.date,
                post_id=reaction.post.id,
                topic=topic,
                opinion_keys=reaction.post.opinion_keys,
                summary=f"replied to {mention.author} about {topic or 'their mention'}",
            )
        )
        log.append(f"MENTION {mention.id} from {mention.author} REPLY")

    if not cfg.dry_state:
        state.append_handled_mentions(memory_dir, handled_rows)
        state.append_said(memory_dir, said_entries)
        state.append_diary(memory_dir, cfg.date, cfg.engine.name, diary)
    else:
        log.append("STATE dry-run: persona/ untouched")

    run_dir = cfg.out_dir / cfg.date
    run_dir.mkdir(parents=True, exist_ok=True)
    replies_toml = run_dir / "replies.toml"
    write_feed(
        replies_toml,
        {
            "date": cfg.date,
            "kind": "replies",
            "engine": cfg.engine.name,
            "persona_name": persona.name,
            "persona_handle": persona.handle,
            "persona_bio": persona.bio,
            "items_ingested": len(mentions),
            "items_relevant": eligible,
            "posts": len(posts),
            "posts_per_hour": per_hour,
            "instances": sorted(cfg.instance_policies),
            "diary": "\n".join(diary),
        },
        posts,
    )
    replies_html = render.render_feed(replies_toml)
    (run_dir / "replies.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    return ReplyRunResult(
        replies_toml=replies_toml,
        replies_html=replies_html,
        posts=posts,
        mentions_total=len(mentions),
        mentions_eligible=eligible,
        log_lines=log,
    )


def _handled(mention: Mention, date: str, status: str, detail: str) -> dict:
    return {
        "id": mention.id,
        "author": mention.author,
        "date": date,
        "status": status,
        "detail": detail,
    }
