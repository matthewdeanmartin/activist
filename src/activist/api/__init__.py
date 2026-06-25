"""FastAPI + Angular admin site (spec/admin_site.md).

A JSON API over store.py plus the persona/account/engine "triple", serving the
built Angular SPA. Additive to the Flask UI (web/) — same store, no lifecycle
changes.
"""

from __future__ import annotations

from .app import create_api

__all__ = ["create_api"]
