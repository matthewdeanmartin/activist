# Admin Site (FastAPI API + Angular) Plan

**Status:** plan, 2026-06-19. Builds on `real_overview.md`, `admin_ui.md` (the
Flask U1/U2 dashboard), `store.py` (the lifecycle + CAS), and `personas.md`
(persona/account/engine separation).

**Job:** a richer single-page admin site that surfaces, in one place, the things
the Flask UI does not foreground:

1. **Who** is posting — the active **persona**, the Mastodon **account**
   (`mastodon_id`) it speaks through, and the **engine profile** (how richly it
   thinks). This is the `personas.md` triple made visible.
2. **What is coming up** — the **upcoming posts** (approved, scheduled, ordered
   by slot) and the pending-review queue, with their scheduled slots.
3. **The human-in-the-loop actions**, as buttons:
   - **Approve** (`pending_review → approved`)
   - **Edit and approve** (edit text, re-moderate, then approve in one click)
   - **Unapprove** (`approved → pending_review` — "delete and put back into queue")
   - **Edit** (re-moderates; pending or approved)
   - **Delete** (hard-remove a queue row that should never have existed)
   - **Reject** (with reason — terminal, kept as a record)
   - For **already-posted** items: **edit** and **delete** the live status.

> This is **additive**. The Flask UI (`activist ui`) stays. The new site is a
> second front-end over the *same* `store.py`, plus a thin read-only persona
> reader. Nothing about the lifecycle, CAS, or moderation changes.

Single user, localhost only, no auth (same posture as the Flask UI).

---

## 1. Why FastAPI + Angular (alongside Flask)

The boss asked for it explicitly. The split is clean:

- **FastAPI** (`src/activist/api/`) is a *pure JSON API* over `store.py`. No
  templates, no HTML. It is the natural home for the Angular client and, later,
  any other consumer (a phone, a TUI). Async is not needed — every call is a
  short SQLite transaction — but FastAPI's typed request/response models and
  automatic OpenAPI doc are worth it for a real API surface.
- **Angular** (`admin-web/`) is the SPA. It is built to static files and can be
  served by FastAPI itself (`StaticFiles`) so `activist api` serves both the API
  and the app on one port — no second server, no CORS in the normal case. In dev
  the Angular dev server (`ng serve`, port 4200) proxies `/api` to the FastAPI
  port, and CORS is opened only for `localhost` in dev.

Run model mirrors the existing services:

```
activist api --config activist.toml          # serves API + built SPA on [api].port
activist ui  --config activist.toml           # the old Flask dashboard (unchanged)
```

---

## 2. Layout

```
src/activist/api/
    __init__.py        # create_api(cfg, store=None, ...) factory (mirrors web.create_app)
    app.py             # FastAPI app, routers, StaticFiles mount, CORS (dev only)
    deps.py            # get_store / get_cfg / lazy moderation context
    schemas.py         # pydantic response/request models (ContentOut, PersonaOut, ...)
    queue_routes.py    # /api/queue, /api/content/{id}, actions
    persona_routes.py  # /api/personas, /api/account, /api/profile
    moderation.py      # shared edit-time re-moderation (ported from web/views.py)

admin-web/             # Angular workspace (built to admin-web/dist/)
    src/app/
      core/            # ApiService, models.ts (TS mirror of schemas.py)
      queue/           # queue-list, content-detail, action-bar components
      personas/        # persona/account/profile panel
    angular.json, package.json, tsconfig*.json, proxy.conf.json
```

The built SPA (`admin-web/dist/admin-web/browser/`) is what `activist api`
serves. If it isn't built, the API still runs and the root returns a friendly
"run `ng build` first" message — the API is useful on its own.

---

## 3. The API (versionless `/api`, JSON only)

All responses are JSON; errors use FastAPI's `HTTPException` with the same
meaning the Flask routes already encode.

### Read

