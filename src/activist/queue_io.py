"""Read/write the run queue file out/<date>/feed.toml.

The TOML file is the single source of truth for a run; HTML is derived.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict
from pathlib import Path

import tomli_w

from .models import DraftPost


def write_feed(path: Path, run_meta: dict, posts: list[DraftPost]) -> None:
    doc: dict = {"run": run_meta}
    if posts:
        doc["post"] = [_post_dict(p) for p in posts]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        tomli_w.dump(doc, fh, multiline_strings=True)


def read_feed(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def write_feed_doc(path: Path, doc: dict) -> None:
    """Write back a full feed document (e.g. after a moderation pass)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        tomli_w.dump(doc, fh, multiline_strings=True)


def _post_dict(post: DraftPost) -> dict:
    data = asdict(post)
    if data["opinion_change"] is None:
        del data["opinion_change"]
    # reply fields only appear on reply drafts; keep top-level posts clean
    for key in ("reply_to_id", "reply_to_author", "reply_to_text"):
        if not data[key]:
            del data[key]
    return data
