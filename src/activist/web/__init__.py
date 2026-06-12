"""Local review dashboard (admin UI Phase U1 — read-only).

Single user, localhost, no auth. The store is the only data access; the UI
never touches persona/ or the Mastodon API in this phase.
"""

from __future__ import annotations

from flask import Flask

from ..config import AppConfig
from ..store import Store


def create_app(cfg: AppConfig, store: Store | None = None) -> Flask:
    app = Flask(__name__)
    app.config["STORE"] = store if store is not None else Store(cfg.db_path)
    app.config["APP_CFG"] = cfg
    from .views import bp

    app.register_blueprint(bp)
    return app
