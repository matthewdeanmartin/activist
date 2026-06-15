"""Integration fixtures: run activist's write path against a real HTTP mock.

These tests boot the ``mastodon_mock`` package (published on PyPI) as a uvicorn
server on a free port and point activist's ``MastodonWriter`` /
``MastodonTransport`` at it. ``mastodon_mock`` is a *stateful* simulation — a
status POSTed shows up in the next GET of that account's timeline — so the
publish path can be proven end to end over HTTP **without ever touching a live
instance** (which is the whole reason live testing has been held back: a
misbehaving bot could get banned).

Two environment facts make this suite special:

* ``pytest.ini`` sets ``--disable-network`` (pytest-network monkeypatches
  ``socket.connect``). These tests genuinely need a loopback socket, so every
  test/fixture here depends on the ``enable_network`` fixture to restore it.
* The whole package self-skips on Python < 3.13 (mastodon_mock's
  ``requires-python``) or if ``mastodon_mock`` is not installed (install
  ``mastodon_mock[test]``).

The free-port/uvicorn/threading boilerplate this file used to hand-roll now
lives in ``mastodon_mock.testing.MockServer`` (the ``mastodon_mock[test]``
extra); we just hand it our seed under the session-scoped network re-enable.

Run just this suite::

    uv run pytest tests/integration
"""

from __future__ import annotations

import socket
import sys
from collections.abc import Iterator

import pytest

if sys.version_info < (3, 13):
    pytest.skip(
        "mastodon_mock requires Python >= 3.13; skipping mock integration suite",
        allow_module_level=True,
    )

pytest.importorskip(
    "mastodon_mock",
    reason="install mastodon_mock[test] to run these tests",
)

import httpx  # noqa: E402

from mastodon_mock.config import (  # noqa: E402
    SeedAccount,
    SeedConfig,
    SeedFollow,
    SeedStatus,
)
from mastodon_mock.testing import MockServer  # noqa: E402

from activist.mastodon_client import (  # noqa: E402
    MastodonCredentials,
    MastodonReader,
    MastodonWriter,
)
from activist.transport import MastodonTransport  # noqa: E402

# The bot's own seeded account + a human who can @-mention it (so we can post
# replies that thread onto a real inbound status).
BOT_TOKEN = "bot_token"
HUMAN_TOKEN = "human_token"

INTEGRATION_SEED = SeedConfig(
    accounts=[
        SeedAccount(username="activistbot", display_name="Activist Bot", bot=True, access_token=BOT_TOKEN),
        SeedAccount(username="human", display_name="A Human", access_token=HUMAN_TOKEN),
    ],
    follows=[SeedFollow(follower="human", following="activistbot")],
    statuses=[
        SeedStatus(account="human", text="hey @activistbot what do you think about heat pumps?"),
    ],
)


@pytest.fixture(scope="session")
def _mock_server_url(enable_network_session: None) -> Iterator[str]:
    """Session-scoped mock server backed by the integration seed.

    State accumulates across the session on purpose — that is what lets the
    write tests prove the server is stateful (post here, read it back there).
    ``MockServer`` owns the free port, readiness wait, and teardown; it runs
    under ``enable_network_session`` so its loopback sockets survive the global
    ``--disable-network``.
    """
    with MockServer(seed=INTEGRATION_SEED) as server:
        yield server.base_url


@pytest.fixture(scope="session")
def enable_network_session() -> Iterator[None]:
    """Session-scoped network re-enable for the server thread/socket setup.

    pytest-network's own ``enable_network`` is function-scoped; the server
    fixture is session-scoped, so we restore the real ``socket.connect`` for the
    whole session here and put the block back at teardown.
    """
    import pytest_network

    socket.socket.connect = pytest_network._original_connect
    try:
        yield
    finally:
        socket.socket.connect = pytest_network.patched_connect


@pytest.fixture
def mock_server_url(_mock_server_url: str, enable_network: None) -> str:
    """Per-test handle to the server URL with loopback sockets re-enabled.

    Depending on this (rather than ``_mock_server_url`` directly) means each test
    body can open HTTP connections despite the global ``--disable-network``.
    """
    return _mock_server_url


def _creds(base_url: str, token: str, identity: str = "BOT") -> MastodonCredentials:
    return MastodonCredentials(
        identity=identity,
        base_url=base_url,
        client_id="integration-client-id",
        client_secret="integration-client-secret",
        access_token=token,
    )


def _http_client(base_url: str, token: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(10.0),
    )


@pytest.fixture
def bot_writer(mock_server_url: str) -> Iterator[MastodonWriter]:
    """activist's write client, authenticated as the bot, pointed at the mock."""
    writer = MastodonWriter(_creds(mock_server_url, BOT_TOKEN), client=_http_client(mock_server_url, BOT_TOKEN))
    try:
        yield writer
    finally:
        writer.close()


@pytest.fixture
def bot_reader(mock_server_url: str) -> Iterator[MastodonReader]:
    """activist's read client (bot) — to read back what the writer posted."""
    reader = MastodonReader(_creds(mock_server_url, BOT_TOKEN), client=_http_client(mock_server_url, BOT_TOKEN))
    try:
        yield reader
    finally:
        reader.close()


@pytest.fixture
def human_writer(mock_server_url: str) -> Iterator[MastodonWriter]:
    """A second identity (the human), so tests can create inbound mentions."""
    writer = MastodonWriter(_creds(mock_server_url, HUMAN_TOKEN, "HUMAN"), client=_http_client(mock_server_url, HUMAN_TOKEN))
    try:
        yield writer
    finally:
        writer.close()


@pytest.fixture
def bot_transport(mock_server_url: str) -> Iterator[MastodonTransport]:
    """activist's live MastodonTransport, gate-bypassed and bound to the mock.

    ``require_gate=False`` is the test-only escape hatch: the triple gate exists
    to protect *real* instances, and here the writer is explicitly bound to a
    localhost mock, so there is nothing to protect against.
    """
    transport = MastodonTransport(
        writer=MastodonWriter(_creds(mock_server_url, BOT_TOKEN), client=_http_client(mock_server_url, BOT_TOKEN)),
        default_visibility="unlisted",
        require_gate=False,
    )
    try:
        yield transport
    finally:
        transport.close()
