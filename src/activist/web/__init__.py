"""Local review dashboard (admin UI Phases U1+U2).

Single user, localhost, no auth. The store is the only queue access; the UI
reads persona/ only to build the moderation context for edit re-checks, and
never touches the Mastodon API.
"""

from __future__ import annotations

import os

from flask import Flask

from ..config import AppConfig
from ..moderation import ModerationContext, ModeratorEngine
from ..store import Store


def create_app(
    cfg: AppConfig,
    store: Store | None = None,
    mod_ctx: ModerationContext | None = None,
    llm_moderator: ModeratorEngine | None = None,
) -> Flask:
    app = Flask(__name__)
    # Only flash messages ride the session; localhost, single user, so a
    # per-process key is all that's needed.
    app.secret_key = os.urandom(16)
    app.config["STORE"] = store if store is not None else Store(cfg.db_path)
    app.config["APP_CFG"] = cfg
    app.config["MOD_CTX"] = mod_ctx
    app.config["LLM_MODERATOR"] = llm_moderator
    from .views import bp

    app.register_blueprint(bp)
    return app
