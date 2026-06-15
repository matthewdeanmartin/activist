# Implemented Architecture

The implemented system has three local entry points sharing one Python package, one config file, one queue store, and one persona directory.

```text
RSS/Atom feeds ---> fetch chain ----\
                                     \
Mastodon mentions --> reply chain ----> SQLite queue ---> local Flask UI ---> dry-run poster log
                                           |
                                           -> persona/ memory and opinions
```

## Main components

### Configuration

`activist.toml` holds human-reviewed settings such as selected identity, feeds, intervals, UI host and port, and file locations. Secrets stay in `.env` as `MASTODON_ID_<NAME>_*`.

### Persona state

The `persona/` directory is the identity layer:

- `persona.toml`: account identity, disclosure, tone, and limits
- `opinions.toml`: positions the bot can reinforce, defend, or revise
- `knowledge.md`: background context sliced by topic
- `memory/*.jsonl` and `memory/diary.md`: seen items, prior statements, handled mentions, and diary notes

### Queue store

`data/activist.db` is the content lifecycle store. It holds drafts, flags, approval state, event history, scheduling fields, and publish receipts.

The legal lifecycle implemented in `src/activist/store.py` is:

```text
pending_review -> approved -> publishing -> published
       |              |            |
       v              v            v
    rejected   pending_review    failed
```

There is also a `failed -> approved` retry path and a `publishing -> approved` release path for backoff support.

### Engines

The drafting seam is defined by the `PersonaEngine` protocol:

- `MockBot`: deterministic, no network, heavily used by tests
- `OpenRouterBot`: real LLM-backed drafting through OpenRouter

Both engines feed the same downstream rules: relevance filtering, scheduling, moderation, and queue insertion.

### Moderation

Moderation has two layers:

- `MockModerator`: deterministic checks such as char limit, disclosure, source-link requirements, invented links in replies, banned hashtags, and human-experience claims
- `OpenRouterModerator`: optional extra judgment layered on top

Flags are attached to content and re-run when a human edits text in the UI.

### Review UI

The local Flask app reads and updates the queue. It exposes:

- status-filtered queue lists
- item detail pages with moderation flags and event log
- approve, reject, unapprove, and retry actions
- text editing with immediate deterministic re-moderation
- optional LLM re-check for an edited item

### Poster

The poster claims approved rows, applies a pacing backstop, and writes simulated publish receipts through `DryRunTransport`. Live Mastodon posting is not implemented.

## Concurrency model

The store is shared across fetcher, UI, and poster. Status changes use compare-and-swap logic so a row can only move if it is still in the expected state. This is the main mechanism that prevents races such as editing a row while the poster tries to claim it.
