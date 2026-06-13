"""Thin httpx wrapper for the Mastodon API, split by capability.

MastodonReader is everything this project is allowed to do today:
read-only calls. Publishing lives in transport.MastodonTransport, which is
gated and unimplemented until poster Phase P2 — the split makes "cannot
post" a structural guarantee, not a flag check.

Credentials come from .env as MASTODON_ID_<NAME>_<FIELD> (the identities
defined there, e.g. TECH and DMV); python-dotenv handles the ``export``
prefixes the file uses.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

import httpx

from . import __version__
from .ingest import strip_html
from .models import Mention

LOGGER = logging.getLogger(__name__)

USER_AGENT = f"activist/{__version__} (+https://github.com/matthewdeanmartin/activist)"
TIMEOUT = httpx.Timeout(20.0)

# When the instance says this few requests remain in the window, pause until it
# resets rather than spending the last calls and getting a hard 429.
RATE_LIMIT_FLOOR = 2

_FIELDS = ("BASE_URL", "CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN")


class CredentialsError(ValueError):
    """Identity is missing one or more MASTODON_ID_* variables."""


@dataclass
class MastodonCredentials:
    identity: str
    base_url: str
    client_id: str
    client_secret: str
    access_token: str

    @classmethod
    def from_env(cls, identity: str) -> MastodonCredentials:
        from dotenv import load_dotenv

        load_dotenv()
        identity = identity.upper()
        values: dict[str, str] = {}
        missing: list[str] = []
        for field in _FIELDS:
            name = f"MASTODON_ID_{identity}_{field}"
            value = os.environ.get(name, "").strip()
            if not value:
                missing.append(name)
            values[field.lower()] = value
        if missing:
            raise CredentialsError(
                f"identity {identity!r} is missing {', '.join(missing)} "
                "(set them in .env; see the MASTODON_ID_* pattern there)"
            )
        return cls(
            identity=identity,
            base_url=values["base_url"].rstrip("/"),
            client_id=values["client_id"],
            client_secret=values["client_secret"],
            access_token=values["access_token"],
        )


class MastodonReader:
    """Read-only Mastodon API access — all this round is allowed to need."""

    def __init__(self, creds: MastodonCredentials, client: httpx.Client | None = None):
        self.creds = creds
        self._client = client or httpx.Client(
            base_url=creds.base_url,
            headers={
                "User-Agent": USER_AGENT,
                "Authorization": f"Bearer {creds.access_token}",
            },
            timeout=TIMEOUT,
        )

    def close(self) -> None:
        self._client.close()

    def verify_credentials(self) -> dict:
        """GET /api/v1/accounts/verify_credentials — the startup self-check.

        Returns the account document; raises httpx.HTTPStatusError on a bad
        or revoked token so callers fail fast before touching the queue.
        """
        response = self._client.get("/api/v1/accounts/verify_credentials")
        response.raise_for_status()
        return response.json()

    def get_status(self, status_id: str) -> dict:
        """GET /api/v1/statuses/:id."""
        response = self._client.get(f"/api/v1/statuses/{status_id}")
        response.raise_for_status()
        return response.json()

    def get_account(self, account_id: str) -> dict:
        """GET /api/v1/accounts/:id."""
        response = self._client.get(f"/api/v1/accounts/{account_id}")
        response.raise_for_status()
        return response.json()

    def notifications(
        self,
        types: list[str] | None = None,
        since_id: str | None = None,
        limit: int = 30,
    ) -> list[dict]:
        """GET /api/v1/notifications, newest first.

        ``types`` filters server-side (e.g. ``["mention"]``); ``since_id`` is
        the checkpoint — only notifications newer than it come back, so reruns
        don't re-process. Honors the instance's ``X-RateLimit-*`` headers: if
        the window is nearly spent it sleeps until reset before returning.
        """
        params: list[tuple[str, str]] = [("limit", str(limit))]
        for kind in types or []:
            params.append(("types[]", kind))
        if since_id:
            params.append(("since_id", since_id))
        response = self._client.get("/api/v1/notifications", params=params)
        response.raise_for_status()
        self._respect_rate_limit(response)
        return response.json()

    @staticmethod
    def _respect_rate_limit(response: httpx.Response) -> None:
        """Sleep until X-RateLimit-Reset when the remaining budget is near zero.

        Read-only by construction, but politeness still matters: blowing
        through an instance's rate limit is how a bot gets the whole project
        blocked. We never *stop* the run here — just pace it.
        """
        remaining_raw = response.headers.get("X-RateLimit-Remaining")
        reset_raw = response.headers.get("X-RateLimit-Reset")
        if remaining_raw is None or reset_raw is None:
            return
        try:
            remaining = int(remaining_raw)
        except ValueError:
            return
        if remaining > RATE_LIMIT_FLOOR:
            return
        delay = _seconds_until(reset_raw)
        if delay <= 0:
            return
        LOGGER.warning(
            "rate limit near zero (%s remaining); sleeping %.0fs until %s",
            remaining,
            delay,
            reset_raw,
        )
        time.sleep(delay)


def _seconds_until(reset: str) -> float:
    """Seconds from now until an ISO-8601 X-RateLimit-Reset timestamp (clamped)."""
    import datetime as dt

    try:
        when = dt.datetime.fromisoformat(reset.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    delta = (when - dt.datetime.now(dt.UTC)).total_seconds()
    # Cap so a bogus far-future reset can't wedge the process for hours.
    return max(0.0, min(delta, 900.0))


def _strip_status_html(html: str) -> str:
    """Strip a status body to plain text, healing the ``@ handle`` artifact.

    Mastodon wraps usernames as ``@<span>lowwatt</span>``; the generic bs4
    strip inserts a separator and yields ``@ lowwatt``, which would defeat the
    consent gate's literal ``@handle`` match. Re-join ``@`` to the word after
    it (and ``#`` for hashtags, same shape) so the gate sees what a human typed.
    """
    import re

    text = strip_html(html)
    return re.sub(r"([@#])\s+(\w)", r"\1\2", text)


def notification_to_mention(notification: dict) -> Mention:
    """Map a Mastodon mention notification to the engine's Mention dataclass.

    The notification id is the checkpoint key (``Mention.id``); the *status*
    id and visibility are carried separately so the poster can thread the
    reply onto the right toot without widening its audience. Status text and
    the author's bio are HTML-stripped — the consent gates (#nobot, @-summon)
    run on plain text.
    """
    account = notification.get("account") or {}
    status = notification.get("status") or {}
    handle = account.get("acct", "")
    author = f"@{handle}" if handle and not handle.startswith("@") else handle
    return Mention(
        id=str(notification.get("id", "")),
        author=author,
        text=_strip_status_html(status.get("content", "")),
        author_bio=strip_html(account.get("note", "")),
        author_is_bot=bool(account.get("bot", False)),
        created=status.get("created_at", notification.get("created_at", "")),
        status_id=str(status.get("id", "")),
        visibility=status.get("visibility", ""),
    )
