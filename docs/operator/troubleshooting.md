# Troubleshooting

## `config file not found`

The CLI defaults to `activist.toml` in the current working directory. Either run from the repository root or pass `--config`.

## `persona.toml not found`

The configured `paths.persona` directory must exist and contain `persona.toml`.

## Replies are skipped due to credentials

The replies path requires all `MASTODON_ID_<NAME>_*` variables for the selected identity. Check `.env`, including the identity suffix.

## The poster refuses to run with `poster.live=true`

That is expected. The current implementation only supports `DryRunTransport`. Set `poster.live = false`.

## The UI says another process changed the row first

That is a normal compare-and-swap race result, usually caused by:

- another browser tab
- the poster claiming an approved row
- a recent status transition from another process

Refresh the page and review the item again.

## A draft has moderation errors

Errors do not automatically delete the draft. Review the flags, edit the content, re-check if needed, and then decide whether to approve or reject it.

## Feed fetches keep failing

Check:

- the feed URL
- general network access
- whether the remote server is returning non-200 responses
- whether article-body fetching is exposing a flaky article host rather than a flaky feed

The fetcher isolates failures per feed, so one broken feed should not stop the others.

## Where to inspect state

- queue and event history: `data/activist.db`
- simulated publish receipts: `data/published_dryrun.jsonl`
- seen article ids: `persona/memory/seen.jsonl`
- handled mentions: `persona/memory/mentions.jsonl`
- recent continuity memory: `persona/memory/said.jsonl`
- diary notes: `persona/memory/diary.md`
