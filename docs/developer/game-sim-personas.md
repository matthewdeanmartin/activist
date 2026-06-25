# Game Sim Personas

**Status: design, not implemented.** This page summarizes `spec/personas.md` and `spec/bots_in_games.md` for contributors who want to understand where the project is headed before code lands. Nothing described here exists in `src/activist/` yet — there is no `personas/` registry, no `game/` package, no `activist game` subcommand. Today there is a single `persona/` directory and one source of content: live RSS via `react_to_items`.

If you're looking for what the code does *today*, see [Core Concepts](core-concepts.md) and [Codebase Structure](codebase.md) instead.

## The problem these specs solve

Two separate gaps in the current single-persona, news-only design:

1. **Only one persona, one engine richness.** Today `persona/` is a single directory and `[engine]`/`[moderation]` are single config blocks. Running a second bot identity, or running the same bot cheaply in dev and expensively in prod, isn't cleanly supported.
2. **Only one source of things to say.** The bot can only react to inbound news. It can't originate first-party content, which both narrows what it has to say and edges toward "just comments on other people's articles" territory.

`personas.md` addresses (1); `bots_in_games.md` addresses (2). They're designed to compose.

## Personas: separating identity from engine richness

The core insight in `spec/personas.md`: "persona" today conflates two independent things:

- **Identity** — voice, opinions, knowledge, memory, optional game. This is *who* the bot is. It belongs in git as the review surface.
- **Engine profile** — which engine (`mockbot` vs `openrouter`), which model, thinking budget, call budget, moderation engine. This is *how richly* that identity gets computed, and it's an environment concern, not an identity concern.

The proposed split:

```
personas/<id>/          # identity, in git — same shape as today's persona/
  persona.toml
  opinions.toml
  knowledge.md
  memory/
  game/                  # optional, see below

activist.toml            # base config: persona_id, identity, feeds, pacing
activist.mock.toml        # env overlay: cheap/deterministic engine profile
activist.prod.toml        # env overlay: expensive/high-thinking engine profile
```

`[identity].persona_id` picks which `personas/<id>/` directory is active; `[identity].mastodon_id` (already implemented) picks which `.env` credentials it posts through; which config file you load picks the engine richness. Three independent knobs — the same persona can run as a cheap deterministic bot locally and a high-thinking LLM bot in prod without forking its opinions or voice, because the overlay only ever touches `[engine]`/`[moderation]`/`[poster]` keys, never the persona directory.

This is a generalization of a pattern that's already live: `activist.mock.toml` (see [Targeting mastodon-mock](mastodon-mock.md)) already overrides engine/poster settings over a notional base. The spec's `extends` mechanism would make that overlay relationship explicit and shared across more env files instead of one-off duplication.

Planned build order: registry plumbing first (directory move, config resolution, with a back-compat fallback to the old single `persona/` if `persona_id` is absent), then the config-overlay `extends` mechanism, then standing up a second persona to prove isolation actually holds end-to-end.

## Games: a first-party source of experience

`spec/bots_in_games.md` proposes giving a persona a second source of content beyond reacting to news: a **game**, a small simulated world the persona "lives in" so it generates its own first-party experiences to post about. The concrete example for the `lowwatt` persona: a simulated home with a budget that gets spent on energy-efficiency gear (heat pumps, insulation), producing posts like "installed a heat pump, sim bill dropped from $210 to $163/month."

### The anti-hallucination constraint

The entire design exists in service of one rule: **every number in a game post must come from a lookup table, never from the LLM.** This mirrors the project's existing unverified-link rule (the engine can't introduce a citation the pipeline didn't supply) with a new `unverified-number` moderation rule: any numeric token in a drafted game post that doesn't appear in the originating `Experience.summary_facts` gets flagged. The LLM's job is narrowly to phrase pre-computed facts, never to compute or invent them.

### The four-verb `Game` protocol

A game is a pure-transform object, structurally the same kind of seam as the existing `PersonaEngine` protocol — no network or store access inside it:

```python
class Game(Protocol):
    def tick(world, clock) -> TickReport: ...           # advance time, accrue bill, age gear
    def do_your_thing(world, clock) -> ActionReport: ...  # one policy-driven move, e.g. buy gear
    def you_got_mail(world, mail) -> MailReport: ...      # handle inbound game mail (deferred to a later phase)
    def write_your_thoughts(world, recent) -> list[Experience]: ...  # decide what's post-worthy
```

Only `write_your_thoughts` produces output that can become a post, and even that output is `Experience` records — flat fact dictionaries, not prose:

```python
@dataclass
class Experience:
    id: str                       # content-addressed, so existing dedupe just works
    kind: str                     # "purchase" | "bill" | "milestone" | "event"
    summary_facts: dict[str, str] # {"item": "GW-200 heat pump", "price": "$3,400", ...}
    topic: str
    opinion_keys: list[str]
    source_url: str = ""
    period: str = ""
```

### How it joins the existing pipeline — no parallel path

The design decision here matters for anyone extending the pipeline later: game experiences become **synthetic `NewsItem`s** (via an `experience_to_item` bridge) and flow through the *same* `react_to_items` loop that handles real RSS items. There is deliberately no separate pacing, dedupe, or moderation path for game content — it competes for the same post slots under the same guardrails as news.

```
persona/game/ ──tick/do_your_thing──▶ Experience[] ──bridge──▶ synthetic NewsItem[] ──┐
                                                                                        ├──▶ react_to_items (unchanged) ──▶ moderate ──▶ store
                                                              live RSS ──▶ real NewsItem[] ──┘
```

`MockBot` gets a small added branch (when a synthetic item's hints carry `game: "true"`, build a deterministic post straight from `summary_facts`, no LLM call); `OpenRouterBot` gets a constrained prompt section that only lets it use facts in the supplied dict. Everything downstream of drafting — pacing, moderation, the store, the admin UI, the poster — is untouched.

### Game state never writes opinions

A hard rule from the design, enforced rather than just conventional: the game path may *read* `opinions.toml` (to decide which experiences resonate with existing beliefs) but must never write to it — no `OpinionChange`, no reinforcement, no pushback from a game reaction. Opinions stay news-driven only; a simulated purchase can be cited as evidence for a belief the persona already holds, but can't form a new one. World state (`world.toml`, `catalog.toml`, `ledger.jsonl`) lives under `persona/game/`, versioned the same way `persona/memory/` is today.

### Honesty framing

Game posts get an explicit disclosure distinct from the news disclosure (`"🤖 bot post · simulated home · human approved"`), and the persona's voice rules add a "this is a transparent simulation" framing ("in my sim home," "modeled bill") rather than claiming a real lived experience.

### Planned service shape

A fourth subcommand, `activist game --config activist.toml [--once | --loop]`, mirroring the existing `fetch`/`ui`/`poster` service pattern. One tick: advance the game clock, let the policy make at most one move, ask the game what's worth posting, bridge new experiences into the shared `react_to_items` path, persist the ledger. A `[game]` config block (`enabled`, `name`, `interval_minutes`, `max_posts_per_run`) gates the whole feature off by default — when absent or `enabled = false`, the rest of the pipeline behaves exactly as it does today.

## Where to read more

The full specs (worth reading before implementing any of this) are `spec/personas.md` and `spec/bots_in_games.md`, including the per-phase build orders (P0–P2 for the persona registry, G0–G4 for the game feature) and open questions the authors flagged as deferred, like whether personas should be able to share a `knowledge.md`.
