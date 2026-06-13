"""Live replies fetcher (fetcher Phase F3).

The fixture path (`replies.run_replies`) and this live path share everything
that matters: the same consent gates in `replies.consent_skip_reason`, the
same `engine.reply`, the same moderation. The only difference is the source —
here mentions come from `MastodonReader.notifications` instead of a TOML file,
and survivors land in the SQLite queue as `pending_review` rows (`kind='reply'`)
rather than an `out/<date>/replies.toml` artifact.

Read-only by construction: this module only ever *reads* the timeline. Drafts
wait in the queue for a human; the poster (gated, Phase P2) is the only thing
that writes back to Mastodon.

Dedup is belt-and-suspenders (spec F3 item 3):
  * the ``since_id`` checkpoint in the store's ``kv`` table means the API only
    returns notifications we haven't seen, and
  * ``memory/mentions.jsonl`` (the handled set) is still consulted, so even a
    replayed or out-of-order notification can't produce a second reply.
"""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from dataclasses import dataclass, field

from . import ratelimit, relevance, state
from .config import AppConfig
from .engine import PersonaEngine
from .mastodon_client import (
    CredentialsError,
    MastodonCredentials,
    MastodonReader,
    notification_to_mention,
)
from .models import Mention, SaidEntry
from .replies import consent_skip_reason
from .store import Store, row_from_draft

LOGGER = logging.getLogger(__name__)


def since_id_key(identity: str) -> str:
    return f"mastodon:{identity.upper()}:notifications:since_id"


@dataclass
class ReplyFetchResult:
    """One live replies pass (fetcher Phase F3)."""

    mentions_total: int = 0
    eligible: int = 0  # passed the consent gates
    inserted: int = 0  # reply drafts queued as pending_review
    duplicates: int = 0  # store rejected the id (already queued)
    gated: int = 0  # consent gate refused
    declined: int = 0  # engine read it, said nothing
    errors: int = 0  # moderation error flags across inserted drafts
    warns: int = 0
    new_since_id: str | None = None
    log_lines: list[str] = field(default_factory=list)


