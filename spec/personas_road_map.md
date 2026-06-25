# Personas: Roadmap & Open Decisions

**Status:** decision doc, 2026-06-19. Companion to `personas.md` (the target
design) and `bots_in_games.md`. This doc exists to surface the **one real
decision** in `personas.md` — the registry refactor — separate it from the
parts that are uncontroversial, and lay out options with their actual blast
radius so the boss can pick.

---

## 1. The situation

`personas.md` proposes two changes that the boss's requirement ("expensive bot
in prod, cheap bot for local testing; multiple personas, one per account") seems
to demand. But they are **not equally costly**, and only one of them is actually
required to satisfy the stated ask:

| Change | Delivers | Cost | Required for the ask? |
|---|---|---|---|
| **A. Per-env engine overlay** (`extends`) | "expensive in prod, cheap in dev" | low — additive config | **Yes** |
| **B. Persona registry** (`personas/<id>/`) | "many personas, one per account" | medium — directory move + test churn | Only for the *multi-persona* half |

The trap: bundling B into A makes a low-risk config feature ride along with a
repo-wide directory move. They should be decided — and probably shipped —
**separately**. A is easy and unblocks the boss's primary phrasing today. B is a
refactor whose timing is a real choice.

## 2. What's NOT in question

These are settled by `personas.md` and need no decision here:

- **Identity lives in git; engine richness lives in config.** Splitting these
  two axes is the core insight and isn't controversial — `[engine]`/
  `[moderation]` are already config, not persona.
- **Per-env overlay via `extends`** (change A). It reuses the existing
  `activist.mock.toml` pattern, touches only `config.py`'s loader, and is purely
  additive. Recommend shipping it regardless of how the registry decision goes.
- **`engine.thinking`** as a new opaque config hint (no-op for mockbot).
- **One persona active per config / per process.** Multi-persona = multiple
  configs + service processes, matching how `mastodon_id` + `.env` already work.

The open question is **only B: do we move to `personas/<id>/`, and when?**

## 3. The decision: persona registry

### The issue

Today there is exactly one persona directory, `persona/`, and `cfg.persona_dir`
is resolved from `paths.persona` in `config.py`. To run **a second persona**
(the multi-account goal), that single dir must become a *registry* selected by
id: `personas/<id>/`, chosen by `[identity].persona_id`.

The source code is ready for this — `persona_dir` is threaded cleanly through
`cfg.persona_dir` in 14 source/test files (55 references), all reading one
config-resolved path. The cost is **not** in the source; it's in:

- the **directory move** `persona/` → `personas/lowwatt/` (a git rename of live,
  mutating state — opinions/memory that change every run);
- **test fixtures** that hardcode the path, chiefly `tests/test_e2e.py`, which
  copies `repo_root / "persona"` and asserts against `workspace / "persona"` in
  ~8 places, plus `tests/conftest.py` and the e2e copytree;
- **docs** — ~12 files under `docs/` reference `persona/` by name;
- the `[game]` work in `bots_in_games.md` assumes `persona/game/`, so the two
  features touch the same directory and their ordering interacts.

### Option B1 — Registry now (P0, as `personas.md` recommends)

Do the move first, then build games on top of `personas/<id>/game/`.

- **Pros:** the target layout from day one; games land in the final location; no
  second migration later; multi-persona unblocked immediately.
- **Cons:** a directory move of live mutating state plus test/doc churn lands
  *before* any user-visible feature; if games slip, we paid the refactor for
  nothing yet.
- **Effort:** ~1 focused session. Mechanical but wide (move, update
  `config.py`, fix e2e/conftest paths, sweep docs).

### Option B2 — Overlay now, registry later (recommended)

Ship change A (`extends`) now. Keep the single `persona/` dir. Build the
`energy_home` game against `persona/game/`. Do the `personas/<id>/` move as its
own phase **after** games prove out — with a back-compat fallback so it never
blocks.

- **Pros:** the boss's primary ask ("expensive prod / cheap dev") ships
  immediately with near-zero risk; no live-state move until something actually
  needs a second persona; games and the registry don't churn the same paths in
  the same change.
- **Cons:** a known second migration (`persona/` → `personas/lowwatt/`) is
  deferred, not avoided; `persona/game/` paths get rewritten once when it lands.
- **Mitigation:** `config.py` already plans a `paths.persona` back-compat
  fallback (`personas.md §2`). Keep it: `persona_id` resolves to
  `personas/<id>/` when set, else falls back to `paths.persona`/`persona/`. The
  move becomes opt-in and reversible, never a hard cutover.

### Option B3 — Never; symlink/alias instead

Keep `persona/` forever; if a second persona is ever needed, point a second
config at a sibling dir via `paths.persona` directly (no registry concept).

- **Pros:** zero refactor; `paths.persona` already supports an arbitrary path.
- **Cons:** no canonical home for N personas; every persona's path is ad-hoc
  per-config; doesn't express "these are all personas of one system"; games and
  future tooling have no registry to enumerate. Fine for 2, awkward at 5.

## 4. Recommendation

**B2.** Concretely:

1. **Now:** ship the `extends` overlay (change A) + `activist.prod.toml`. This
   is the boss's stated requirement and it's low-risk. *(P1 in `personas.md`.)*
2. **Now:** build `energy_home` against `persona/game/` (current single dir).
3. **When a real second persona appears** (or right before, deliberately): do
   the `personas/<id>/` move with the `paths.persona` fallback. *(P0/P2 in
   `personas.md`, demoted from "first" to "when needed.")*

Rationale: A delivers the headline ask immediately; B's cost is real but its
*value* (multiple accounts) isn't needed until there's a second persona to run.
Pulling the move forward spends refactor budget before it pays off and entangles
it with the game work on the same paths. The back-compat fallback means deferring
costs us nothing — we can move the day we need to, no flag day.

## 5. If the boss wants the registry now anyway

Pick **B1** and sequence it as the very first persona task, *before* the game's
`persona/game/` work, so games are written against the final
`personas/<id>/game/` path and never need rewriting. The migration checklist:

1. `git mv persona personas/lowwatt` (preserves history of the mutating state).
2. `config.py`: add `[identity].persona_id`, resolve
   `persona_dir = personas_root / persona_id`; keep `paths.persona` as a
   fallback for one release.
3. Default `personas_root = personas/`; validate `persona_dir` exists (replaces
   today's `_validate_paths` persona check).
4. Fix hardcoded paths in `tests/test_e2e.py` (copytree source + ~8 assertions)
   and `tests/conftest.py`.
5. Sweep `docs/` (~12 files) for `persona/` → `personas/lowwatt/`.
6. Update `activist.toml` / `activist.mock.toml` to set `persona_id`.

This is the only decision in `personas.md` with a non-trivial cost. Everything
else there is additive and safe to build now.
