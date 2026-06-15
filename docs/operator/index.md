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
- Mastodon writes are not implemented

If you need actual live publishing, treat that as development work, not an operator setting.
