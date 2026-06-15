"""Poster (Phase P1): drain the approved queue on schedule, via a Transport.

The claim protocol: a row is published only after winning the
approved→publishing compare-and-swap, so a human un-approving or editing in
the UI at the same moment can never have their row published out from under
them — one side loses the race politely.

The pacing backstop: slots are spaced when drafts are created, but slots can
be hand-edited and backlogs pile up while the poster is down. Whatever the
queue says, this loop never publishes two items closer together than the
effective per-identity spacing (ordinary code, as always — the strictest of
the persona's posts_per_hour and the target instances' policies).
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import ratelimit, state
from .config import AppConfig
from .store import APPROVED, FAILED, PUBLISHING, StaleStatus, Store
from .transport import RetryablePublishError, Transport

LOGGER = logging.getLogger(__name__)


@dataclass
class TickResult:
    due: int = 0
    published: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped_race: int = 0
    deferred_pacing: int = 0
    requeued: list[str] = field(default_factory=list)


def effective_per_hour(cfg: AppConfig) -> int:
    from .moderation.policies import load_instance_policy

    persona = state.load_persona(cfg.persona_dir / "persona.toml")
    app_limit = cfg.rate_limit_posts_per_hour or persona.posts_per_hour
    instance_policies = {
        domain: load_instance_policy(cfg.policies_dir, domain)
        for domain in cfg.instances
        if domain not in cfg.instance_rate_limits
    }
    return ratelimit.effective_hourly_limit(
        app_limit, instance_policies, cfg.instance_rate_limits
    )


def poster_tick(
    cfg: AppConfig,
    store: Store,
    transport: Transport,
    now: dt.datetime | None = None,
    per_hour: int | None = None,
) -> TickResult:
    """One pass over the due queue. Safe to run from overlapping schedulers —
    the claim CAS and the pacing backstop both hold per-row."""
    now = ratelimit.aware_utc(now or dt.datetime.now(dt.UTC))
    if per_hour is None:
        per_hour = effective_per_hour(cfg)
    spacing = dt.timedelta(minutes=max(1, 60 // max(1, per_hour)))
    identity = cfg.mastodon_id

    result = TickResult()
    due = store.due_approved(identity, now.isoformat(timespec="seconds"))
    result.due = len(due)
    last_pub = store.last_published_at(identity)

    for index, row in enumerate(due):
        if last_pub and now - ratelimit.aware_utc(dt.datetime.fromisoformat(last_pub)) < spacing:
            # Backstop wins over the queue: the rest of the backlog waits for
            # later ticks no matter what their slots claim.
            result.deferred_pacing = len(due) - index
            LOGGER.info(
                "pacing backstop: last publish %s, spacing %s — deferring %d due row(s)",
                last_pub,
                spacing,
                result.deferred_pacing,
            )
            break
        try:
            store.transition(row.id, APPROVED, PUBLISHING, actor="poster", detail=transport.name)
        except StaleStatus:
            result.skipped_race += 1
            LOGGER.info("lost claim race for %s; skipping", row.id)
            continue
        try:
            receipt = transport.publish(row)
        except RetryablePublishError as exc:
            # Transient (e.g. 429): release the claim back to approved and let a
            # later tick try again — don't burn the row to failed. The
            # idempotency key means a retry can't double-post even if this one
            # actually landed server-side.
            store.transition(
                row.id, PUBLISHING, APPROVED, actor="poster",
                detail=f"requeue after {exc.retry_after:.0f}s: {exc}",
            )
            result.requeued.append(row.id)
            LOGGER.info("publish re-queued for %s (retry_after=%.0fs): %s", row.id, exc.retry_after, exc)
            # Stop the tick: if we're being rate-limited, the rest of the backlog
            # would only pile up more 429s.
            break
        except Exception as exc:  # any transport failure → failed, human retries via UI
            store.transition(row.id, PUBLISHING, FAILED, actor="poster", detail=str(exc))
            result.failed.append(row.id)
            LOGGER.warning("publish failed for %s: %s", row.id, exc)
            continue
        store.mark_published(row.id, receipt.status_id, receipt.published_at, receipt.url)
        result.published.append(row.id)
        last_pub = receipt.published_at
        LOGGER.info("published %s as %s", row.id, receipt.status_id)

    if result.published or result.failed or result.requeued:
        store.log_event(
            "-",
            "poster",
            "poster-tick",
            f"{len(result.published)} published, {len(result.failed)} failed, "
            f"{len(result.requeued)} requeued, {result.deferred_pacing} deferred ({transport.name})",
        )
    return result


class PosterLock:
    """data/poster.lock — two posters on one queue is how double-posts happen."""

    def __init__(self, path: Path):
        self.path = path
        self._held = False

    def __enter__(self) -> PosterLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open("x", encoding="utf-8") as fh:
                fh.write(dt.datetime.now().isoformat(timespec="seconds"))
        except FileExistsError:
            raise RuntimeError(
                f"another poster appears to be running (lockfile {self.path} exists; "
                "delete it if that's wrong)"
            ) from None
        self._held = True
        return self

    def __exit__(self, *exc_info) -> None:
        if self._held:
            self.path.unlink(missing_ok=True)
            self._held = False


def poster_loop(cfg: AppConfig, store: Store, transport: Transport) -> None:
    """--loop mode: tick, sleep, repeat until Ctrl-C."""
    interval = cfg.poster_check_interval_minutes * 60
    LOGGER.info("poster loop: every %d min, transport=%s", interval // 60, transport.name)
    try:
        while True:
            tick = poster_tick(cfg, store, transport)
            if tick.published or tick.failed:
                LOGGER.info(
                    "tick: %d published, %d failed, %d deferred",
                    len(tick.published),
                    len(tick.failed),
                    tick.deferred_pacing,
                )
            time.sleep(interval)
    except KeyboardInterrupt:
        LOGGER.info("poster loop stopped")
