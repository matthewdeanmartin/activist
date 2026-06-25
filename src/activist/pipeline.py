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
class EngineOutput:
    """Everything one engine pass produced, before any sink sees it.

    Shared by the fixture path (run → feed.toml) and the live path
    (fetch → store); the loop, pacing, and guardrails are identical.
    """

    posts: list[DraftPost] = field(default_factory=list)
    changes: list[OpinionChange] = field(default_factory=list)
    reinforcements: list[str] = field(default_factory=list)
    pushbacks: list[dict[str, str]] = field(default_factory=list)
    diary: list[str] = field(default_factory=list)
    said_entries: list[SaidEntry] = field(default_factory=list)
    seen_rows: list[dict] = field(default_factory=list)
    relevant_count: int = 0
    log_lines: list[str] = field(default_factory=list)


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

    out = react_to_items(
        items,
        persona=persona,
        opinions=opinions,
        knowledge_path=knowledge_path,
        seen_ids=seen_ids,
        recent_said=recent_said,
        date=cfg.date,
        engine=cfg.engine,
        max_posts=max_posts,
        slot_for=lambda index: ratelimit.slot_time(cfg.date, index, per_hour),
    )
    posts = out.posts
    diary = out.diary
    relevant_count = out.relevant_count
    log.extend(out.log_lines)

    if not cfg.dry_state:
        apply_engine_state(cfg.persona_dir, cfg.date, cfg.engine.name, opinions, out)
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


def react_to_items(
    items: list[NewsItem],
    *,
    persona,
    opinions: dict[str, Opinion],
    knowledge_path: Path,
    seen_ids: set[str],
    recent_said: list[SaidEntry],
    date: str,
    engine: PersonaEngine,
    max_posts: int,
    slot_for,
    engine_call_budget: int | None = None,
) -> EngineOutput:
    """The engine loop: dedupe, relevance, react, pace. No I/O sinks here.

    ``slot_for(index)`` supplies the scheduled timestamp for the index-th
    draft — fixture runs space within the run date, live runs continue after
    whatever the queue already holds.

    ``engine_call_budget`` caps how many items get an ``engine.react()``
    call this run (each call is a real LLM request for the openrouter
    engine). ``max_posts`` only caps how many *drafts get kept* — without
    this budget, a large feed still pays for an LLM call on every
    topic-matched item even once the draft quota is full. Once the budget
    is spent, remaining items are left off ``seen_rows`` so they are
    reconsidered (not silently dropped) on the next run.
    """
    out = EngineOutput()
    posted_keys: set[str] = set()
    engine_calls = 0

    for item in items:
        if item.id in seen_ids:
            out.log_lines.append(f"ITEM {item.id} '{item.title}' SKIP already-seen")
            continue
        matched = relevance.match_topics(item, persona.topics)
        if matched and engine_call_budget is not None and engine_calls >= engine_call_budget:
            out.log_lines.append(
                f"ITEM {item.id} '{item.title}' DEFERRED engine-call-budget exhausted"
            )
            continue
        out.seen_rows.append(
            {
                "id": item.id,
                "url": item.url,
                "title": item.title,
                "date_seen": date,
                "topics": matched,
                "relevant": bool(matched),
            }
        )
        if not matched:
            out.log_lines.append(f"ITEM {item.id} '{item.title}' IRRELEVANT")
            continue
        out.relevant_count += 1

        relevant_ops = _relevant_opinions(opinions, matched, item)
        knowledge = state.knowledge_sections(knowledge_path, matched)
        created = slot_for(len(out.posts))
        engine_calls += 1
        reaction = engine.react(item, persona, relevant_ops, knowledge, recent_said, created)
        if reaction.diary_note:
            out.diary.append(reaction.diary_note)

        if reaction.post is None:
            out.log_lines.append(f"ITEM {item.id} '{item.title}' ABSTAIN")
            out.changes.extend(reaction.opinion_changes)
            continue

        post = reaction.post
        if len(out.posts) >= max_posts or any(k in posted_keys for k in post.opinion_keys):
            out.diary.append(
                f"Paced out: had a post for '{item.title}' but held it (rate/key limit)."
            )
            out.log_lines.append(f"ITEM {item.id} '{item.title}' PACED-OUT")
            continue
        if post.char_count > POST_CHAR_LIMIT:
            LOGGER.warning("Post %s is %d chars (> %d)", post.id, post.char_count, POST_CHAR_LIMIT)
            out.log_lines.append(f"ITEM {item.id} '{item.title}' WARN over-{POST_CHAR_LIMIT}-chars")

        out.posts.append(post)
        posted_keys.update(post.opinion_keys)
        out.changes.extend(reaction.opinion_changes)
        out.reinforcements.extend(reaction.reinforcements)
        out.pushbacks.extend(reaction.pushbacks)
        out.said_entries.append(_said_entry(date, post, relevant_ops, reaction))
        kind = "CHANGED-MIND" if post.opinion_change else "POST"
        out.log_lines.append(f"ITEM {item.id} '{item.title}' {kind} keys={post.opinion_keys}")

    return out


def apply_engine_state(
    persona_dir: Path,
    date: str,
    engine_name: str,
    opinions: dict[str, Opinion],
    out: EngineOutput,
) -> None:
    """Write everything an engine pass changed back into persona/."""
    memory_dir = persona_dir / "memory"
    _apply_state(persona_dir, date, opinions, out.changes, out.reinforcements, out.pushbacks)
    state.append_seen(memory_dir, out.seen_rows)
    state.append_said(memory_dir, out.said_entries)
    state.append_diary(memory_dir, date, engine_name, out.diary)


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
    persona_dir: Path,
    date: str,
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
        op.since = date
        op.basis = change.reason
        op.history.append({"date": date, "stance": change.new_stance, "trigger": change.reason})
    for key in reinforcements:
        op = opinions.get(key)
        if op is not None:
            op.strength = round(min(1.0, op.strength + 0.05), 2)
    for push in pushbacks:
        op = opinions.get(push["key"])
        if op is not None:
            op.history.append(
                {"date": date, "stance": op.stance, "trigger": f"pushed back: {push['reason']}"}
            )
    state.save_opinions(persona_dir / "opinions.toml", opinions)
