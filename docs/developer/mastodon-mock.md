# Targeting mastodon-mock

`MastodonTransport` can publish for real — it POSTs a status, gets back a real id and URL, handles 429/401/403 like a real client would. But pointing that at a real account for development is risky and noisy. `mastodon_mock` (a separate PyPI package, declared as `mastodon_mock[test]` under `[dependency-groups]` in `pyproject.toml`) runs a disposable local server with the same API shape, so the entire publish path — credentials, the triple gate, the actual HTTP write, idempotency, rate-limit handling — can be exercised without ever touching a live instance.

This page covers both ways the mock is used: the `pytest` integration suite, and the `MakefileMock` manual demo loop.

## Why a mock server instead of fakes

Unit tests fake the transport directly. The integration suite instead boots a real server process and a real `httpx` client against it, because the things worth proving — does the idempotency key actually prevent a double post on retry, does a 429 actually get mapped to `RetryablePublishError`, does the claimed status id round-trip — only mean something if a real HTTP round trip happened.

## Integration tests (`tests/integration/`)

`tests/integration/conftest.py` defines a session-scoped fixture that boots `mastodon_mock` as a `uvicorn` server on a free local port, seeded with two accounts:

- `activistbot` (the bot account, with a `bot_token`)
- `human` (a human-ish account, with a `human_token`)

Key fixtures exposed to tests:

- `mock_server_url` — the base URL of the running mock
- `bot_writer` / `bot_reader` — `MastodonWriter`/`MastodonReader` bound to the bot's token
- `human_writer` — a writer bound to the human account, used to seed mentions/replies
- `bot_transport` — a `MastodonTransport` constructed with `require_gate=False` and an explicit `writer`, so the triple gate is bypassed deliberately for the test only

`require_gate=False` is a test-only escape hatch. It exists so the gate that protects real Mastodon accounts doesn't also block proving the write path works — the only thing on the other end of that transport in tests is the local, ephemeral mock.

Relevant test files:

- `tests/integration/test_poster_against_mock.py` — runs a full poster tick against the mock, publishes, reads the status back via the API, and checks idempotency (retrying a row that already landed doesn't double-post)
- `tests/integration/test_write_roundtrip.py` — posts something and reads it back

The integration suite requires Python ≥ 3.13 and the `mastodon_mock[test]` extra; it self-skips if those aren't available, so the rest of the suite still runs on older interpreters.

Run just the integration suite:

```bash
uv run pytest tests/integration/
```

## Manual demo: `MakefileMock`

For exploring the real publish path by hand — fetching live feeds, reviewing drafts, and actually publishing them to something you can open in a browser — use `MakefileMock` (or its thin wrapper, `mock.sh`). This is a parallel set of targets to a (separate, dry-run-oriented) Makefile, scoped entirely to mock-mode files so it never touches the data your real `activist.toml` run would use.

### What's different about mock mode

| | Real / dry-run config | Mock config |
|---|---|---|
| Config file | `activist.toml` | `activist.mock.toml` |
| `identity.mastodon_id` | e.g. `TECH` | `MOCK` |
| `[poster].live` | `false` | `true` (safe — destination is local only) |
| Data paths | `data/` | `data/mock/` |
| Persona dir | `persona/` | `data/mock/persona` (a scratch copy) |

`activist.mock.toml` (repo root) is the config overlay for this: same shape as `activist.toml`, but `identity.mastodon_id = "MOCK"` selects `MASTODON_ID_MOCK_*` from `.env`, whose `BASE_URL` points at the mock server instead of a real instance. `.mastodon_mock.toml` is a different file — it's the *seed* config consumed by the `mastodon_mock` server itself (accounts, follows, a seeded mention), not by `activist`.

### .env setup

You need a `MASTODON_ID_MOCK_*` block in `.env` matching the seed in `.mastodon_mock.toml`:

```
MASTODON_ID_MOCK_BASE_URL=http://127.0.0.1:3000
MASTODON_ID_MOCK_CLIENT_ID=mock_client_id
MASTODON_ID_MOCK_CLIENT_SECRET=mock_client_secret
MASTODON_ID_MOCK_ACCESS_TOKEN=mock_bot_token
```

`mock_bot_token` must match the `access_token` seeded for the `lowwatt` account in `.mastodon_mock.toml`. `make -f MakefileMock preflight` checks for `MASTODON_ID_MOCK_BASE_URL` and fails fast with a clear message if it's missing.

You also still need `OPENROUTER_API_KEY` in `.env` — `activist.mock.toml` uses the real `openrouter` engine (not `mockbot`) against live RSS content, so the demo produces genuine drafts. `[engine].call_budget = 25` caps how many LLM calls one fetch can burn.

### Commands

```bash
# start the mock server in the background (logs to data/mock/server.log)
make -f MakefileMock up

# check it's listening and reachable
make -f MakefileMock status

# pull live feeds into the mock-mode review queue
make -f MakefileMock fetch

# review in the dashboard, on its own port (8766) so it doesn't collide with a real run
make -f MakefileMock ui

# publish one tick FOR REAL to the mock (sets ACTIVIST_LIVE=1 and --live for you)
make -f MakefileMock poster

# stop the mock server
make -f MakefileMock down
```

Or run the whole thing in one shot — boot the mock, fetch real feeds, auto-approve everything (skipping the review UI), and actually publish:

```bash
make -f MakefileMock demo
```

Then open `http://127.0.0.1:3000/_ui/` to see the posts that actually landed on the mock server.

`mock.sh` is equivalent shorthand: `./mock.sh up`, `./mock.sh fetch`, etc.

### Why `poster.live = true` is safe here

`activist.mock.toml` sets `[poster].live = true` permanently, and `MakefileMock`'s `poster`/`demo` targets export `ACTIVIST_LIVE=1` and pass `--live`, fully opening the triple gate every time. That's fine specifically because the only thing on the other end is `MASTODON_ID_MOCK_BASE_URL` — a local, ephemeral `mastodon_mock` instance that gets wiped by `make -f MakefileMock clean`. The gate exists to protect real accounts; pointed at the mock, "live" is exactly as safe as dry-run.

### Cleaning up

```bash
make -f MakefileMock clean   # stops the server, wipes data/mock/ and the mock's db
```