| Method & path | Returns |
|---|---|
| `GET /api/profile` | active persona + account + engine profile (the `personas.md` triple) + status counts + last-fetch time. The dashboard header. |
| `GET /api/personas` | all personas discovered under the personas root (read-only). |
| `GET /api/account` | the active Mastodon account: `mastodon_id`, base_url, configured instances, and (if a token check is cheap/available) the verified handle. |
| `GET /api/queue?status=pending_review` | list of `ContentOut` for one status (default `pending_review`), newest first. |
| `GET /api/upcoming` | approved rows for the active identity, ordered by `scheduled_for` — **the upcoming-posts view**. Each carries its slot and whether it is due. |
| `GET /api/content/{id}` | one `ContentOut` plus its `event_log` trail. |
| `GET /api/counts` | `{status: n}` for the badge bar. |

### Actions (all mutate `store.py`; all CAS-safe)

| Method & path | Effect | Store call |
|---|---|---|
| `POST /api/content/{id}/approve` | pending → approved | `transition` |
| `POST /api/content/{id}/reject` `{reason}` | pending → rejected (reason kept) | `transition` |
| `POST /api/content/{id}/unapprove` | approved → pending ("put back into queue") | `transition` |
| `POST /api/content/{id}/retry` | failed → approved | `transition` |
| `POST /api/content/{id}/edit` `{text}` | re-moderate + replace text/flags (pending/approved) | `update_text` |
| `POST /api/content/{id}/edit-approve` `{text}` | edit (above) **then** approve, one click | `update_text` + `transition` |
| `POST /api/content/{id}/recheck-llm` | re-run flags via OpenRouter moderator on demand | `update_flags` |
| `DELETE /api/content/{id}` | **hard delete** a non-published queue row | `delete` (new) |

### Already-posted edit / delete (stubbed until poster P2)

The live Mastodon edit/delete API (`MastodonPublisher`) is **not built yet**
(see `poster_service.md` — P1 is dry-run only, P2 is the gated live publisher).
So these endpoints exist and the UI shows the buttons, but the live-status
operations return **501 Not Implemented** with a clear message, exactly like
`MastodonTransport` raising in `__init__` until P2.

| Method & path | Now | At P2 |
|---|---|---|
| `POST /api/content/{id}/edit-published` `{text}` | **501** "live edit lands with poster P2" | `PUT /statuses/{status_id}`, behind the triple gate |
| `DELETE /api/content/{id}/published` | **501** "live delete lands with poster P2" | `DELETE /statuses/{status_id}`, behind the triple gate |

The Angular buttons render but are **disabled with an explanatory tooltip**
until a `GET /api/profile` flag (`live_edit_available: false`) flips. When the
publisher arrives, only that flag and the two route bodies change.

> A note on **delete semantics**. There are now three distinct "remove" verbs,
> and the UI must not blur them:
> - **Unapprove** = `approved → pending_review`. Reversible. "Put it back in the
>   queue." (boss's "unapprove (which delete and put back into queue)").
> - **Reject** = terminal record with a reason; *never* row-deleted. (existing
>   principle, `store.py` docstring.)
> - **Delete** = a genuine hard `DELETE` of a row that should not exist at all
>   (a junk draft). New `store.delete`, refuses `publishing` and (locally)
>   `published` rows; the audit `event_log` row is preserved (delete the
>   `content` row, keep its history).

### CAS / error contract (unchanged meaning)

- `StaleStatus` → **409** `{"error": "stale", "detail": ...}` — the Angular
  client re-fetches and shows a polite "another process got there first" banner
  (the Flask flash, as JSON).
