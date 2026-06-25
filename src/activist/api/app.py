"""FastAPI app factory for the admin site (spec/admin_site.md §1-2).

create_api mirrors web.create_app: it accepts the same injectable doubles
(store, mod_ctx, llm_moderator) so tests run against a seeded temp Store. The
built Angular SPA is served from admin-web/dist if present; otherwise the API
still runs and the root explains how to build it.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..config import AppConfig
from ..moderation import ModerationContext, ModeratorEngine
from ..store import Store
from . import persona_routes, queue_routes

# admin-web/dist/admin-web/browser/ relative to the repo root. Resolved from the
# package location: src/activist/api/app.py -> repo root is parents[3].
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SPA_DIR = _REPO_ROOT / "admin-web" / "dist" / "admin-web" / "browser"

_NO_SPA_HTML = """<!doctype html><meta charset=utf-8>
<title>activist admin</title>
<body style="font-family:system-ui;max-width:40rem;margin:3rem auto;line-height:1.5">
<h1>activist admin API</h1>
<p>The API is running. The Angular app isn't built yet.</p>
<pre>cd admin-web &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p>Then reload. Meanwhile the JSON API lives under
<a href="/api/profile">/api/profile</a> and the docs at
<a href="/docs">/docs</a>.</p>
</body>"""


def create_api(
    cfg: AppConfig,
    store: Store | None = None,
    mod_ctx: ModerationContext | None = None,
    llm_moderator: ModeratorEngine | None = None,
    dev_cors: bool = False,
) -> FastAPI:
    app = FastAPI(title="activist admin", version="0.1.0")
    app.state.cfg = cfg
    app.state.store = store if store is not None else Store(cfg.db_path)
    app.state.mod_ctx = mod_ctx
    app.state.llm_moderator = llm_moderator

    # CORS only in dev, only for the Angular dev server on localhost. In the
    # shipped form the SPA is same-origin (served below), so CORS is off.
    if dev_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(queue_routes.router)
    app.include_router(persona_routes.router)

    # Serve the built SPA at / (after the /api routers so they win). With
    # html=True, StaticFiles falls back to index.html for client-side routes.
    if _SPA_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(_SPA_DIR), html=True), name="spa")
    else:

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def _no_spa() -> str:
            return _NO_SPA_HTML

    return app
