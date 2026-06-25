# Design Goals

Activist is meant to be a transparent, opinionated bot, not an engagement farm.

## Primary goals

### Human approval stays in the loop

Generated content enters a review queue before anything else happens. The human operator can inspect moderation flags, edit text, approve it, reject it, or send failed work back for another attempt.

### Transparency is mandatory

The persona includes a disclosure footer, and moderation treats missing disclosure as an error. The system is designed to present itself as a bot rather than imitating a person.

### Content is grounded in external source material

Top-level posts are reactions to articles or feed items rather than free-standing synthetic chatter. Moderation also requires a source link on non-reply posts.

### Reply behavior is consent-based

Replies are allowed only when the target explicitly summons the bot, has not opted out with `#nobot`, is not itself a bot, and has not already been handled. These gates are implemented in code before any engine is asked to draft a response.

### Moderation informs humans instead of overruling them

Moderation attaches flags. It does not silently drop content. Deterministic checks always run, and an LLM-based moderator can add more judgment when configured.

### Persona state remains reviewable

Opinions, knowledge, and memory live in plain files under `persona/`. The design treats readable diffs as part of the operating model.

### Server policy and pacing are first-class concerns

Rate limits are enforced as ordinary scheduling code rather than prompt text. Instance policies can tighten pacing, and the project is designed to stay within conservative bot behavior norms.

## Non-goals

The project is not designed for:

- high-volume coordinated posting
- fully unattended autonomous posting
- fake personal experience
- synthetic content disconnected from sources
- automatic engagement with anyone mentioning a keyword

## Live publishing is gated, not absent

A real Mastodon-posting transport (`MastodonTransport`) exists and performs the actual write. It is deliberately hard to trigger by accident: it requires `[poster].live = true` in committed config, `ACTIVIST_LIVE=1` in the environment, and `--live` on the command line, all at once. Unattended scheduling beyond `poster --loop` is not implemented.