def run_reply_chain(
    cfg: AppConfig,
    engine: PersonaEngine,
    store: Store,
    reader: MastodonReader | None = None,
    dry_run: bool = False,
    now: dt.datetime | None = None,
    llm_moderator=None,
    limit: int = 30,
) -> ReplyFetchResult:
    """notifications → map → consent gates → engine.reply → moderate → queue.

    ``reader`` is injected by tests (a fake-transport MastodonReader); in
    production it's built from the configured identity's env credentials.
    ``dry_run`` previews the whole chain without writing the store, the
    checkpoint, or persona/.
    """
    from .moderation import ModerationContext, moderate_post
    from .moderation.policies import load_app_policy, load_instance_policy
    from .queue_io import _post_dict

    persona = state.load_persona(cfg.persona_dir / "persona.toml")
    opinions = state.load_opinions(cfg.persona_dir / "opinions.toml")
    knowledge_path = cfg.persona_dir / "knowledge.md"
    memory_dir = cfg.persona_dir / "memory"
    handled_ids = state.load_handled_mentions(memory_dir)
    recent_said = state.load_said(memory_dir, n=5)
    instance_policies = {
        domain: load_instance_policy(cfg.policies_dir, domain)
        for domain in cfg.instances
        if domain not in cfg.instance_rate_limits
    }
    app_limit = cfg.rate_limit_posts_per_hour or persona.posts_per_hour
    per_hour = ratelimit.effective_hourly_limit(
        app_limit, instance_policies, cfg.instance_rate_limits
    )
    now = ratelimit.aware_utc(now or dt.datetime.now(dt.UTC))

    own_reader = reader is None
    if reader is None:
        reader = MastodonReader(MastodonCredentials.from_env(cfg.mastodon_id))

    result = ReplyFetchResult()
    try:
        since_id = store.get_kv(since_id_key(cfg.mastodon_id)) or None
        notifications = reader.notifications(
            types=["mention"], since_id=since_id, limit=limit
        )
        result.mentions_total = len(notifications)
        result.log_lines.append(
            f"NOTIFICATIONS {len(notifications)} mentions since_id={since_id or '(none)'}"
        )
        result.log_lines.append(
            f"PACING {per_hour}/hour (app={app_limit}, instances={sorted(instance_policies)})"
        )

        # API returns newest first; reverse so slots are assigned oldest-first
        # and the checkpoint advances monotonically to the newest id we saw.
        mentions = [notification_to_mention(n) for n in reversed(notifications)]
        max_notification_id = _max_id(notifications)

        ctx = ModerationContext(
            disclosure=persona.disclosure,
            app_policy=load_app_policy(cfg.app_policy),
            instance_policies=instance_policies,
        )
        last_slot = store.last_scheduled_for(cfg.mastodon_id)

        rows = []
        said_entries: list[SaidEntry] = []
        handled_rows: list[dict] = []
        for mention in mentions:
            skip = consent_skip_reason(mention, persona, handled_ids)
            if skip is not None:
                if skip == "already handled":
                    result.log_lines.append(f"MENTION {mention.id} SKIP {skip}")
                    continue
                result.gated += 1
                result.log_lines.append(
                    f"MENTION {mention.id} from {mention.author} GATE {skip}"
                )
                handled_rows.append(_handled(mention, now, "gated", skip))
                continue
            result.eligible += 1

            topics = relevance.match_topics_text(mention.text, persona.topics)
            relevant_ops = {
                key: op
                for key, op in opinions.items()
                if op.topic in topics or key == mention.hints.get("asks", "")
            }
            knowledge = state.knowledge_sections(knowledge_path, topics)
            slot = ratelimit.continued_slot(len(rows), per_hour, now, last_slot)
            reaction = engine.reply(
                mention, persona, relevant_ops, knowledge, recent_said, slot
            )
            if reaction.post is None:
                result.declined += 1
                result.log_lines.append(
                    f"MENTION {mention.id} from {mention.author} DECLINED"
                )
                handled_rows.append(_handled(mention, now, "declined", reaction.diary_note))
                continue

            flags = moderate_post(_post_dict(reaction.post), ctx, llm_moderator)
            result.errors += sum(f.severity == "error" for f in flags)
            result.warns += sum(f.severity == "warn" for f in flags)
            rows.append(row_from_draft(reaction.post, flags, identity=cfg.mastodon_id))
            handled_rows.append(_handled(mention, now, "replied", reaction.post.id))
            key = reaction.post.opinion_keys[0] if reaction.post.opinion_keys else ""
            topic = opinions[key].topic if key in opinions else ""
            said_entries.append(
                SaidEntry(
                    date=now.date().isoformat(),
                    post_id=reaction.post.id,
                    topic=topic,
                    opinion_keys=reaction.post.opinion_keys,
                    summary=f"replied to {mention.author} about {topic or 'their mention'}",
                )
            )
            result.log_lines.append(f"MENTION {mention.id} from {mention.author} REPLY")

        result.new_since_id = max_notification_id

        if dry_run:
            result.log_lines.append("DRY-RUN store, checkpoint, and persona/ untouched")
            return result

        for row in rows:
            try:
                store.add_pending(row)
                result.inserted += 1
            except sqlite3.IntegrityError:
                result.duplicates += 1
                result.log_lines.append(f"DUPLICATE {row.id} already queued; skipped")

        # Advance the checkpoint and write the handled set together so a crash
        # can at worst re-offer (the handled set + PRIMARY KEY both still guard).
        if max_notification_id:
            store.set_kv(since_id_key(cfg.mastodon_id), max_notification_id)
        state.append_handled_mentions(memory_dir, handled_rows)
        state.append_said(memory_dir, said_entries)
        store.log_event(
            "-",
            "fetcher",
            "replies",
            f"{result.mentions_total} mentions, {result.inserted} reply drafts queued, "
            f"{result.gated} gated, {result.declined} declined",
        )
    finally:
        if own_reader:
            reader.close()
    return result


def _max_id(notifications: list[dict]) -> str | None:
    """Highest notification id seen, by numeric value (Mastodon ids are
    snowflake-ordered strings). Returns the string form for the API."""
    best: int | None = None
    best_str: str | None = None
    for note in notifications:
        raw = str(note.get("id", ""))
        try:
            value = int(raw)
        except ValueError:
            continue
        if best is None or value > best:
            best, best_str = value, raw
    return best_str


def _handled(mention: Mention, now: dt.datetime, status: str, detail: str) -> dict:
    return {
        "id": mention.id,
        "author": mention.author,
        "date": now.date().isoformat(),
        "status": status,
        "detail": detail,
    }


def build_reader(cfg: AppConfig) -> MastodonReader:
    """Live reader from the configured identity; raises CredentialsError if env
    is missing (the CLI turns that into a clean message)."""
    return MastodonReader(MastodonCredentials.from_env(cfg.mastodon_id))


__all__ = [
    "ReplyFetchResult",
    "run_reply_chain",
    "since_id_key",
    "build_reader",
    "CredentialsError",
]
