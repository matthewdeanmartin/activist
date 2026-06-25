# Personas

**Status:** plan, 2026-06-19. Companion doc: `bots_in_games.md`. Builds on
`real_overview.md` (`[identity].mastodon_id` already selects
`MASTODON_ID_<NAME>_*` from `.env`).

> A persona is the **durable mind**: a voice, a set of owned opinions, a memory,
> and — optionally — one game (`bots_in_games.md`) it inhabits as a temporary
> body. One persona per account. The same persona can run under *different
> engine richness per environment*: a cheap deterministic bot locally, a more
> expensive, higher-thinking bot in production.

---

## 1. Two axes that today are tangled

There are two independent things the word "persona" is being asked to carry:

1. **Identity & content** — *who* the bot is: name, handle, voice, opinions,
   knowledge, memory, game. This is the persona proper. It belongs in git and
   is the review surface.
2. **Engine profile** — *how richly* that identity is computed *in this
   environment*: which engine (mockbot vs openrouter), which model, thinking
   budget, call budget, moderation engine. This is an **environment** concern,
   not an identity concern.

The boss's requirement — "the persona for local testing might be a more
expensive bot or higher thinking config in prod" — is precisely the statement
that these two axes must be **separable**. The same identity, computed two ways.

So: **persona = identity (in git)**, selected by id. **Engine profile = config
overlay (per env)**, selected by which `activist*.toml` you point at.

## 2. The persona registry: `personas/<id>/`

Today there is a single `persona/` directory. We generalize to a registry so
multiple personas (multiple accounts) coexist, while keeping the *exact* layout
each persona already has:

```
personas/
  lowwatt/
    persona.toml          # identity + voice (today's persona.toml)
    opinions.toml
    knowledge.md
    memory/               # seen/said/mentions/diary
    game/                 # optional — see bots_in_games.md
  <next-persona>/
    persona.toml
    ...
```

`activist.toml` selects which one is active:

```toml
[identity]
persona_id  = "lowwatt"          # → personas/lowwatt/
mastodon_id = "TECH"             # → MASTODON_ID_TECH_* in .env (unchanged)
instances   = ["mastodon.social"]
```

`config.py` resolves `persona_dir = personas_root / persona_id` and validates it
exists, replacing today's `paths.persona`. **One persona is active per config /
per process.** Running two personas = two configs, two service processes, two
identities in `.env` — which is already how `mastodon_id` works, so this is the
natural extension, not a new concurrency model.

### Migration

`persona/` → `personas/lowwatt/` is a directory move plus a one-line config
change (`persona_id = "lowwatt"`). `paths.persona` is kept as a back-compat
override for one release: if `persona_id` is absent, fall back to the old
single-dir behavior so nothing breaks mid-transition.

## 3. Identity vs account vs env — the mapping

```
            persona_id ───────────▶  personas/<id>/   (WHO + WHAT: git)
  activist.toml
  [identity]  mastodon_id ─────────▶  MASTODON_ID_<NAME>_*  (.env: WHERE it posts)

  which *.toml you load ───────────▶  engine profile        (HOW richly: env)
```

- **persona_id** picks the mind (voice, opinions, game).
- **mastodon_id** picks the account it speaks through.
- **the config file you point the service at** picks the engine richness.

These are deliberately three knobs, not one. The same persona could in principle
post to a staging account in dev and a real account in prod by changing only
`mastodon_id` — without touching its opinions or voice.

## 4. Per-environment engine profile (the boss's ask)

Engine richness is **already** config, not persona (`[engine]`,
`[moderation]`, `[engine].call_budget` in `config.py`). The mechanism for
per-env difference is therefore: **a base config + a per-env overlay**, using
the `activist.mock.toml` pattern that already exists in the repo.

### Base + overlay

```
activist.toml          # base: feeds, persona_id, identity, pacing, paths
activist.mock.toml     # LOCAL overlay: cheap/deterministic engine
activist.prod.toml     # PROD overlay: expensive/high-thinking engine
```

Each env file declares which base it extends and overrides only the engine
profile keys. `config.py` gains a tiny `extends` step: load base, then
shallow-merge the overlay's tables over it.

