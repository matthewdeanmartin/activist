# State, Errors, Observability, Testing

## State surfaces

The project uses three main state surfaces:

- `persona/`: versionable identity and memory state
- `data/activist.db`: queue lifecycle and event log
- `out/`: rendered debug artifacts and fixture outputs

## Error handling style

The code generally prefers:

- explicit typed exceptions for queue lifecycle problems
- degraded behavior for malformed feeds and partial network failures
- fail-fast behavior for bad config or bad credentials when continuing would be misleading

Examples:

- malformed feeds return no items rather than crashing the run
- a single dead feed does not stop the other feeds
- illegal lifecycle transitions raise `IllegalTransition`
- compare-and-swap races raise `StaleStatus`
- bad Mastodon identity config raises `CredentialsError`

## Observability

Today’s observability is lightweight:

- CLI summaries printed to stdout
- Python logging in fetch, poster, and engine code
- queue `event_log` in SQLite
- HTML review artifacts under `out/`
- dry-run publish receipts in JSONL

There is no full metrics or tracing stack in the current code.

## Tests

The repository has a broad pytest suite covering:

- config loading
- feed parsing and fetching
- reply gates
- store transitions
- rendering
- moderation
- poster behavior
- OpenRouter model selection logic
- end-to-end flows

The test strategy relies heavily on:

- fixture files
- deterministic `MockBot` behavior
- fake transports
- no live network dependency
