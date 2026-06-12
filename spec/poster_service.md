# Poster Service Plan

**Status:** plan, 2026-06-11. Shared decisions in `real_overview.md`.
**Job:** drain the `approved` queue on schedule and publish each item at its
`scheduled_for` slot. **The live Mastodon transport is NOT built in Phase P1
and stays hard-gated in P2** — until you flip the gate, "publish" means the
dry-run transport. Read-only API calls (verify_credentials) are allowed now.

---

## Phase P1 — Scheduler + dry-run transport

Everything about the poster except actually posting. After this phase the
full loop works end to end: fetch → review → approve → "published" rows,
with zero outbound writes.

### Deliverables

1. **Transport seam** (`transport.py`) — the same trick as the engine seam:

   ```python
   class Transport(Protocol):
       def publish(self, item: ContentRow) -> PublishReceipt: ...

   @dataclass
   class PublishReceipt:
       status_id: str        # real Mastodon id, or "dryrun-<uuid>"
       url: str              # status URL, or a file:// pointer
       published_at: str
   ```

   `DryRunTransport` (default, and the only one implemented in P1):
   appends the would-be toot to `data/published_dryrun.jsonl` and returns a
   fake receipt. `MastodonTransport` exists as a stub that **raises
   `NotImplementedError`** — selecting it is impossible until P2.

2. **Scheduler loop** (`poster.py`, `activist poster [--once|--loop]`):
   - Each tick: `SELECT` `approved` rows with `scheduled_for <= now` for the
     configured identity, oldest first.
   - **Claim protocol** (decided with admin_ui U2 item 4): transition
     `approved→publishing` via compare-and-swap in one transaction; only a
     successful claim proceeds. Publish → `publishing→published` with
     receipt fields; failure → `publishing→failed` with the error in
     `event_log`.
   - Pacing backstop: even if slots were edited by hand, never publish two
     items closer together than the effective per-identity spacing from
     `ratelimit.py` (ordinary code, the poster's last line of defense).
   - `--once` does a single tick (Task Scheduler mode); `--loop` honors
     `[poster].check_interval_minutes`, lockfile, clean Ctrl-C.
3. **Startup self-check:** `MastodonReader.verify_credentials()` for the
   configured identity (read-only, allowed now) — fail fast with a clear
   message if the token is bad, *before* claiming anything.
4. **`failed` handling:** stays `failed` until a human acts (UI shows it;
   retry = transition back to `approved`). No automatic retries in P1 —
   simplest thing that can't double-post.
5. **Persona memory:** on successful publish, append to
   `persona/memory/said.jsonl` if the fetch phase didn't already (decide:
   said-at-draft-time vs said-at-publish-time — recommendation: keep
   said-at-draft for engine continuity, add the publish receipt to
   `event_log` only, so persona files stay fetcher-owned).

### Tests
Claim CAS under a simulated concurrent UI edit; dry-run end-to-end (seed
approved rows → tick → published rows + jsonl lines); pacing backstop with
hand-mangled slots; failed transition on a transport that throws; `--once`
idempotence (second tick publishes nothing new).

### Model fit
- **Opus:** the claim protocol + pacing backstop + failure semantics
  (this is the component where a bug eventually means double-posting or
  posting rejected content; get the state machine right while it's cheap).
- **Sonnet:** dry-run transport, loop/lockfile/CLI, verify_credentials
  check, tests, once the state machine is specified.

---

## Phase P2 — Live Mastodon transport (GATED — do not start without explicit go)

### The gate (defense in depth, all three required)

1. `[poster].live = true` in `activist.toml` (committed, reviewable),
2. environment variable `ACTIVIST_LIVE=1` (never committed),
3. CLI flag `--live` on `activist poster`.

Anything less → `DryRunTransport` with a loud log line saying why. This
makes "accidentally went live" require three separate mistakes.

### Deliverables

1. **`MastodonPublisher.post_status`** — `POST /api/v1/statuses` with:
   - **`Idempotency-Key` header = content id.** Mastodon natively dedupes on
     it (~1h window), so a crash between POST and the DB write cannot
     double-post on retry. This is the single most important line in the
     poster.
   - `in_reply_to_id` from `in_reply_to_status_id` for replies; `visibility`
     carried from the mention (fetcher F3 item 2) — replies match the
     visibility of what they answer, top-level posts use config default
     (`public` or, for a soft launch, `unlisted`).
2. **Error taxonomy** → store status:
   - 401/403/422 (bad token, suspended, validation) → `failed`, stop the
     loop (everything else will fail too; alert via log + UI ops strip).
   - 429 → respect `X-RateLimit-Reset` / `Retry-After`, leave the row
     `publishing`? No — transition back to `approved` (CAS) and retry next
     tick after the reset time; record the backoff in `event_log`.
   - 5xx/network → `failed` after one in-tick retry with the same
     idempotency key.
3. **Receipt write-back:** real `mastodon_status_id`, status URL,
   `published_at`; the UI's published archive links to the live status.
4. **First-flight checklist (docs):** soft-launch with `visibility =
   "unlisted"`, `[fetch]` paused, one hand-approved test post; verify the
   disclosure footer renders; confirm delete works (`DELETE /statuses/:id`
   — also the manual "oh no" tool); then normal operation.

### Tests
Fake httpx transport: idempotency header present and stable across retries;
each error class → correct status transition; 429 backoff math; visibility
propagation for replies vs posts. **No live-network tests, ever** (existing
pytest-network blocking stays).

### Model fit
- **Opus:** all of item 1–2 design (idempotency + error taxonomy + the 429
  re-queue dance). The implementation afterwards is Sonnet-friendly.
- **Sonnet:** receipt write-back, checklist doc, tests from the spec.

---

## Phase P3 — Daemon / Windows service

Make the fetcher (`--loop`) and poster (`--loop`) survive reboots without a
terminal. Shared with fetcher F4.

### Deliverables

1. **Recommended: Windows Task Scheduler, no service at all.**
   `schtasks` definitions (or an XML you import) running
   `uv run activist fetch` and `uv run activist poster --once` on intervals,
   "run whether user is logged on or not". Stateless ticks + the claim
   protocol mean missed/overlapping ticks are already safe; lockfiles guard
   the rest. Provide `scripts/install-tasks.ps1` / `uninstall-tasks.ps1`.
2. **Alternative (only if Task Scheduler chafes):** wrap `--loop` mode with
   [WinSW](https://github.com/winsw/winsw) or NSSM as a real Windows
   service. Document, don't build, until needed — pywin32 service code is
   a maintenance tax with no payoff at single-user scale.
3. **Operability basics:** rotating logs under `data/logs/`; `activist
   status` CLI subcommand printing queue counts, last fetch/post times, and
   lock state (the UI ops strip's data, for when the UI isn't running);
   exit codes that Task Scheduler can alert on.

### Tests
Lockfile mutual exclusion; `--once` exit codes (0 published-or-nothing-due,
nonzero on failures); `activist status` against a seeded store.

### Model fit
- **Sonnet:** all of it. The hard concurrency questions were answered in P1;
  this phase is packaging.

---

## Explicitly out of scope
Likes/boosts and follow-back flows (in `docs/TODO.md`, spec separately —
they need their own consent rules); media/image attachment; multi-identity
posting in one process (run two posters with two configs if DMV goes live);
content warnings/hashtag strategy (persona/policy question, not plumbing).
