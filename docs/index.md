# Activist

Activist is a human-in-the-loop Mastodon bot for opinionated advocacy. It reads news feeds and Mastodon mentions, drafts posts or replies, runs moderation checks, stores drafts in a local SQLite review queue, and lets a human decide what happens next.

The project is intentionally conservative about automation:

- it keeps persona state in reviewable files under `persona/`
- it enforces consent gates for replies in ordinary code
- it treats moderation as flagging, not auto-deletion
- it keeps live Mastodon publishing disabled in the current implementation

## Audience guide

- Read the [Design overview](design/index.md) if you are evaluating whether this project fits your goals.
- Read the [Operator docs](operator/index.md) if you want to run the system without changing its code.
- Read the [Developer docs](developer/index.md) if you expect to customize behavior, prompts, moderation, storage, or runtime flow.

## What the code does today

The current codebase implements these main runtime surfaces:

- `activist fetch`: fetches live RSS feeds, optionally reads live Mastodon mentions, drafts content, moderates it, and queues it for review
- `activist ui`: runs a local Flask review dashboard for approving, rejecting, editing, and re-checking drafts
- `activist poster`: drains approved items through a dry-run transport and records simulated publish receipts
- `activist run` and `activist replies`: fixture-based offline workflows used for local testing and development

## What is not implemented

These design elements are described in `spec/`, but are not live in the current code:

- actual Mastodon publishing
- a production daemon or service wrapper
- authentication or multi-user administration
- media upload workflows

The docs below separate implemented behavior from design intent so you can evaluate the project honestly.
