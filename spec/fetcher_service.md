# Fetcher Service Plan

**Status:** plan, 2026-06-11. Shared decisions in `real_overview.md`.
**Job:** live news in, live mentions in → digestible items → engine →
moderation → `pending_review` rows in the queue store. Never publishes
anything; Mastodon access is **read-only** (`MastodonReader`).

---

## Phase F1 — Config, store, and live RSS ingestion ✅ implemented 2026-06-11

The foundation phase; admin UI and poster both build on it.

### Deliverables

1. **`config.py`** — load/validate `activist.toml` (schema in
   `real_overview.md` §4). Dataclass `AppConfig`; clear errors for missing
   feeds, unknown identity, bad intervals. `.env` loading stays where it is
   (dotenv handles the `export ` prefixes already in the file).
2. **`store.py`** — SQLite queue per `real_overview.md` §3: connection
   helper (WAL, busy_timeout), `init_db()`, typed CRUD
   (`add_pending`, `get`, `list_by_status`, `transition(id, from, to, actor,
   detail)`), append-only `event_log`. The `transition` function is the only
   way status changes — it validates legality and logs.
3. **`fetch.py`** — live RSS/Atom over httpx:
   - Conditional GET: persist `ETag`/`Last-Modified` per feed URL in
     `.cache/feeds/<sha12(url)>.json`; send `If-None-Match`/
     `If-Modified-Since`; 304 → skip. Timeouts, polite User-Agent
     (`activist/<version> (+repo url)`), per-feed failure isolation
     (one dead feed never kills the run — matches `parse_feed`'s
     degrade-gracefully behavior).
   - Refactor `ingest.parse_feed(path)` to also accept bytes
     (`parse_feed_bytes`) so fixtures and live bodies share one parser.
     Fixture-based tests must not change.
4. **`digest.py`** — "ordinary code turns articles into something digestible":
   - Normalize RSS summaries (bs4 strip — exists), collapse whitespace,
     truncate to a token budget.
   - Optional full-article fetch (config flag, default off): GET the article
     URL, extract `<article>`/`<main>`/`og:description` text via bs4, cap at
     ~2000 chars. No readability dep unless extraction proves too weak —
     revisit then.
   - Output is still `NewsItem`; `summary` just gets better.
