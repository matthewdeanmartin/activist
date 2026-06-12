# Admin UI Plan

**Status:** plan, 2026-06-11. Shared decisions in `real_overview.md`.
**Job:** the human approval queue as a tiny local website: browse everything
(pending / approved / rejected / published / failed), approve or reject,
edit before approving, see moderation flags and opinion changes.
Single user, localhost only, no auth.

---

## Framework choice: Flask

Compact, boring, well-understood; one new runtime dep (`flask`), Jinja2
included. Runs as `activist ui` via `app.run(host, port)` from
`[ui]` config — the dev server is exactly right for single-user localhost.
(Bottle would be one dep smaller but Flask's blueprints/templates/test client
are worth it; FastAPI is overkill — there's no API consumer and no async
need. The `HOST`/`PORT`/`DEBUG` vars already in `.env` slot straight in.)

Structure:

```
src/activist/web/
    __init__.py      # create_app(config) factory
    views.py         # routes
    templates/       # Jinja2; visual language ported from feed.html.tmpl
    static/style.css # inline CSS from the POC template, extracted
```

The store (`store.py`) is the only data access — the UI never touches
`persona/` or the Mastodon API in Phases U1–U2.

---

## Phase U1 — Read-only dashboard ✅ implemented 2026-06-11

See real queue data early; ships right after fetcher F1/F2 produce rows.

### Deliverables

1. **Queue list** `/` — tabs or filter bar by status (`pending_review`
   default), newest first: text preview, kind badge (post/reply), char count
   (green ≤500 / red over), flag count by severity, scheduled slot, engine,
   identity.
2. **Detail view** `/content/<id>` — full text; source link; moderation
   flags as the POC's purple strip; opinion-change strip (old stance ▸ new
   stance ▸ reason) like `feed.html.tmpl`; for replies, the quoted
   "↩ replying to" block; the item's `event_log` trail at the bottom.
3. **Published archive** `/published` — everything that went live (dry-run
   or real), with `published_at` and (later) a link to the Mastodon status.
4. **Run/ops glance** — header strip: counts per status, last fetch time
   (from `event_log`), poster status.
5. **CLI:** `activist ui [--config activist.toml]`; prints the URL.

### Tests
Flask test client against a seeded temp store: each status renders, flags
and opinion changes appear, HTML-escaping of post text and source titles
(same concern `test_render.py` covers — reuse its cases).

### Model fit
- **Sonnet:** the whole phase — routes, templates, CSS port, tests. No
  design risk; the POC HTML template is the visual spec.

---

## Phase U2 — Actions: approve, reject, edit

The actual human-in-the-loop. Plain HTML forms + POST/redirect — no JS
framework; a sprinkle of vanilla JS at most (char counter).

### Deliverables

1. **Approve** — button on detail + list rows. POST → `store.transition(id,
   pending_review→approved, actor='human')`. Approved items become the
   poster's input; UI shows their scheduled slot.
2. **Reject** — with optional free-text reason → `rejected_reason`. Rejected
   items are never deleted.
3. **Edit** — textarea on the detail view (live char counter vs 500):
   - First edit preserves `original_text`; `event_log` records each save.
   - **On save, MockModerator re-runs automatically** and flags are
     replaced — an edit can introduce a violation (length, stripped
     disclosure footer, added URL in a reply → unverified-link). A
     "re-check with LLM" button triggers the OpenRouter moderator on demand
     (never automatic — costs money).
   - Editing is allowed in `pending_review` and `approved` (editing an
     approved item keeps it approved but re-flags; see concurrency note).
   - `published` and `rejected` are read-only (a rejected item can be edited
     only via reject → back to `pending_review`? No — keep it simple:
     rejected is terminal; re-generate instead).
4. **Approve-to-queue semantics with the poster.** The poster must never
   publish a row the human is mid-editing. Rule: the poster claims a row by
   transitioning `approved→publishing` (new transient status) inside one
   transaction; the UI's edit/un-approve POST does a compare-and-swap on
   `status` and fails politely ("the poster just picked this up") if it
   lost the race. This is the one genuinely subtle piece of the UI.
5. **Un-approve** — `approved→pending_review`, same CAS rule.

### Tests
Transition matrix via test client (every button on every status — illegal
ones 404/409); edit re-moderation (introduce an over-limit edit → error flag
appears; strip footer → flag); original_text preserved across multiple
edits; CAS race simulated with a direct store write between GET and POST.

### Model fit
- **Opus:** item 4 only — the claim/CAS protocol between UI and poster
  (decide it once, document it in `store.py`; it also constrains poster P1).
- **Sonnet:** everything else — forms, transitions, re-moderation hook,
  tests. The transition function from fetcher F1 already enforces legality,
  so the routes are thin.

---

## Phase U3 — Quality of life

Pick-and-choose; nothing here blocks the poster.

### Deliverables (candidates)

1. **Edit diff view** — `difflib.HtmlDiff` of `original_text` vs `text` on
   the detail page.
2. **Filter/search** — by kind, identity, topic (opinion_keys), text
   substring; SQLite `LIKE` is plenty.
3. **Manual triggers** — "Fetch now" / "Run replies now" buttons that invoke
   the fetcher in a background thread with output captured to the ops
   strip. (Subprocess `uv run activist fetch`, not in-process — keeps the
   UI responsive and the fetcher lockfile honest.)
4. **Bulk actions** — approve/reject checkboxes on the list view.
5. **Opinion browser** — read-only view of `persona/opinions.toml` with
   history timelines (this is the only `persona/` read in the UI; still
   no writes — opinions change via git/bot only).
6. **Reschedule** — edit `scheduled_for` on approved items (validated
   against the ratelimit spacing for the identity — reuse `ratelimit.py`,
   ordinary code as ever).

### Model fit
- **Sonnet:** all of it. Item 6 should reuse the slot validator from
  fetcher F2 rather than reimplementing — flag for review if it can't.

---

## Explicitly out of scope
Auth/sessions (localhost, single user), HTTPS, mobile styling beyond
"readable", websockets/live refresh (meta-refresh or manual reload is fine),
creating content from scratch in the UI (the bot writes, the human edits —
if you want hand-authored posts, that's a new feature to spec separately).
