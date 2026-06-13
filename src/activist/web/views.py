"""Queue routes: browse (U1) plus approve / reject / edit actions (U2).

Every status change goes through store.transition's compare-and-swap, so a
button click that races the poster (or another tab) loses politely with a
flash message instead of corrupting the lifecycle.
"""

from __future__ import annotations

from dataclasses import asdict

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from .. import state
from ..moderation import ModerationContext, moderate_post
from ..store import (
    APPROVED,
    FAILED,
    PENDING,
    PUBLISHED,
    REJECTED,
    STATUSES,
    IllegalTransition,
    NotEditable,
    StaleStatus,
    Store,
    UnknownContent,
)

bp = Blueprint("queue", __name__)

# Tab order on the dashboard; 'publishing' is transient and rare, so last.
TAB_ORDER = (PENDING, APPROVED, PUBLISHED, REJECTED, FAILED, "publishing")

# Button name -> (from_status, to_status). The store re-validates legality;
# this map just keeps URLs honest.
ACTIONS = {
    "approve": (PENDING, APPROVED),
    "reject": (PENDING, REJECTED),
    "unapprove": (APPROVED, PENDING),
    "retry": (FAILED, APPROVED),
}


def _store() -> Store:
    return current_app.config["STORE"]


def _mod_ctx() -> ModerationContext:
    """Built lazily so read-only browsing never needs persona/policy files."""
    ctx = current_app.config.get("MOD_CTX")
    if ctx is None:
        from ..moderation.policies import load_app_policy, load_instance_policy

        cfg = current_app.config["APP_CFG"]
        persona = state.load_persona(cfg.persona_dir / "persona.toml")
        ctx = ModerationContext(
            disclosure=persona.disclosure,
            app_policy=load_app_policy(cfg.app_policy),
            instance_policies={
                domain: load_instance_policy(cfg.policies_dir, domain)
                for domain in cfg.instances
            },
        )
        current_app.config["MOD_CTX"] = ctx
    return ctx


def _llm_moderator():
    moderator = current_app.config.get("LLM_MODERATOR")
    if moderator is None:
        from ..moderation.openrouter_mod import OpenRouterModerator

        cfg = current_app.config["APP_CFG"]
        moderator = OpenRouterModerator(model=cfg.model)
        current_app.config["LLM_MODERATOR"] = moderator
    return moderator


@bp.app_context_processor
def ops_strip() -> dict:
    store = _store()
    last_fetch = store.last_event("fetch")
    return {
        "counts": store.counts(),
        "tab_order": TAB_ORDER,
        "last_fetch": last_fetch,
        "app_cfg": current_app.config["APP_CFG"],
    }


@bp.get("/")
def queue_list():
    status = request.args.get("status", PENDING)
    if status not in STATUSES:
        abort(404)
    rows = _store().list_by_status(status)
    return render_template("list.html", rows=rows, status=status)


@bp.get("/content/<content_id>")
def detail(content_id: str):
    try:
        row = _store().get(content_id)
    except UnknownContent:
        abort(404)
    return render_template("detail.html", row=row, events=_store().events(content_id))


@bp.get("/published")
def published():
    rows = _store().list_by_status(PUBLISHED)
    return render_template("list.html", rows=rows, status=PUBLISHED)


@bp.post("/content/<content_id>/act/<action>")
def act(content_id: str, action: str):
    pair = ACTIONS.get(action)
    if pair is None:
        abort(404)
    detail_text = request.form.get("reason", "").strip()
    try:
        _store().transition(content_id, pair[0], pair[1], actor="human", detail=detail_text)
        flash(f"{action}: {content_id} → {pair[1].replace('_', ' ')}")
    except UnknownContent:
        abort(404)
    except StaleStatus as exc:
        flash(f"Nothing changed — another process got there first ({exc}).", "error")
    except IllegalTransition:
        abort(409)
    return redirect(request.form.get("next") or url_for("queue.detail", content_id=content_id))


@bp.post("/content/<content_id>/edit")
def edit(content_id: str):
    new_text = request.form.get("text", "").strip()
    if not new_text:
        flash("Refusing to save empty text — reject the post instead.", "error")
        return redirect(url_for("queue.detail", content_id=content_id))
    store = _store()
    try:
        row = store.get(content_id)
    except UnknownContent:
        abort(404)
    # Every edit re-runs the deterministic moderator: a human can introduce a
    # violation as easily as fix one (drop the footer, add a reply link).
    flags = moderate_post(
        {
            "text": new_text,
            "char_count": len(new_text),
            "reply_to_id": row.in_reply_to_status_id,
        },
        _mod_ctx(),
    )
    try:
        store.update_text(content_id, new_text, [asdict(f) for f in flags])
        flash(f"saved ({len(new_text)} chars, {len(flags)} flags)")
    except NotEditable as exc:
        flash(f"Not editable — {exc}.", "error")
    return redirect(url_for("queue.detail", content_id=content_id))


@bp.post("/content/<content_id>/recheck-llm")
def recheck_llm(content_id: str):
    store = _store()
    try:
        row = store.get(content_id)
    except UnknownContent:
        abort(404)
    flags = moderate_post(
        {
            "text": row.text,
            "char_count": row.char_count,
            "reply_to_id": row.in_reply_to_status_id,
        },
        _mod_ctx(),
        llm_moderator=_llm_moderator(),
    )
    try:
        store.update_flags(content_id, [asdict(f) for f in flags])
        flash(f"LLM re-check complete ({len(flags)} flags)")
    except NotEditable as exc:
        flash(f"Not re-checkable — {exc}.", "error")
    return redirect(url_for("queue.detail", content_id=content_id))