5. **Dedup** — reuse `persona/memory/seen.jsonl` exactly as today (URL /
   title-hash). Seen-skip happens *before* digesting (don't fetch article
   bodies for items we've already processed). The store additionally rejects
   duplicate content ids (PRIMARY KEY) as a backstop.
6. **CLI:** `activist fetch --config activist.toml [--dry-run]` — fetch +
   digest + dedupe only in this phase; prints what's new. `--dry-run` skips
   cache writes and seen.jsonl appends.

### Tests
Mirror existing style: cached-vs-304 behavior with a fake httpx transport;
digester normalization table; dedupe across two runs; malformed live feed
degrades; store transition legality (every illegal transition raises);
parallel-writer smoke test (two connections, WAL).

### Model fit
- **Opus:** `store.py` schema + transition rules (everything depends on it;
  concurrency semantics are easy to get subtly wrong).
- **Sonnet:** config loader, conditional GET, digester, CLI plumbing, tests.

---

## Phase F2 — News through the bot into the queue ✅ implemented 2026-06-12

### Deliverables

1. **Pipeline sink refactor.** `pipeline.run()` currently ends at
   `write_feed(out/<date>/feed.toml)`. Introduce a sink seam: the run
   produces `DraftPost`s + flags, then writes them to (a) the store as
   `pending_review` and (b) optionally the legacy `out/<date>/` artifacts
   (config flag, on by default during transition). Persona state writes
   (opinions, said/seen/diary) are unchanged.
2. **Moderation inline.** `activist fetch` runs MockModerator on every draft
   before insert (LLM moderation too if `[moderation].engine = "openrouter"`).
   Flags land in the `flags` column. A separate `activist moderate` pass over
   the store stays possible for re-checks.
3. **Scheduling slots.** `ratelimit.py` slot assignment moves from "spread
   over the run date" to "next free slots after now, given what's already
   `approved`/`published` for this identity" — query the store for the last
   scheduled slot and continue from there. Rate limiting stays ordinary code.
4. **CLI:** `activist fetch` now does the full chain: fetch → digest →
   dedupe → relevance → engine → moderate → store. `--engine mockbot`
   override kept for offline testing.

### Tests
End-to-end with fixture feeds → store rows with status/flags/slots asserted;
golden continuity with `tests/seed_opinions.toml`; slot continuation across
two fetch runs.

### Model fit
- **Opus:** the sink refactor and slot-continuation logic (touches
  pipeline, ratelimit, store — cross-cutting, and the slot math now has
  persistent state).
- **Sonnet:** moderation wiring, CLI, tests.

---

## Phase F3 — Replies fetcher ✅ implemented 2026-06-12

Live, read-only. `mastodon_client.MastodonReader` gained `notifications`,
`get_account`, and `X-RateLimit-*` backoff; `notification_to_mention` maps API
JSON to the `Mention` dataclass (HTML-stripped, `@ handle` artifact healed),
carrying the real status id and visibility through `DraftPost` →
`ContentRow.in_reply_to_status_id`/`visibility`. `reply_fetch.run_reply_chain`
runs the same consent gates and `engine.reply` as the fixture path, checkpoints
`since_id` in the store `kv` table (`mastodon:<ID>:notifications:since_id`),
belt-and-suspenders dedups via `memory/mentions.jsonl`, and queues survivors as
`pending_review` / `kind='reply'`. CLI: `activist fetch --replies` /
`--only-replies` (defaults to `[replies].enabled`). The fixture path
(`activist replies`) stays for offline tests.

### Deliverables

1. **`mastodon_client.py` / `MastodonReader`** (see `real_overview.md` §5):
   `verify_credentials()`, `notifications(types=["mention"], since_id=...)`,
   `get_status(id)`, `get_account(id)`. httpx, bearer token from the
   configured identity, honors `X-RateLimit-*` response headers (sleep/stop
   when near zero). Read-only by construction.
2. **Mention mapping** — API notification JSON → existing `Mention`
   dataclass: author handle, HTML-stripped status text (bs4), bio
   (`account.note`, stripped) for the `#nobot` check, `account.bot` flag,
   **plus the real status id and visibility** carried through to the draft's
   `in_reply_to_status_id` (the poster needs it to thread; visibility of the
   reply should match the mention's, e.g. don't answer a DM publicly).
3. **Same gates, same seam.** Consent gates (`consent_skip_reason`) run
   unchanged; `since_id` checkpoint stored in the DB (`kv` table or
   `event_log`) *and* dedupe via `memory/mentions.jsonl` as today — belt and
   suspenders. Survivors → `engine.reply` → moderation (replies keep their
   exemptions + the unverified-link rule) → store as `pending_review`,
   `kind='reply'`.
4. **CLI:** `activist fetch --replies` (or `activist fetch` does both per
   config `[replies].enabled`). Fixture path (`activist replies`) stays for
   tests.

### Tests
Recorded notification JSON fixtures (capture once from the real API with the
TECH identity, scrub ids) → Mention mapping; consent-gate table against API
shapes (`account.bot`, `#nobot` in HTML bio); since_id checkpointing;
rate-limit header backoff with fake transport.

### Model fit
- **Opus:** `MastodonReader` error/backoff semantics and the
  visibility-handling rules (privacy mistakes here are outward-facing later).
- **Sonnet:** JSON→Mention mapping, checkpointing, fixtures, tests.

---

## Phase F4 — Run it unattended (lightweight)

### Deliverables

1. `activist fetch --loop` — sleep/wake loop honoring `[fetch]` and
   `[replies]` intervals, jittered, with a lockfile so two fetchers can't
   run at once. Ctrl-C clean shutdown.
2. Structured logging to `data/logs/fetcher.log` (rotating, stdlib
   `logging.handlers`); per-run summary line the admin UI can surface later.
3. Windows Task Scheduler recipe (docs only): `schtasks` running
   `uv run activist fetch` every N minutes as the no-daemon alternative.
   Full service story lives in `poster_service.md` Phase P3 and is shared.

### Model fit
- **Sonnet:** all of it.

---

## Explicitly out of scope here
Publishing (poster doc), any UI (admin doc), auth, multi-user, non-RSS
sources beyond Mastodon mentions ("other feeds" in `activist.toml` start as
RSS/Atom only; a `type` field on `[[feed]]` leaves the door open).
