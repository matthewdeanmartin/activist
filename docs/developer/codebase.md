# Codebase Structure

## Top-level directories

- `src/activist/`: application code
- `tests/`: test suite
- `persona/`: editable persona identity, opinions, and memory
- `fixtures/`: offline feed and mention fixtures
- `policies/`: instance policy text files used by moderation and pacing
- `spec/`: design notes used to explain intent
- `docs/`: MkDocs source
- `out/` and `out_mock/`: generated review artifacts
- `data/`: SQLite queue and dry-run publish logs

## Important modules

### `cli.py`

Defines all supported subcommands and maps them to the live and fixture workflows.

### `config.py`

Loads `activist.toml` into an `AppConfig` dataclass and validates critical inputs.

### `pipeline.py`

Owns the core engine loop used by the fixture workflow and reused by the live fetch chain.

### `fetch.py`

Implements live feed fetching, caching, digesting, moderation, and queue insertion for top-level posts.

### `reply_fetch.py`

Implements live Mastodon mention reading, consent gates, moderation, and queue insertion for replies.

### `store.py`

Owns the SQLite schema, lifecycle rules, compare-and-swap transitions, and event logging.

### `poster.py`

Claims approved rows, enforces pacing, and publishes through the transport seam.

### `transport.py`

Defines publish transport behavior. Only dry-run transport exists today.
