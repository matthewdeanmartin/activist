"""Orchestrates one run: ingest -> filter -> engine -> state -> queue -> render.

Pacing and state guardrails live here, engine-agnostically: max one post per
opinion key per run, max N posts per run, dedupe against seen.jsonl.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from . import ingest, ratelimit, relevance, render, state
from .engine import PersonaEngine
from .engine.base import POST_CHAR_LIMIT
from .models import DraftPost, NewsItem, Opinion, OpinionChange, SaidEntry
from .queue_io import write_feed

LOGGER = logging.getLogger(__name__)


@dataclass
class RunConfig:
    fixtures_dir: Path
    persona_dir: Path
    out_dir: Path
    date: str  # YYYY-MM-DD; namespaces out/ and timestamps memory
    engine: PersonaEngine
    dry_state: bool = False
    max_posts: int | None = None  # None = persona's limit
    # target instances; their policies tighten the scheduler's hourly pacing
    instance_policies: dict[str, str] = field(default_factory=dict)


@dataclass
class RunResult:
    feed_toml: Path
    feed_html: Path
    posts: list[DraftPost] = field(default_factory=list)
    items_ingested: int = 0
    items_relevant: int = 0
    log_lines: list[str] = field(default_factory=list)


def run(cfg: RunConfig) -> RunResult:
    persona = state.load_persona(cfg.persona_dir / "persona.toml")
    opinions = state.load_opinions(cfg.persona_dir / "opinions.toml")
    knowledge_path = cfg.persona_dir / "knowledge.md"
    memory_dir = cfg.persona_dir / "memory"
    seen_ids = state.load_seen_ids(memory_dir)
    recent_said = state.load_said(memory_dir, n=5)
    max_posts = cfg.max_posts if cfg.max_posts is not None else persona.max_posts_per_run
    per_hour = ratelimit.effective_hourly_limit(persona.posts_per_hour, cfg.instance_policies)

    items = ingest.parse_fixtures_dir(cfg.fixtures_dir)
    log: list[str] = [f"RUN date={cfg.date} engine={cfg.engine.name} fixtures={cfg.fixtures_dir}"]
    log.append(f"INGEST items={len(items)}")
    log.append(f"PACING {per_hour}/hour (app={persona.posts_per_hour}, instances={sorted(cfg.instance_policies)})")

    posts: list[DraftPost] = []
    changes: list[OpinionChange] = []
    reinforcements: list[str] = []
    pushbacks: list[dict[str, str]] = []
    diary: list[str] = []
    said_entries: list[SaidEntry] = []
    seen_rows: list[dict] = []
    posted_keys: set[str] = set()
    relevant_count = 0

    for item in items:
        if item.id in seen_ids:
            log.append(f"ITEM {item.id} '{item.title}' SKIP already-seen")
            continue
        matched = relevance.match_topics(item, persona.topics)
        seen_rows.append(
            {
                "id": item.id,
                "url": item.url,
                "title": item.title,
                "date_seen": cfg.date,
                "topics": matched,
                "relevant": bool(matched),
            }
        )
        if not matched:
            log.append(f"ITEM {item.id} '{item.title}' IRRELEVANT")
            continue
        relevant_count += 1

        relevant_ops = _relevant_opinions(opinions, matched, item)
        knowledge = state.knowledge_sections(knowledge_path, matched)
        created = ratelimit.slot_time(cfg.date, len(posts), per_hour)
        reaction = cfg.engine.react(item, persona, relevant_ops, knowledge, recent_said, created)
        if reaction.diary_note:
            diary.append(reaction.diary_note)

        if reaction.post is None:
            log.append(f"ITEM {item.id} '{item.title}' ABSTAIN")
            changes.extend(reaction.opinion_changes)
            continue

        post = reaction.post
        if len(posts) >= max_posts or any(k in posted_keys for k in post.opinion_keys):
            diary.append(f"Paced out: had a post for '{item.title}' but held it (rate/key limit).")
            log.append(f"ITEM {item.id} '{item.title}' PACED-OUT")
            continue
        if post.char_count > POST_CHAR_LIMIT:
            LOGGER.warning("Post %s is %d chars (> %d)", post.id, post.char_count, POST_CHAR_LIMIT)
            log.append(f"ITEM {item.id} '{item.title}' WARN over-{POST_CHAR_LIMIT}-chars")

        posts.append(post)
        posted_keys.update(post.opinion_keys)
        changes.extend(reaction.opinion_changes)
        reinforcements.extend(reaction.reinforcements)
        pushbacks.extend(reaction.pushbacks)
        said_entries.append(_said_entry(cfg.date, post, relevant_ops, reaction))
        kind = "CHANGED-MIND" if post.opinion_change else "POST"
        log.append(f"ITEM {item.id} '{item.title}' {kind} keys={post.opinion_keys}")

    if not cfg.dry_state:
        _apply_state(cfg, opinions, changes, reinforcements, pushbacks)
        state.append_seen(memory_dir, seen_rows)
        state.append_said(memory_dir, said_entries)
        state.append_diary(memory_dir, cfg.date, cfg.engine.name, diary)
    else:
        log.append("STATE dry-run: persona/ untouched")

    run_dir = cfg.out_dir / cfg.date
    run_dir.mkdir(parents=True, exist_ok=True)
    feed_toml = run_dir / "feed.toml"
    write_feed(
        feed_toml,
        {
            "date": cfg.date,
            "engine": cfg.engine.name,
            "persona_name": persona.name,
            "persona_handle": persona.handle,
            "persona_bio": persona.bio,
            "items_ingested": len(items),
            "items_relevant": relevant_count,
            "posts": len(posts),
            "posts_per_hour": per_hour,
            "instances": sorted(cfg.instance_policies),
            "diary": "\n".join(diary),
        },
        posts,
    )
    feed_html = render.render_feed(feed_toml)
    (run_dir / "run.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    return RunResult(
        feed_toml=feed_toml,
        feed_html=feed_html,
        posts=posts,
        items_ingested=len(items),
        items_relevant=relevant_count,
        log_lines=log,
    )


def _relevant_opinions(
    opinions: dict[str, Opinion], matched_topics: list[str], item: NewsItem
) -> dict[str, Opinion]:
    """Opinions on the matched beats, plus any the item's hints name."""
    hinted = {item.hints.get("challenges", ""), item.hints.get("supports", "")}
    return {
        key: op
        for key, op in opinions.items()
        if op.topic in matched_topics or key in hinted
    }


