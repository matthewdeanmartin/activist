# Codex Review Notes

Date: 2026-06-12

Scope reviewed: current working tree, with focus on the fetcher/admin/poster
implementation against `spec/real_overview.md`, `spec/fetcher_service.md`,
`spec/admin_ui.md`, and `spec/poster_service.md`.

## Executive take

The base is in good shape for a local, human-in-the-loop bot: the queue store
is centralized, status changes are compare-and-swap guarded, the governing
policy is packaged runtime input, explicit TOML rate limits drive ordinary-code
scheduling, timestamps are UTC-aware, and the live Mastodon write path is still
structurally blocked.

## Spec issues and clarifications

- `spec/real_overview.md` still shows a simplified lifecycle without the
  transient `publishing` state, while `store.py`, `admin_ui.md`, and
  `poster_service.md` use `approved -> publishing -> published/failed`.
  Update the overview diagram so future work starts from the real lifecycle.
- `spec/real_overview.md` says `MastodonReader` has `notifications`, `search`,
  and `status(id)`, while `fetcher_service.md` F3 now effectively has
  `get_status(id)` in code. Pick final method vocabulary before F3 grows.

## Base Improvement Recommendations

1. Store publish/error metadata as structured JSON. `event_log.detail` is
   convenient text, but P2 will want machine-readable HTTP class, reset time,
   receipt URL, and idempotency key.
2. Keep all live-network tests opt-in. The default suite should continue using
   fake transports and package resources.
3. Add CLI smoke tests for the real subcommands. The library tests are solid,
   but command-level defaults are where path and config drift tend to appear.
4. Consider app-policy override ergonomics later: explicit missing overrides
   now fail fast, but the CLI/help/docs should make the packaged default clear.

## Next Feature Roadmap

### Near Term: Stabilize The Shipped Phases

- Keep `uv run pytest` green by default; live-network checks should stay
  opt-in.
- Update `real_overview.md` to match the actual lifecycle.
- Add CLI smoke coverage for `activist fetch --dry-run`, `activist poster
  --skip-verify`, `activist moderate`, and `activist ui` app creation.

### Next: Fetcher F3 Replies

- Implement `MastodonReader.notifications` and `get_account` with fake
  transport tests first.
- Add mention checkpointing in `kv` with a namespaced key such as
  `mastodon:TECH:notifications:since_id`.
- Carry `visibility` through `Mention`/`DraftPost`/`ContentRow`; this is a P2
  prerequisite because replies must not widen audience.
- Record scrubbed notification fixtures for mapping and consent-gate tests.

### Then: Admin U3 Operations

- Search/filter and reschedule are the highest-value UI additions.
- Add an edit diff view before bulk actions; it supports better human review
  with low implementation risk.
- Add an ops strip with last poster tick, last error, and queue counts by
  identity.

### Then: Unattended Operation

- Add `activist status` before Windows Task Scheduler docs. It gives both the
  user and scheduled jobs a single health surface.
- Add rotating logs under `data/logs/`.
- Write Task Scheduler install/uninstall scripts after the service/tick
  contract is settled.

### Later: Live Publish P2

- Build `MastodonPublisher.post_status` against `httpx.MockTransport` only.
- Keep the triple live gate, and add a first-flight checklist with an
  unlisted, hand-approved test post.
