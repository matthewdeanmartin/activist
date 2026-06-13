"""The publish seam (poster Phase P1) — same trick as the engine seam.

DryRunTransport is the only working transport this phase: "publishing" means
appending the would-be toot to data/published_dryrun.jsonl. MastodonTransport
is a stub that refuses to exist until Phase P2 opens the live gate, so no
code path can post to Mastodon by accident.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .store import ContentRow


@dataclass
class PublishReceipt:
    status_id: str  # real Mastodon id, or "dryrun-<hex>"
    url: str  # status URL, or a pointer to the dry-run log
    published_at: str


class Transport(Protocol):
    @property
    def name(self) -> str: ...

    def publish(self, row: ContentRow) -> PublishReceipt: ...


class DryRunTransport:
    name = "dryrun"

    def __init__(self, log_path: Path):
        self.log_path = log_path

    def publish(self, row: ContentRow) -> PublishReceipt:
        now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        receipt = PublishReceipt(
            status_id=f"dryrun-{uuid.uuid4().hex[:12]}",
            url=self.log_path.as_uri(),
            published_at=now,
        )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "published_at": now,
                        "status_id": receipt.status_id,
                        "content_id": row.id,
                        "kind": row.kind,
                        "identity": row.identity,
                        "scheduled_for": row.scheduled_for,
                        "in_reply_to_status_id": row.in_reply_to_status_id,
                        "text": row.text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        return receipt


class MastodonTransport:
    """Phase P2. Constructing it is the error — see spec/poster_service.md
    for the triple gate (config + env + flag) that has to open first."""

    name = "mastodon"

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "Live Mastodon publishing is Phase P2 and gated; the poster runs "
            "with DryRunTransport until the gate opens."
        )
