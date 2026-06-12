"""Read-only routes: queue list, content detail, published archive."""

from __future__ import annotations

from flask import Blueprint, abort, current_app, render_template, request

from ..store import PENDING, PUBLISHED, STATUSES, Store, UnknownContent

bp = Blueprint("queue", __name__)

# Tab order on the dashboard; 'publishing' is transient and rare, so last.
TAB_ORDER = (PENDING, "approved", PUBLISHED, "rejected", "failed", "publishing")


def _store() -> Store:
    return current_app.config["STORE"]


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
