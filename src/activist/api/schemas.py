"""Pydantic request/response models for the admin API (spec/admin_site.md §5).

These mirror store.ContentRow / store.Event and the persona/account/engine
"triple" from personas.md. Secrets never appear here — no token ever crosses
the wire.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..store import ContentRow, Event

CHAR_LIMIT = 500  # Mastodon default; over this is an error flag.


class FlagOut(BaseModel):
    severity: str
    policy: str
    rule: str
    detail: str


class ContentOut(BaseModel):
    id: str
    kind: str
    status: str
    text: str
    original_text: str | None = None
    created: str
    identity: str
    scheduled_for: str | None = None
    not_before: str = ""
    source_url: str = ""
    source_title: str = ""
    opinion_keys: list[str] = []
    opinion_change: dict | None = None
    flags: list[dict] = []
    engine: str = ""
    in_reply_to_status_id: str = ""
    reply_to_author: str = ""
    reply_to_text: str = ""
    visibility: str = ""
    mastodon_status_id: str = ""
    published_url: str = ""
    published_at: str = ""
    rejected_reason: str = ""
    updated_at: str = ""
    # derived (so the client doesn't recompute the Flask templates' logic)
    char_count: int = 0
    over_limit: bool = False
    is_reply: bool = False
    error_count: int = 0
    warn_count: int = 0

    @classmethod
    def from_row(cls, row: ContentRow) -> "ContentOut":
        return cls(
            id=row.id,
            kind=row.kind,
            status=row.status,
            text=row.text,
            original_text=row.original_text,
            created=row.created,
            identity=row.identity,
            scheduled_for=row.scheduled_for,
            not_before=row.not_before,
            source_url=row.source_url,
            source_title=row.source_title,
            opinion_keys=row.opinion_keys,
            opinion_change=row.opinion_change,
            flags=row.flags,
            engine=row.engine,
            in_reply_to_status_id=row.in_reply_to_status_id,
            reply_to_author=row.reply_to_author,
            reply_to_text=row.reply_to_text,
            visibility=row.visibility,
            mastodon_status_id=row.mastodon_status_id,
            published_url=row.published_url,
            published_at=row.published_at,
            rejected_reason=row.rejected_reason,
            updated_at=row.updated_at,
            char_count=row.char_count,
            over_limit=row.char_count > CHAR_LIMIT,
            is_reply=row.kind == "reply",
            error_count=len(row.error_flags()),
            warn_count=len(row.warn_flags()),
        )


class EventOut(BaseModel):
    ts: str
    content_id: str
    actor: str
    action: str
    detail: str

    @classmethod
    def from_event(cls, ev: Event) -> "EventOut":
        return cls(
            ts=ev.ts,
            content_id=ev.content_id,
            actor=ev.actor,
            action=ev.action,
            detail=ev.detail,
        )


class ContentDetailOut(BaseModel):
    content: ContentOut
    events: list[EventOut]


class PersonaOut(BaseModel):
    persona_id: str
    name: str
    handle: str
    bio: str
    disclosure: str
    active: bool = False


class AccountOut(BaseModel):
    mastodon_id: str
    base_url: str = ""
    instances: list[str] = []
    handle: str | None = None  # verified public handle, if a read-only check ran
    verified: bool = False


class EngineProfileOut(BaseModel):
    engine: str
    model: str | None = None
    moderation_engine: str
    poster_live: bool
    default_visibility: str


class ProfileOut(BaseModel):
    """The dashboard header: who/what/how-richly + queue glance."""

    persona: PersonaOut
    account: AccountOut
    engine: EngineProfileOut
    counts: dict[str, int]
    last_fetch: EventOut | None = None
    # False until the poster's live publisher (P2) exists; gates the
    # already-posted edit/delete buttons in the UI.
    live_edit_available: bool = False


# --- request bodies ---------------------------------------------------------


class RejectIn(BaseModel):
    reason: str = ""


class EditIn(BaseModel):
    text: str
