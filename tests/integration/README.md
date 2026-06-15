# Integration tests (mastodon_mock-backed)

These tests run activist's **write/publish path** against
[`mastodon_mock`](../../../mastodon_mock) — an unpublished, *stateful*
simulation of a Mastodon server — booted as a local HTTP server. **No live
Mastodon, no API keys.**

This is the safe stand-in for the live testing the project has deliberately
avoided: a misbehaving bot posting to a real instance risks a ban, so the
publish path (`MastodonWriter`, `MastodonTransport`, the full `poster_tick`)
had no test coverage. The mock closes that gap.

## What they prove

- `MastodonWriter.post_status` / `delete_status` round-trip over real HTTP:
  post → read back → delete → 404.
- The **Idempotency-Key** guarantee: re-posting with the same content id returns
  the existing status instead of duplicating it (the poster's most important
  safety property).
- Replies thread onto an inbound mention and inherit its visibility.
- `MastodonTransport` + `poster_tick` end to end: approved rows reach
  `published` with a real server id; a 4xx lands them in `failed`.
- The server **422s empty / over-length posts** (a divergence found and fixed in
  mastodon_mock — see that repo's `spec/findings_from_activist.md`).

## How it works

`conftest.py` boots `mastodon_mock` (session-scoped, in-memory, seeded with a
`bot` account and a `human` who mentions it) and hands tests writer/reader
clients pointed at it.

Two environment notes:

- `pytest.ini` sets `--disable-network` (pytest-network blocks `socket.connect`,
  including loopback). These tests need a real socket, so every fixture/test
  here depends on `enable_network` / a session-scoped re-enable.
- The `MastodonTransport` gate (config + env + flag) protects *real* instances;
  tests construct it with `require_gate=False` and a writer explicitly bound to
  the localhost mock.

## Running

```bash
uv run pytest tests/integration
# or
make test-integration
```

Self-skips on Python < 3.13 or if `mastodon_mock` is not installed (it is an
editable path dev dependency on the sibling repo; see `[tool.uv.sources]` in
`pyproject.toml`). Drop that path source for a version pin once it's published.
