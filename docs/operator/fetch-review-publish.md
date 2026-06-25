# Run the System

## Fetch drafts into the queue

Use the live chain:

```bash
activist fetch --config activist.toml
```

What it does:

- fetches configured RSS or Atom feeds with conditional GET caching
- deduplicates against `persona/memory/seen.jsonl`
- optionally fetches article bodies to improve summaries
- filters for relevant topics
- drafts posts through the selected engine
- runs moderation
- inserts drafts into `data/activist.db` as `pending_review`

Useful variants:

```bash
activist fetch --config activist.toml --dry-run
activist fetch --config activist.toml --replies
activist fetch --config activist.toml --only-replies
activist fetch --config activist.toml --no-replies
activist fetch --config activist.toml --engine mockbot
```

## Review the queue

Start the local UI:

```bash
activist ui --config activist.toml
```

The UI shows:

- queue lists by status
- draft details
- moderation flags
- source links and reply context
- event history

Human actions available today:

- approve
- reject, with an optional reason
- unapprove
- retry a failed item
- edit text
- run an LLM moderation re-check on editable content

Edits automatically re-run deterministic moderation.

## Simulate publishing

Run the poster:

```bash
activist poster --config activist.toml
```

Or in loop mode:

```bash
activist poster --config activist.toml --loop
```

What actually happens by default:

- the poster verifies Mastodon credentials unless `--skip-verify` is used
- it claims due `approved` rows
- it respects a pacing backstop
- it writes a simulated publish receipt to `data/published_dryrun.jsonl` via `DryRunTransport`
- it marks the row as `published`

No call is made to create a real Mastodon status unless you deliberately open the triple publish gate (`[poster].live = true` in config, `ACTIVIST_LIVE=1` in the environment, and `--live` on the command line). With all three set, the poster uses `MastodonTransport` and actually POSTs each approved row, mapping 429s to a requeue and 401/403/404/422 to a `failed` row a human can retry from the UI.

To see this real path work without touching a live account, target the local mastodon-mock server — see [Targeting mastodon-mock](../developer/mastodon-mock.md).

## Offline fixture workflows

For local experimentation without live feeds or Mastodon:

```bash
activist run
activist replies
activist moderate out/2026-06-11/feed.toml
activist render out/2026-06-11/feed.toml
```

These commands write review artifacts under `out/<date>/`.
