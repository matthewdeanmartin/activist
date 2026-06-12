# From POC to Real Thing: Shared Architecture

**Status:** plan, 2026-06-11. Companion docs: `fetcher_service.md`,
`admin_ui.md`, `poster_service.md` — each with its own phases.
**Constraints for this round:** single user, local only, no auth,
**no live publishing to Mastodon** (read-only API calls and search are fine;
credentials exist in `.env` as `MASTODON_ID_{NAME}_{FIELD}`).

---

## 1. The three components

```
                ┌──────────────────────────────────────────────┐
                │ activist.toml (config) + .env (secrets)      │
                └──────────────────────────────────────────────┘
                       │                  │                │
   live RSS ──▶ [fetcher_service] ─▶ ┌─────────┐ ◀─ [admin_ui]  human
   mastodon ──▶  (news + replies     │ SQLite  │     approve / reject /
   mentions      → engine → mod      │ queue   │     edit / browse history
   (read-only)   → pending queue)    └─────────┘
                                          │ approved
                                          ▼
                                    [poster_service]
                                    scheduled publish (dry-run transport
                                    until the live gate is opened)
```

All three are subcommands of the existing `activist` CLI (`activist fetch`,
`activist ui`, `activist poster`) sharing one package, one config, one store.
No microservices — three entry points over the same library.

## 2. What stays from the POC (unchanged)

- **Engine seam** (`engine/base.py`, MockBot default, OpenRouter rotation
  free→paid). Tests keep pinning to `tests/seed_opinions.toml`.
- **Moderation** (`moderation/`): MockModerator always runs; LLM moderation
  layered on top. Flags never drop posts.
- **Rate limiting is ordinary code** (`ratelimit.py`) — never moderation,
  never prompt text. The poster honors the same slot spacing.
- **Consent gates in code** (`replies.py`): explicit summon, `#nobot`,
  no bot-to-bot, dedupe — all before any engine sees a mention.
- **Persona state stays TOML/JSONL under git** (`persona/`): opinions,
  seen/said/mentions memory, diary. Reviewable diffs are the point.
- The **unverified-link rule**: any URL in a reply that the pipeline did not
  supply gets flagged (a model once invented a citation).

## 3. What changes: the content queue moves to SQLite

The POC's per-run `out/<date>/feed.toml` cannot be the queue for the real
thing: three processes (fetcher, UI, poster) read/write content states
concurrently, and "pending" must survive across runs. The queue becomes a
single SQLite database (stdlib `sqlite3`, WAL mode, zero new deps) at
`data/activist.db` (gitignored).

**Division of truth:**

| Store | Holds | Why |
|---|---|---|
| `data/activist.db` | content lifecycle: drafts, flags, approvals, edits, publish records | concurrent access, status transitions |
| `persona/` (git) | opinions, memory, diary | bot identity; diffs are the review surface |
| `out/<date>/` | optional debug artifacts (feed.toml/html per run) | kept during transition, then demoted |

### Content lifecycle (one `status` column, enforced in `store.py`)

```
pending_review ──approve──▶ approved ──poster──▶ published
      │                        │                     ▲
      └──reject──▶ rejected    └──poster error──▶ failed ──retry──▶ approved
```

- Bot output lands as `pending_review` (moderation flags already attached).
- Human may **edit** before approving; original text is preserved
  (`original_text`), MockModerator re-runs automatically on save.
- `rejected` is kept forever (audit + future few-shot material), never deleted.
- `published` records `mastodon_status_id` + `published_at`.
- Legal transitions are enforced in one function; everything else is a bug.

### Schema sketch (`store.py`)

