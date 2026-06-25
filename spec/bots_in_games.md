# Bots in Games

**Status:** plan, 2026-06-19. Companion doc: `personas.md`. Builds on
`real_overview.md` (the three-service architecture) and the engine seam in
`engine/base.py`.

> A *nirmāṇakāya* note, since the boss named it: a game is a **temporary body**
> the persona inhabits so that *ideas can occur in the event of living ordinary
> life*. The persona (its voice, its opinions) is the durable mind. The game is
> a disposable vehicle that generates lived experience for that mind to react
> to. Many personas, many games; one game per persona at a time.

---

## 1. Why this exists

Today the bot only has one source of things-worth-saying: **inbound news**
(RSS → `react_to_items`). That is a narrow, reactive distribution
(`content_strategy.md` calls out the splog risk). A bot that only comments on
articles is borderline content-stealing and adds little a reader couldn't get
themselves.

A **game** gives a persona a *second, first-party* source of experience: it
does things in a tiny simulated world and those events become post fuel. For
`lowwatt`, the game is **"a bot with a quantity of money that it spends on
energy-efficiency gear for its simulated home."** It buys a heat pump; its
modeled energy bill drops; *that* is something only this bot can say, because
only this bot lived it.

The crucial constraint (boss's instruction): the game is **table-driven**.
Every number a post can cite — a price, a bill delta, a payback period — is
*computed by the game from lookup tables*, never invented by the LLM. The
engine narrates pre-computed facts. This is the anti-hallucination spine of the
whole feature (it mirrors the existing **unverified-link rule**: the model may
not introduce a fact the pipeline didn't supply).

## 2. The Game interface (the four verbs)

A game is an object implementing one Protocol. Each verb takes the game's own
durable world-state and returns a typed result. None of the verbs talk to the
network, the store, or Mastodon — exactly like the engine seam, the game is a
pure transform and everything around it is shared plumbing.

```python
# src/activist/game/base.py
from typing import Protocol

class Game(Protocol):
    @property
    def name(self) -> str: ...          # "energy_home", registry key

    def tick(self, world: World, clock: GameClock) -> TickReport:
        """Time passes. Advance the world: accrue this period's simulated
        energy bill from current inventory, age gear, apply scheduled
        events. Mutates `world`; returns what changed (for the diary +
        ledger). NEVER posts."""

    def do_your_thing(self, world: World, clock: GameClock) -> ActionReport:
        """A free turn. The game's *policy* (ordinary code, not the LLM)
        decides one move — e.g. buy the highest-ROI affordable item from
        the catalog — and applies it. Returns the move + its table-derived
        outcome. NEVER posts."""

    def you_got_mail(self, world: World, mail: GameMail) -> MailReport:
        """Inbound mail addressed to the game character (a rebate notice, a
        question about a purchase). Returns a structured reply payload; the
        *wording* is later produced by the engine, the *facts* come from
        `world`. NEVER posts directly."""

    def write_your_thoughts(
        self, world: World, recent: list[GameEvent]
    ) -> list[Experience]:
        """Look at what just happened (this tick's report + recent unposted
        events) and decide which, if any, are worth a post. Returns 0..N
        `Experience` records — each a *fully-resolved set of facts* with no
        free text. The engine turns an Experience into prose later."""
```

### Why four verbs and not one

They separate **simulation** (`tick`), **agency** (`do_your_thing`),
**interaction** (`you_got_mail`), and **expression** (`write_your_thoughts`).
The first three change the world and must be deterministic and replayable; only
the last decides what becomes public, and even it emits *facts, not prose*. This
keeps the LLM at the very edge of the system — it phrases, it does not decide
and does not compute.

### The `Experience` is the heart of the contract

```python
@dataclass
class Experience:
    """A table-resolved event the persona may post about. All numbers are
    final; the engine may only rephrase, never recompute or introduce facts."""
    id: str                       # stable: sha256(persona:event_key:period)
    kind: str                     # "purchase" | "bill" | "milestone" | "event"
    summary_facts: dict[str, str] # {"item": "GW-200 heat pump",
                                  #  "price": "$3,400", "bill_before": "$210",
                                  #  "bill_after": "$163", "saved_pct": "22%"}
    topic: str                    # maps to a persona beat ("heat pumps")
    opinion_keys: list[str]       # opinions this experience touches (read-only)
    source_url: str = ""          # catalog/source citation if the table has one
    period: str = ""              # game-clock label, e.g. "2026-07"
```

`summary_facts` is a flat string→string map so it serializes cleanly to the
ledger, renders in the admin UI verbatim, and gives the engine an explicit
allow-list of values it may use. A post-publish check (see §6) verifies every
number in the drafted post text appears in `summary_facts` — if the model
introduced a figure, the draft is flagged, exactly like an unverified link.

## 3. World-state: `persona/game/` under git

Per `personas.md`, world-state is **persona state** and lives beside the
persona's opinions, reviewable as a git diff (the same principle as
`persona/memory/`). One game per persona, so the layout is flat:

```
persona/
  persona.toml          # identity + voice (unchanged)
  opinions.toml         # unchanged — game NEVER writes here (see §5)
  knowledge.md
  memory/               # news/reply memory (unchanged)
  game/
    game.toml           # which game + tunables: starting_money, monthly_budget,
                        #   policy ("highest_roi"), framing ("sim_home")
    world.toml          # durable state: money, owned inventory, clock period
    catalog.toml        # the gear table (price, modeled savings) — the
                        #   anti-hallucination source of truth
    ledger.jsonl        # append-only: every tick, purchase, bill, mail event
    posted.jsonl        # Experience ids already turned into drafts (dedupe)
```

### `catalog.toml` — the table that makes posts trustworthy

```toml
[[item]]
key = "heatpump-gw200"
name = "ABC GW-200 cold-climate heat pump"
topic = "heat pumps"
price = 3400
# Modeled monthly saving vs the baseline this item replaces, in dollars.
# This is THE number that ends up in a post. Sourced, not guessed.
monthly_saving = 47
replaces = "resistance-heat"
source_url = "https://example.org/gw200-testing"
opinion_keys = ["heat-pump-top-pick"]

[[item]]
key = "insulation-attic"
name = "attic air-seal + R-49 insulation"
topic = "home insulation"
price = 1800
monthly_saving = 31
replaces = "leaky-attic"
source_url = "https://example.org/attic-retrofit"
opinion_keys = ["insulation-first"]
```

### `world.toml` — what changes

```toml
[state]
money = 12000          # dollars remaining
period = "2026-07"     # current game-clock period
baseline_bill = 210    # modeled monthly bill before any retrofits

[[owned]]
key = "insulation-attic"
bought_period = "2026-06"
```

`tick` recomputes the current bill = `baseline_bill - sum(monthly_saving of
owned)`; `do_your_thing` spends `money` on the best affordable catalog item the
policy picks; both append to `ledger.jsonl`. **No number in any of this is
produced by an LLM.**

## 4. Where game experience joins the posts pipeline

Decision (boss): **game experiences enter as synthetic `NewsItem`s and flow
through the existing `react_to_items` loop.** We add no parallel pacing,
dedupe, or moderation path — the game competes for the same post slots as real
news and obeys the same guardrails.

```
persona/game/  ──tick/do_your_thing──▶ Experience[]
                                          │  (game.experiences_to_items)
                                          ▼
                              synthetic NewsItem[]  ──┐
   live RSS ──▶ fetch_news ──▶ real NewsItem[] ──────┼──▶ react_to_items
                                                      │      (UNCHANGED)
                                                      ▼
                                              moderate → store (pending_review)
```

### The bridge: `Experience → NewsItem`

```python
# src/activist/game/bridge.py
def experience_to_item(exp: Experience) -> NewsItem:
    return NewsItem(
        id=exp.id,                         # already content-addressed → dedupe
        feed="game:energy_home",           # distinguishes game items in logs/UI
        title=_headline(exp),              # "Sim home: installed the GW-200"
        url=exp.source_url,                # catalog citation, or "" 
        published=exp.period,
        summary=_facts_blob(exp),          # the summary_facts as text
        hints={                            # mockbot reads hints; openrouter ignores
            "game": "true",
            "experience_id": exp.id,
            **exp.summary_facts,           # facts the engine may cite
        },
    )
```

Because the synthetic item carries a content-addressed `id`, the existing
`seen.jsonl` dedupe and the store's primary-key dedupe both work with zero
changes — an Experience can't be double-posted any more than an article can.

### Engine changes are additive and small

`react_to_items` already routes on `hints` for mockbot. We extend both engines:

- **MockBot** gains a branch: when `hints["game"] == "true"`, it builds a
  deterministic post straight from `summary_facts` (no opinion-change/pushback
  machinery — see §5). This keeps the whole game path testable with zero LLM.
- **OpenRouterBot** gets a game-aware prompt section: *"You are narrating a
  transparent simulation. You may ONLY use these facts: {summary_facts}. Do not
  introduce any number, brand, or price not listed. Frame as your sim home."*

The persona's `react()` for a game item produces a `DraftPost` with a
**game disclosure** (§6). Everything downstream — pacing, moderation, the
store, the admin UI, the poster — is untouched.

### `you_got_mail` reuses the replies path

Game mail is rare and optional for v1. When enabled, a `GameMail` is adapted to
the existing `Mention`/`reply()` seam the same way an Experience adapts to a
`NewsItem`, so consent gates and reply pacing apply unchanged. **Defer to a
later phase**; `write_your_thoughts` is the v1 value.

## 5. Game NEVER writes opinions (boss decision)

The game is a **pure content source**. `do_your_thing` and `tick` may *read*
`opinions.toml` (to pick which experiences resonate with what the persona
already believes), but the game path **never** emits `OpinionChange`,
reinforcement, or pushback. `opinions.toml` stays news-driven only.

Concretely, in `react_to_items` the game branch returns a `Reaction` with
`opinion_changes=[]`, `reinforcements=[]`, `pushbacks=[]`. The
`apply_engine_state` writeback for game items touches only `seen`/`said`/diary,
never `opinions.toml`. This is enforced, not merely conventional: a small guard
asserts game reactions carry no opinion mutations.

> Rationale: a single simulated purchase rewriting a stated belief would be both
> epistemically sloppy *and* a review-surface surprise. The bot can *cite its
> sim home as evidence for an opinion it already holds* without the sim being
> allowed to *form* opinions. Keeps the game honest and the diffs boring.

## 6. Honesty: the "sim home" framing

Voice rule today: *"never claims human experiences (no 'my house', 'I drove')."*
The game is a simulation the bot transparently owns, so we **add** rather than
violate:

- New persona voice rule: *"game posts are explicitly framed as a transparent
  simulation — 'in my sim home', 'modeled bill', never a real dwelling."*
- New **game disclosure** line appended to game posts, distinct from the news
  disclosure: `"🤖 bot post · simulated home · human approved"`. Configured in
  `game.toml` (`framing = "sim_home"`), surfaced by the engine.
- New moderation rule (`moderation/`, alongside the unverified-link rule):
  **`unverified-number`** — scan the drafted post for numeric tokens
  (`$3,400`, `22%`, `$163`); every one must appear in the originating
  `summary_facts`. A figure the model invented gets an `error` flag. Flags never
  drop posts (existing principle); a human sees it in the UI and rejects/edits.

Together: the *facts* are table-true (§2–3), the *framing* says "sim", and the
*moderation* catches any number the model smuggled in. Honest by construction.

## 7. The game service (the clock)

Decision (boss): a **fourth subcommand**, `activist game`, alongside
`fetch` / `ui` / `poster`, with its own interval — mirroring the existing
service pattern exactly (`real_overview.md §1`).

```
activist game --config activist.toml [--once | --loop]
```

One tick of the service:

1. `tick(world, clock)` — advance time, accrue the period's bill, age gear.
2. `do_your_thing(world, clock)` — make at most one move (policy-driven).
3. `write_your_thoughts(world, recent)` → `Experience[]`.
4. Bridge each new Experience (not in `posted.jsonl`) → synthetic `NewsItem`.
5. Feed them through `react_to_items` + moderation + `store.add_pending`
   **using the same code the fetcher calls** — no fork of the pipeline.
6. Persist: append `ledger.jsonl`, mark Experiences in `posted.jsonl`, save
   `world.toml`, write the game's diary lines.

`GameClock` decouples game-time from wall-time: a tick can equal "one simulated
month" regardless of how often the service runs, so a 5-minute dev loop and a
daily prod loop both produce a sane bill cadence. The clock period is stored in
`world.toml` so restarts resume, and tests can pin a fixed clock for
byte-identical output (same discipline as the mockbot).

### Config additions (`activist.toml`)

```toml
[game]
enabled = true
name = "energy_home"          # registry key → src/activist/game/<name>.py
interval_minutes = 1440       # wall-clock cadence of the service loop
ticks_per_run = 1             # game-clock periods advanced per loop
max_posts_per_run = 1         # game is a trickle, not a firehose
```

`config.py` validates these the same way it validates `[fetch]`/`[poster]`;
absent `[game]` (or `enabled = false`) means the service no-ops and nothing
else changes — the feature is fully opt-in and the existing pipeline is
untouched when it's off.

## 8. Build order

1. **G0 — interfaces & state.** `game/base.py` (Protocol, `World`,
   `Experience`, reports), `persona/game/` loader/saver in the `state.py`
   style, `[game]` config block. No behavior yet. *(Opus: get the
   `Experience`/world contract right; everything hangs off it.)*
2. **G1 — `energy_home` game.** Catalog loader, `tick` bill model,
   `do_your_thing` highest-ROI policy, `write_your_thoughts`. Pure, seeded,
   table-driven, fully unit-tested with no LLM. *(Sonnet: well-specified
   simulation.)*
3. **G2 — the bridge + engine branches.** `experience_to_item`, MockBot game
   branch, OpenRouter game prompt, the `unverified-number` moderation rule,
   the game disclosure. *(Opus: the moderation/honesty seam. Sonnet: the
   MockBot branch + tests.)*
4. **G3 — the service.** `activist game` subcommand, `GameClock`, loop/once,
   wiring into the shared `react_to_items`/store path, ledger/posted/diary
   persistence. *(Sonnet: mirrors the fetcher/poster service.)*
5. **G4 (later) — `you_got_mail`.** Adapt `GameMail`→`Mention`, reuse reply
   consent gates. Optional.

## 9. What stays unchanged (the test of a good design)

- `react_to_items`, pacing/`ratelimit.py`, dedupe, moderation pipeline, the
  store, the admin UI, the poster: **all untouched**. Game items are just
  `NewsItem`s with a `game` hint.
- `opinions.toml` writeback: untouched (§5 forbids the game from touching it).
- Tests keep pinning to fixtures; the game path is deterministic, so it gets
  the same golden-file treatment the mockbot news path already has.
- When `[game].enabled = false`, the binary behaves exactly as it does today.
