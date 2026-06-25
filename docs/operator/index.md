# Operator Overview

These docs are for someone running Activist as configured, without modifying application code.

Your job as an operator is to:

- provide configuration and secrets
- run fetch and review workflows
- inspect moderation flags
- approve, reject, or edit drafts
- monitor the queue and dry-run publish log

The current implementation is local-first:

- queue state is stored in `data/activist.db`
- the review UI runs on localhost
- Mastodon reads are live when credentials are configured
- Mastodon writes default to a dry-run log (`data/published_dryrun.jsonl`); real publishing exists but is gated behind `[poster].live = true`, `ACTIVIST_LIVE=1`, and `--live` all together

Treat flipping the live gate for a real account as a deliberate, reviewed decision, not a routine operator setting. If you want to see the real publish path work without any risk to a live account, see [Targeting mastodon-mock](../developer/mastodon-mock.md), which points the same triple-gated transport at a disposable local server.