def _said_entry(date: str, post: DraftPost, opinions: dict[str, Opinion], reaction) -> SaidEntry:
    key = post.opinion_keys[0]
    opinion = opinions.get(key)
    topic = opinion.topic if opinion else ""
    if post.opinion_change:
        summary = f"changed my mind on {topic}: {post.opinion_change.new_stance}"
    elif reaction.pushbacks:
        summary = f"held firm on {topic}: {opinion.stance if opinion else ''}"
    else:
        summary = f"reaffirmed on {topic}: {opinion.stance if opinion else ''}"
    return SaidEntry(
        date=date, post_id=post.id, topic=topic, opinion_keys=post.opinion_keys, summary=summary
    )


def _apply_state(
    cfg: RunConfig,
    opinions: dict[str, Opinion],
    changes: list[OpinionChange],
    reinforcements: list[str],
    pushbacks: list[dict[str, str]],
) -> None:
    for change in changes:
        op = opinions.get(change.key)
        if op is None:
            LOGGER.warning("Opinion change for unknown key %r dropped", change.key)
            continue
        op.stance = change.new_stance
        op.since = cfg.date
        op.basis = change.reason
        op.history.append({"date": cfg.date, "stance": change.new_stance, "trigger": change.reason})
    for key in reinforcements:
        op = opinions.get(key)
        if op is not None:
            op.strength = round(min(1.0, op.strength + 0.05), 2)
    for push in pushbacks:
        op = opinions.get(push["key"])
        if op is not None:
            op.history.append(
                {"date": cfg.date, "stance": op.stance, "trigger": f"pushed back: {push['reason']}"}
            )
    state.save_opinions(cfg.persona_dir / "opinions.toml", opinions)
