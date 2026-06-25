"""Queue browse + actions (spec/admin_site.md §3).

Every mutation goes through store.py's CAS, so a button that races the poster
(or another tab) loses politely with a 409 instead of corrupting the lifecycle —
the JSON equivalent of the Flask UI's flash messages.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from ..config import AppConfig
from ..moderation import ModerationContext, moderate_post
from ..store import (
    APPROVED,
    FAILED,
    PENDING,
    REJECTED,
    STATUSES,
    IllegalTransition,
    NotEditable,
    StaleStatus,
    Store,
    UnknownContent,
)
from .deps import get_cfg, get_llm_moderator, get_mod_ctx, get_store
from .schemas import (
    ContentDetailOut,
    ContentOut,
    EditIn,
    EventOut,
    RejectIn,
)

router = APIRouter(prefix="/api", tags=["queue"])


def _get_row(store: Store, content_id: str):
    try:
        return store.get(content_id)
    except UnknownContent:
        raise HTTPException(404, f"no content {content_id!r}")


def _flags_for(text: str, row, ctx: ModerationContext, llm=None) -> list[dict]:
    """Re-run moderation for an edited/rechecked post (web/views.py parity)."""
    flags = moderate_post(
        {
            "text": text,
            "char_count": len(text),
            "reply_to_id": row.in_reply_to_status_id,
        },
        ctx,
        llm_moderator=llm,
    )
    return [asdict(f) for f in flags]


# --- reads ------------------------------------------------------------------


@router.get("/counts")
def counts(store: Store = Depends(get_store)) -> dict[str, int]:
    return store.counts()


@router.get("/queue", response_model=list[ContentOut])
def queue(status: str = PENDING, store: Store = Depends(get_store)) -> list[ContentOut]:
    if status not in STATUSES:
        raise HTTPException(404, f"unknown status {status!r}")
    return [ContentOut.from_row(r) for r in store.list_by_status(status)]


@router.get("/upcoming", response_model=list[ContentOut])
def upcoming(
    store: Store = Depends(get_store), cfg: AppConfig = Depends(get_cfg)
) -> list[ContentOut]:
    """Approved posts for the active identity, in slot order — what's coming up.

    The store returns them ordered by scheduled_for; the client derives "due"
    from scheduled_for vs now.
    """
    return [ContentOut.from_row(r) for r in store.upcoming(cfg.mastodon_id)]


@router.get("/content/{content_id}", response_model=ContentDetailOut)
def detail(content_id: str, store: Store = Depends(get_store)) -> ContentDetailOut:
    row = _get_row(store, content_id)
    return ContentDetailOut(
        content=ContentOut.from_row(row),
        events=[EventOut.from_event(e) for e in store.events(content_id)],
    )


# --- transitions ------------------------------------------------------------


def _transition(store: Store, content_id: str, frm: str, to: str, detail: str = ""):
    try:
        store.transition(content_id, frm, to, actor="human", detail=detail)
    except UnknownContent:
        raise HTTPException(404, f"no content {content_id!r}")
    except StaleStatus as exc:
        raise HTTPException(409, detail={"error": "stale", "detail": str(exc)})
    except IllegalTransition as exc:
        raise HTTPException(409, detail={"error": "illegal", "detail": str(exc)})


@router.post("/content/{content_id}/approve", response_model=ContentOut)
def approve(content_id: str, store: Store = Depends(get_store)) -> ContentOut:
    _transition(store, content_id, PENDING, APPROVED)
    return ContentOut.from_row(store.get(content_id))


@router.post("/content/{content_id}/reject", response_model=ContentOut)
def reject(
    content_id: str, body: RejectIn | None = None, store: Store = Depends(get_store)
) -> ContentOut:
    reason = (body.reason if body else "").strip()
    _transition(store, content_id, PENDING, REJECTED, detail=reason)
    return ContentOut.from_row(store.get(content_id))


@router.post("/content/{content_id}/unapprove", response_model=ContentOut)
def unapprove(content_id: str, store: Store = Depends(get_store)) -> ContentOut:
    """approved → pending_review — "delete and put back into queue"."""
    _transition(store, content_id, APPROVED, PENDING)
    return ContentOut.from_row(store.get(content_id))


@router.post("/content/{content_id}/retry", response_model=ContentOut)
def retry(content_id: str, store: Store = Depends(get_store)) -> ContentOut:
    _transition(store, content_id, FAILED, APPROVED)
    return ContentOut.from_row(store.get(content_id))


# --- edit / recheck ---------------------------------------------------------


@router.post("/content/{content_id}/edit", response_model=ContentOut)
def edit(
    content_id: str,
    body: EditIn,
    store: Store = Depends(get_store),
    ctx: ModerationContext = Depends(get_mod_ctx),
) -> ContentOut:
    new_text = body.text.strip()
    if not new_text:
        raise HTTPException(422, "refusing to save empty text — reject instead")
    row = _get_row(store, content_id)
    flags = _flags_for(new_text, row, ctx)
    try:
        store.update_text(content_id, new_text, flags)
    except UnknownContent:
        raise HTTPException(404, f"no content {content_id!r}")
    except NotEditable as exc:
        raise HTTPException(409, detail={"error": "not_editable", "detail": str(exc)})
    return ContentOut.from_row(store.get(content_id))


@router.post("/content/{content_id}/edit-approve", response_model=ContentOut)
def edit_approve(
    content_id: str,
    body: EditIn,
    store: Store = Depends(get_store),
    ctx: ModerationContext = Depends(get_mod_ctx),
) -> ContentOut:
    """Edit the text (re-moderated) then approve — one click for the common case."""
    edit(content_id, body, store, ctx)  # raises on its own failures
    _transition(store, content_id, PENDING, APPROVED)
    return ContentOut.from_row(store.get(content_id))


@router.post("/content/{content_id}/recheck-llm", response_model=ContentOut)
def recheck_llm(
    content_id: str,
    store: Store = Depends(get_store),
    ctx: ModerationContext = Depends(get_mod_ctx),
    llm=Depends(get_llm_moderator),
) -> ContentOut:
    row = _get_row(store, content_id)
    flags = _flags_for(row.text, row, ctx, llm=llm)
    try:
        store.update_flags(content_id, flags)
    except NotEditable as exc:
        raise HTTPException(409, detail={"error": "not_editable", "detail": str(exc)})
    return ContentOut.from_row(store.get(content_id))


# --- delete -----------------------------------------------------------------


@router.delete("/content/{content_id}", status_code=204)
def delete(content_id: str, store: Store = Depends(get_store)) -> None:
    """Hard-remove a junk queue row (not a transition; refuses publishing/published)."""
    try:
        store.delete(content_id)
    except UnknownContent:
        raise HTTPException(404, f"no content {content_id!r}")
    except StaleStatus as exc:
        raise HTTPException(409, detail={"error": "stale", "detail": str(exc)})
    except IllegalTransition as exc:
        raise HTTPException(409, detail={"error": "not_deletable", "detail": str(exc)})


# --- already-posted edit / delete (stub until poster P2) --------------------

_P2_MSG = (
    "live status {} lands with the poster's live publisher (P2). The local "
    "record is a receipt; editing/deleting the real toot needs MastodonPublisher."
)


@router.post("/content/{content_id}/edit-published", status_code=501)
def edit_published(content_id: str, body: EditIn) -> None:
    raise HTTPException(501, _P2_MSG.format("edit"))


@router.delete("/content/{content_id}/published", status_code=501)
def delete_published(content_id: str) -> None:
    raise HTTPException(501, _P2_MSG.format("delete"))