```toml
# activist.mock.toml — local: fast, free, deterministic, fully gated
extends = "activist.toml"

[engine]
name = "mockbot"           # deterministic, no network, no cost

[moderation]
engine = "mockmod"

[poster]
live = false               # hard gate stays shut locally
min_spacing_seconds = 1    # nothing real to protect; don't wait

[game]
interval_minutes = 1       # tick fast so a dev sees experiences immediately
```

```toml
# activist.prod.toml — production: the expensive, higher-thinking bot
extends = "activist.toml"

[engine]
name  = "openrouter"
model = "..."              # the strong model
# thinking/reasoning budget lives here too (see §5)

[moderation]
engine = "openrouter"      # LLM judgment layered on MockModerator

[game]
interval_minutes = 1440    # one simulated month/day, the real cadence
```

The persona (`personas/lowwatt/`) is **identical** in both — same opinions, same
voice, same game. Only *how richly it thinks* differs. That is exactly "a more
expensive bot or higher thinking config in prod, a cheaper one for local
testing," achieved without forking the identity.

### Why overlay, not separate persona dirs

If we encoded "cheap vs expensive" into the persona directory, the two would
**drift**: a fix to lowwatt's opinions in prod wouldn't reach the dev persona.
The whole point is that local testing exercises the *same* mind the cheap way.
Identity in git (shared), engine profile in config (per-env) keeps them in sync
by construction.

## 5. The engine profile, fully enumerated

So a "profile" is a named, reviewable thing, these are the keys that constitute
"how richly this persona thinks" — all already config-shaped:

| Key | Table | Meaning |
|---|---|---|
| `engine.name` | `[engine]` | `mockbot` (free, deterministic) vs `openrouter` |
| `engine.model` | `[engine]` | which model in the openrouter rotation |
| `engine.thinking` | `[engine]` | **new:** reasoning/thinking budget hint passed to the engine (ignored by mockbot) |
| `engine.call_budget` | `[engine]` | LLM calls per run (cost throttle, exists) |
| `moderation.engine` | `[moderation]` | `mockmod` vs LLM-layered moderation |
| `poster.live` | `[poster]` | the live-publish hard gate (stays false in dev) |

`config.py` validates the profile the same way it validates everything else.
`engine.thinking` is the one genuinely new field; it's an opaque hint the
`OpenRouterBot` may use to raise reasoning effort, and mockbot ignores. It is
named in config (reviewable), never in the persona, never in prompt text the bot
writes itself.

## 6. Many personas, one codebase

Nothing about a second persona requires new code beyond the registry lookup:

- **State** is already per-directory (`seen.jsonl`, `said.jsonl`, `opinions`,
  `game/`) — give a persona its own `personas/<id>/` and its state is isolated.
- **Account** is already per-`mastodon_id` — a second persona gets its own
  `.env` credentials and posts as itself.
- **Engine profile** is already per-config — a second persona's services run off
  their own `activist.<persona>.toml`.
- **Game** is per-persona by directory (`personas/<id>/game/`) — `lowwatt` plays
  `energy_home`; another persona could play a different game, or none.

A second persona is therefore: a new `personas/<id>/` directory, a new
`MASTODON_ID_<NAME>_*` block in `.env`, and a config that names both. No new
abstractions. The registry is the only structural change; everything else the
architecture already supports one-at-a-time and now supports N.

## 7. Build order

1. **P0 — registry.** `personas/<id>/` layout, `config.py` resolves
   `persona_id` → `persona_dir`, back-compat `paths.persona` fallback, move
   `persona/` → `personas/lowwatt/`. Pure plumbing; behavior identical.
2. **P1 — config overlay.** `extends` key in `config.py`, shallow-merge of
   env overlay over base, add `activist.prod.toml`; align `activist.mock.toml`
   to the overlay form. Add `engine.thinking` validation (no-op for mockbot).
3. **P2 — second persona (proof).** Stand up one more `personas/<id>/` with its
   own opinions/voice to prove isolation end-to-end (no game required). This is
   the test that the separation actually holds.

## 8. Open questions for later

- **Shared knowledge across personas?** If two climate personas want the same
  `knowledge.md`, do we allow a shared `personas/_common/`? Deferred — start
  with full isolation; factor out only if duplication actually hurts.
- **One service, many personas?** Could a single `fetch` loop iterate all
  enabled personas instead of one process each? Possible later, but
  one-process-per-persona keeps `.env` credential isolation and failure domains
  clean for now.
