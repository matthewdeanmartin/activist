"""SQLite content queue — the single source of truth for content lifecycle.

Three processes share this file (fetcher writes, UI reads/writes, poster
claims), so every status change goes through :func:`Store.transition`, which
is a compare-and-swap: it only succeeds if the row still has the status the
caller saw. Persona state (opinions, memory) is NOT here — that stays
TOML/JSONL under git in persona/.

Lifecycle (spec/real_overview.md §3):

    pending_review ──approve──▶ approved ──claim──▶ publishing ──▶ published
          │                       │  ▲                  │
          └─reject─▶ rejected     │  └──retry── failed ◀┘
                                  └─un-approve─▶ pending_review
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .models import DraftPost, Flag

PENDING = "pending_review"
APPROVED = "approved"
REJECTED = "rejected"
PUBLISHING = "publishing"
PUBLISHED = "published"
FAILED = "failed"

STATUSES = (PENDING, APPROVED, REJECTED, PUBLISHING, PUBLISHED, FAILED)

# The complete map of legal status changes. Anything else is a bug, not a
# feature request: add it here deliberately or not at all.
LEGAL_TRANSITIONS: dict[tuple[str, str], str] = {
    (PENDING, APPROVED): "approve",
    (PENDING, REJECTED): "reject",
    (APPROVED, PENDING): "un-approve",
    (APPROVED, PUBLISHING): "claim",
    (PUBLISHING, PUBLISHED): "publish",
    (PUBLISHING, FAILED): "fail",
    (PUBLISHING, APPROVED): "release",  # e.g. 429 backoff re-queues the row
    (FAILED, APPROVED): "retry",
}


class StoreError(Exception):
    """Base class for queue store failures."""


class UnknownContent(StoreError):
    """No row with that id."""


class IllegalTransition(StoreError):
    """The (from, to) pair is not in LEGAL_TRANSITIONS — caller has a bug."""


class StaleStatus(StoreError):
    """Legal transition, but another process changed the row first (lost CAS)."""


@dataclass
class ContentRow:
    id: str
    kind: str  # 'post' | 'reply'
    status: str
    text: str
    created: str
    identity: str
    original_text: str | None = None
    scheduled_for: str | None = None
    source_url: str = ""
    source_title: str = ""
    opinion_keys: list[str] = field(default_factory=list)
    opinion_change: dict | None = None
    flags: list[dict] = field(default_factory=list)
    engine: str = ""
    in_reply_to_status_id: str = ""
    reply_to_author: str = ""
    reply_to_text: str = ""
    mastodon_status_id: str = ""
    published_at: str = ""
    rejected_reason: str = ""
    updated_at: str = ""

    @property
    def char_count(self) -> int:
        return len(self.text)

    def error_flags(self) -> list[dict]:
        return [f for f in self.flags if f.get("severity") == "error"]

    def warn_flags(self) -> list[dict]:
        return [f for f in self.flags if f.get("severity") == "warn"]


@dataclass
class Event:
    ts: str
    content_id: str
    actor: str  # 'human' | 'fetcher' | 'poster' | 'system'
    action: str
    detail: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS content (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  text TEXT NOT NULL,
  original_text TEXT,
  created TEXT NOT NULL,
  scheduled_for TEXT,
  source_url TEXT DEFAULT '',
  source_title TEXT DEFAULT '',
  opinion_keys TEXT DEFAULT '[]',
  opinion_change TEXT,
  flags TEXT DEFAULT '[]',
  engine TEXT DEFAULT '',
  identity TEXT NOT NULL,
  in_reply_to_status_id TEXT DEFAULT '',
  reply_to_author TEXT DEFAULT '',
  reply_to_text TEXT DEFAULT '',
  mastodon_status_id TEXT DEFAULT '',
  published_at TEXT DEFAULT '',
  rejected_reason TEXT DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_content_status ON content(status, scheduled_for);
CREATE TABLE IF NOT EXISTS event_log (
  ts TEXT NOT NULL,
  content_id TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_event_content ON event_log(content_id, ts);
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


class Store:
    """One store per database file; every call opens a short-lived connection,
    so a single Store instance is safe to share across threads/processes."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        try:
            with conn:  # one transaction per operation
                yield conn
        finally:
            conn.close()

    # --- writes --------------------------------------------------------------

    def add_pending(self, row: ContentRow, actor: str = "fetcher") -> None:
        row.status = PENDING
        row.updated_at = _now()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO content (id, kind, status, text, original_text, created,
                     scheduled_for, source_url, source_title, opinion_keys, opinion_change,
                     flags, engine, identity, in_reply_to_status_id, reply_to_author,
                     reply_to_text, mastodon_status_id, published_at, rejected_reason,
                     updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row.id, row.kind, row.status, row.text, row.original_text,
                    row.created, row.scheduled_for, row.source_url, row.source_title,
                    json.dumps(row.opinion_keys),
                    json.dumps(row.opinion_change) if row.opinion_change else None,
                    json.dumps(row.flags), row.engine, row.identity,
                    row.in_reply_to_status_id, row.reply_to_author, row.reply_to_text,
                    row.mastodon_status_id, row.published_at, row.rejected_reason,
                    row.updated_at,
                ),
            )
            self._log(conn, row.id, actor, "created", f"kind={row.kind}")

    def transition(
        self, content_id: str, from_status: str, to_status: str, actor: str, detail: str = ""
    ) -> None:
        """Compare-and-swap status change. The ONLY way status moves.

        Raises IllegalTransition for pairs outside the lifecycle map, and
        StaleStatus when another process won the race (caller should re-read
        and tell the human, not retry blindly).
        """
        action = LEGAL_TRANSITIONS.get((from_status, to_status))
        if action is None:
            raise IllegalTransition(f"{from_status} -> {to_status} is not a legal transition")
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE content SET status=?, updated_at=? WHERE id=? AND status=?",
                (to_status, _now(), content_id, from_status),
            )
            if cur.rowcount == 0:
                row = conn.execute(
                    "SELECT status FROM content WHERE id=?", (content_id,)
                ).fetchone()
                if row is None:
                    raise UnknownContent(content_id)
                raise StaleStatus(
                    f"{content_id}: expected {from_status}, found {row['status']}"
                )
            self._log(conn, content_id, actor, action, detail)

    def set_kv(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO kv (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def log_event(self, content_id: str, actor: str, action: str, detail: str = "") -> None:
        """Append a non-transition event (fetch summaries use content_id='-')."""
        with self._conn() as conn:
            self._log(conn, content_id, actor, action, detail)

    @staticmethod
    def _log(conn: sqlite3.Connection, content_id: str, actor: str, action: str, detail: str) -> None:
        conn.execute(
            "INSERT INTO event_log (ts, content_id, actor, action, detail) VALUES (?,?,?,?,?)",
            (_now(), content_id, actor, action, detail),
        )

    # --- reads ---------------------------------------------------------------

    def get(self, content_id: str) -> ContentRow:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM content WHERE id=?", (content_id,)).fetchone()
        if row is None:
            raise UnknownContent(content_id)
        return _row_to_content(row)

    def list_by_status(self, status: str) -> list[ContentRow]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM content WHERE status=? ORDER BY created DESC", (status,)
            ).fetchall()
        return [_row_to_content(r) for r in rows]

    def counts(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute("SELECT status, COUNT(*) n FROM content GROUP BY status").fetchall()
        found = {r["status"]: r["n"] for r in rows}
        return {status: found.get(status, 0) for status in STATUSES}

    def has(self, content_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM content WHERE id=?", (content_id,)).fetchone()
        return row is not None

    def events(self, content_id: str) -> list[Event]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM event_log WHERE content_id=? ORDER BY ts", (content_id,)
            ).fetchall()
        return [Event(r["ts"], r["content_id"], r["actor"], r["action"], r["detail"]) for r in rows]

    def last_event(self, action: str) -> Event | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM event_log WHERE action=? ORDER BY ts DESC LIMIT 1", (action,)
            ).fetchone()
        if row is None:
            return None
        return Event(row["ts"], row["content_id"], row["actor"], row["action"], row["detail"])

    def get_kv(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def _row_to_content(row: sqlite3.Row) -> ContentRow:
    return ContentRow(
        id=row["id"],
        kind=row["kind"],
        status=row["status"],
        text=row["text"],
        original_text=row["original_text"],
        created=row["created"],
        scheduled_for=row["scheduled_for"],
        source_url=row["source_url"],
        source_title=row["source_title"],
        opinion_keys=json.loads(row["opinion_keys"] or "[]"),
        opinion_change=json.loads(row["opinion_change"]) if row["opinion_change"] else None,
        flags=json.loads(row["flags"] or "[]"),
        engine=row["engine"],
        identity=row["identity"],
        in_reply_to_status_id=row["in_reply_to_status_id"],
        reply_to_author=row["reply_to_author"],
        reply_to_text=row["reply_to_text"],
        mastodon_status_id=row["mastodon_status_id"],
        published_at=row["published_at"],
        rejected_reason=row["rejected_reason"],
        updated_at=row["updated_at"],
    )


def row_from_draft(post: DraftPost, flags: list[Flag], identity: str) -> ContentRow:
    """Bridge the POC pipeline's DraftPost into a queue row (fetcher F2 sink)."""
    from dataclasses import asdict

    return ContentRow(
        id=post.id,
        kind="reply" if post.reply_to_id else "post",
        status=PENDING,
        text=post.text,
        created=post.created,
        scheduled_for=post.created,  # ratelimit already spaced the slots
        identity=identity,
        source_url=post.source_url,
        source_title=post.source_title,
        opinion_keys=list(post.opinion_keys),
        opinion_change=asdict(post.opinion_change) if post.opinion_change else None,
        flags=[asdict(f) for f in flags],
        engine=post.engine,
        in_reply_to_status_id=post.reply_to_id,
        reply_to_author=post.reply_to_author,
        reply_to_text=post.reply_to_text,
    )
