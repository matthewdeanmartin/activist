# Core Concepts

## Human-in-the-loop queue

The queue is the center of the live system. Generated content does not bypass it.

Key statuses:

- `pending_review`
- `approved`
- `publishing`
- `published`
- `rejected`
- `failed`

The code treats legal transitions as a hardcoded map. If you need new behavior, you extend `LEGAL_TRANSITIONS` deliberately.

## Persona continuity

The bot is not stateless. It carries:

- explicit opinions
- topical knowledge
- recently said summaries
- seen-item memory
- handled-mention memory
- diary notes

That continuity is stored in plain files rather than in a database or prompt cache.

## Relevance before generation

Keyword-based topic matching happens before any engine work. This keeps the bot narrower, cheaper, and easier to reason about.

## Pacing as code

Rate limiting is enforced by scheduling code, not by moderation and not by prompt instruction. That makes spacing deterministic and testable.

## Moderation as flags

The project’s moderation model is advisory but persistent. Flags travel with the draft, appear in the UI, and can be regenerated after edits.

## Reply consent gates

The project separates:

- whether the bot may answer
- what the bot should say

The first question is answered by code in `replies.py`; the second is answered by the engine.