- `IllegalTransition` → **409** (a client bug; the button shouldn't have shown).
- `UnknownContent` → **404**. `NotEditable` → **409**.
- Live edit/delete pre-P2 → **501**.

---

## 4. `store.py` additions

Only one genuinely new capability, plus a read the upcoming view wants:

1. **`Store.delete(content_id, actor="human", allow_statuses=...)`** — hard
   delete with a status guard in the `DELETE ... WHERE id=? AND status IN (...)`
   so it can't race a poster claim. Default allows `pending_review`, `approved`,
   `failed`, `rejected`; refuses `publishing` and `published` (published is a
   receipt — see §3 note; live delete is the P2 path, not this one). Logs a
   `delete` event *before* removing the content row (or to a separate audit that
   survives), so the action is never silent.
2. **`Store.upcoming(identity)`** (or reuse `list_by_status(APPROVED)` filtered
   to identity + ordered by `scheduled_for`) — already expressible; add a thin
   helper rather than pushing ordering into the API layer.

`LEGAL_TRANSITIONS` is **untouched** — delete is not a transition, it's a row
removal, deliberately outside the lifecycle map.

---

## 5. Schemas (`schemas.py` ⇄ `models.ts`)

`ContentOut` is `ContentRow` as pydantic, plus the derived fields the Flask
templates compute (`char_count`, `error_flags`, `warn_flags`, an `is_reply`
bool, an `over_limit` bool at 500). `EventOut` mirrors `Event`. `ProfileOut`
carries persona name/handle/bio/disclosure, `mastodon_id`, engine name/model,
moderation engine, `poster_live`, `default_visibility`, `live_edit_available`,
and the status counts. The TS `models.ts` is a hand-kept mirror (small, stable).

The API never returns secrets — `.env` tokens never cross the wire; `account`
returns only `base_url` and the public handle from a read-only verify (or null).

---

## 6. Angular app

Minimal, standalone-components, no heavy state library — a single
`ApiService` (HttpClient) and component-local signals. Three areas:

1. **Profile header** — persona name·handle, account (`@handle@instance`),
   engine badge (`mockbot` / `openrouter:model`), live-gate indicator, and the
   status-count chips. This is the "who/what" surface.
2. **Queue + Upcoming** — a status tab bar (`pending_review` default) and a
   dedicated **Upcoming** tab that hits `/api/upcoming` and shows approved posts
   in slot order with a "due" marker. Rows show text preview, kind badge, char
   count (red over 500), flag counts, slot, engine, identity. Inline
   **Approve / Unapprove / Reject / Delete** buttons per row.
3. **Detail** — full text, source link, moderation-flag strip, opinion-change
   strip, reply context (quoted "↩ replying to" + visibility badge), event-log
   trail. A textarea editor with a live 500-char counter and the action bar:
   **Save (edit)**, **Edit & Approve**, **Recheck (LLM)**, plus the
   **Edit posted** / **Delete posted** buttons (disabled until
   `live_edit_available`).

A `409` from any action triggers a re-fetch + a non-blocking toast ("another
process changed this first"), matching the Flask CAS behavior exactly.

### Build / serve

- Dev: `ng serve` (4200) with `proxy.conf.json` → `http://127.0.0.1:<api port>`.
- Prod-ish: `ng build` → `admin-web/dist/admin-web/browser/`, served by FastAPI
  `StaticFiles` at `/`. `activist api` prints both URLs.

---

## 7. CLI + deps

- New subcommand **`activist api [--config activist.toml] [--host] [--port]`**
  → `uvicorn` running `create_api(cfg)`. Defaults from a new `[api]` config
  block (`host`, `port`, default `127.0.0.1:8675`), independent of `[ui]` so the
  Flask UI and the API can run side by side.
- New runtime deps: `fastapi`, `uvicorn[standard]`. (`pydantic` arrives with
  FastAPI.) Angular is a separate Node toolchain under `admin-web/`, not a
  Python dependency; the wheel ships the built static files like it already
  ships the Flask templates.

---

## 8. Tests

- **API**: FastAPI `TestClient` against a seeded temp `Store` (same fixtures the
  Flask tests use): every read returns the right shape; every action button on
  every status (legal → 200, illegal → 409/404); a direct store write between
  GET and POST proves the 409 CAS path; `edit` re-moderation introduces/clears a
  flag; `delete` refuses `publishing`/`published`; live edit/delete return 501.
- **store**: `delete` guard matrix (each status), event preserved.
- Angular: a couple of component specs (ApiService wiring, action-bar disables
  the posted buttons when `live_edit_available` is false). Light — the contract
  is enforced server-side.

---

## 9. Explicitly out of scope (now)

- Auth/HTTPS (localhost, single user — same as the Flask UI).
- **Real** live status edit/delete (poster P2; stubbed 501 here).
- Hand-authoring posts from scratch (the bot writes, the human edits — same
  stance as `admin_ui.md`).
- Multi-persona switching *in the running process* — the active persona is the
  one the loaded config selects (`personas.md` §2: one persona per process).
  `/api/personas` lists them read-only; switching means pointing at another
  config, as today.
```
