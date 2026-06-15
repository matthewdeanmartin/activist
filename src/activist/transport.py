"""The publish seam — same trick as the engine seam.

DryRunTransport "publishes" by appending the would-be toot to
data/published_dryrun.jsonl. MastodonTransport (Phase P2) performs the real
POST, but its constructor refuses to run unless the triple gate (config + env +
flag) has opened, so no code path can post to a live instance by accident.

The integration suite points MastodonTransport at the local mastodon_mock
server (``require_gate=False``), which is the whole reason the write path can be
proven without ever touching a real account.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from .mastodon_client import (
    MastodonCredentials,
    MastodonRateLimited,
    MastodonWriter,
)
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


class PublishGateError(RuntimeError):
    """The live gate is not fully open; constructing a live transport is refused."""


class RetryablePublishError(Exception):
    """A transient failure (e.g. 429) — the row should go back to ``approved``.

    ``retry_after`` is a best-effort seconds-to-wait hint for the next tick.
    Distinct from a plain ``Exception`` so the poster can re-queue instead of
    burning the row to ``failed`` (spec/poster_service.md P2 error taxonomy).
    """

    def __init__(self, retry_after: float, message: str = "publish retryable"):
        super().__init__(message)
        self.retry_after = retry_after


# 4xx classes that mean "this will never succeed; stop the loop" rather than
# "try again later" — bad/revoked token, suspended account, validation failure.
FATAL_STATUS_CODES = frozenset({401, 403, 404, 422})


class MastodonTransport:
    """Phase P2 live publisher. POSTs each approved row to Mastodon.

    The triple gate (spec/poster_service.md): ``[poster].live = true`` in the
    committed config, ``ACTIVIST_LIVE=1`` in the environment, and the caller
    passing ``--live`` (reflected here as ``live_flag``). All three are required
    before this will construct against a live instance — three separate mistakes
    to "accidentally go live."

    Tests pass ``require_gate=False`` together with an explicit ``writer`` bound
    to the local mock server, so the gate guards real instances only.
    """

    name = "mastodon"

    def __init__(
        self,
        creds: MastodonCredentials | None = None,
        *,
        default_visibility: str = "public",
        live_flag: bool = False,
        config_live: bool = False,
        require_gate: bool = True,
        writer: MastodonWriter | None = None,
        client: httpx.Client | None = None,
    ):
        if require_gate:
            env_live = os.environ.get("ACTIVIST_LIVE") == "1"
            if not (config_live and env_live and live_flag):
                raise PublishGateError(
                    "live publishing is gated: needs [poster].live=true "
                    f"(got {config_live}), ACTIVIST_LIVE=1 (got {env_live}), and "
                    f"--live (got {live_flag}). Refusing to build a live transport."
                )
        if writer is None:
            if creds is None:
                raise ValueError("MastodonTransport needs creds or an explicit writer")
            writer = MastodonWriter(creds, client=client)
        self._writer = writer
        self.default_visibility = default_visibility

    def close(self) -> None:
        self._writer.close()

    def publish(self, row: ContentRow) -> PublishReceipt:
        """POST one row, mapping Mastodon's response onto the poster's contract.

        * 429 → ``RetryablePublishError`` (poster re-queues to ``approved``).
        * 401/403/404/422 → ``Exception`` (poster marks ``failed`` and stops).
        * 5xx/network → ``Exception`` after the writer's own single retry budget;
          the poster marks ``failed`` and a human retries via the UI.

        The idempotency key is the content id, so retrying a row that actually
        landed server-side returns the same status instead of duplicating it.
        """
        visibility = row.visibility or self.default_visibility
        try:
            result = self._writer.post_status(
                row.text,
                idempotency_key=row.id,
                in_reply_to_id=row.in_reply_to_status_id,
                visibility=visibility,
            )
        except MastodonRateLimited as exc:
            raise RetryablePublishError(exc.retry_after, "rate limited; re-queueing") from exc
        except httpx.HTTPStatusError as exc:
            # Re-raise with a tidy message; poster_tick records it on the failed row.
            code = exc.response.status_code
            raise RuntimeError(f"publish failed HTTP {code}: {exc.response.text[:200]}") from exc

        return PublishReceipt(
            status_id=result.status_id,
            url=result.url,
            published_at=result.created_at or dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        )