```sql
CREATE TABLE content (
  id TEXT PRIMARY KEY,           -- DraftPost.id
  kind TEXT NOT NULL,            -- 'post' | 'reply'
  status TEXT NOT NULL,          -- lifecycle above
  text TEXT NOT NULL,
  original_text TEXT,            -- set on first human edit
  created TEXT NOT NULL,
  scheduled_for TEXT,            -- ratelimit slot
  source_url TEXT, source_title TEXT,
  opinion_keys TEXT,             -- JSON array
  opinion_change TEXT,           -- JSON object or NULL
  flags TEXT,                    -- JSON array of moderation flags
  engine TEXT,
  identity TEXT NOT NULL,        -- 'TECH' | 'DMV' → MASTODON_ID_* env keys
  in_reply_to_status_id TEXT,    -- real Mastodon status id (replies only)
  reply_to_author TEXT, reply_to_text TEXT,
  mastodon_status_id TEXT, published_at TEXT,
  rejected_reason TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE event_log (         -- append-only audit trail
  ts TEXT, content_id TEXT, actor TEXT,  -- 'human' | 'fetcher' | 'poster'
  action TEXT, detail TEXT
);
```

## 4. `activist.toml` — the one config file

Repo root, human-edited, committed. Secrets stay in `.env`
(loaded via existing python-dotenv; note the `export ` prefixes — dotenv
handles them).

```toml
[identity]
mastodon_id = "TECH"            # picks MASTODON_ID_TECH_* from .env
instances = ["mastodon.social"] # policy + pacing targets (policies/<d>.txt)

[fetch]
interval_minutes = 60
cache_dir = ".cache/feeds"      # ETag/Last-Modified conditional GET cache

[[feed]]
name = "CleanTechnica"
url  = "https://cleantechnica.com/feed/"

[[feed]]
name = "Canary Media"
url  = "https://www.canarymedia.com/rss"

[replies]
enabled = true
interval_minutes = 15

[engine]
name = "openrouter"             # mockbot stays default for tests
# model = "..."                 # else OPENROUTER_* rotation from .env

[moderation]
engine = "mockmod"              # "openrouter" layers LLM judgment on top

[ui]
host = "127.0.0.1"
port = 8765

[poster]
live = false                    # HARD GATE — see poster_service.md
check_interval_minutes = 5
```

`config.py` loads + validates this once; every entry point takes
`--config activist.toml`. CLI flags override config; config overrides
defaults. The POC's fixture-driven commands keep working without the file.

## 5. Mastodon client: thin httpx wrapper, split by capability

`mastodon_client.py` over the existing `httpx` dependency (no `Mastodon.py`
dep needed for ~6 endpoints). Two classes so "cannot publish yet" is a type-
level guarantee, not a flag check:

- `MastodonReader` — `verify_credentials`, `notifications(types=mention)`,
  `search`, `status(id)`. This is all the fetcher and this round ever needs.
- `MastodonPublisher(MastodonReader)` — `post_status` (with `Idempotency-Key`
  header), only constructed by the poster, and only when the live gate opens
  (poster_service.md Phase P2). **Not implemented this round beyond a stub
  that raises.**

Credential loading: `identity.mastodon_id` → reads the four
`MASTODON_ID_<NAME>_*` vars; fails fast with a clear message if any missing.

## 6. Build order across the three docs

1. **fetcher_service F1** (config + store + live RSS) — foundation everything
   else sits on.
2. **admin_ui U1** (read-only dashboard) — early eyes on real queue data.
3. **fetcher_service F2–F3** (pipeline → store; replies fetch).
4. **admin_ui U2** (approve/reject/edit).
5. **poster_service P1** (scheduler + dry-run transport).
6. **admin_ui U3**, **fetcher F4**, **poster P2–P3** as needed; P2's live
   publish stays gated until you say go.

## 7. Opus vs Sonnet — summary

**Opus (design-heavy, mistakes are expensive):** store schema + lifecycle
transition rules and their concurrency story (§3); the
pipeline refactor that swaps feed.toml for the store sink (fetcher F2);
Mastodon error/idempotency semantics for publishing (poster P2); edit →
re-moderate flow semantics (admin U2 design only).

**Sonnet (well-specified, pattern-following):** config loader, conditional-GET
RSS fetching, article digester, all Flask routes/templates/CSS, scheduler
loop, Task Scheduler wiring, tests mirroring existing suites, CLI plumbing.

Per-phase call-outs live in each companion doc.
