"""Shared API state + lazy builders (spec/admin_site.md §2).

The FastAPI app holds the same objects the Flask app holds in app.config: the
Store (only queue access), the AppConfig, and a lazily-built moderation context
for edit re-checks. We keep them on app.state so create_api can inject test
doubles, mirroring web.create_app's store/mod_ctx parameters.
"""

from __future__ import annotations

from fastapi import Request

from ..config import AppConfig
from ..moderation import ModerationContext
from ..store import Store


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_cfg(request: Request) -> AppConfig:
    return request.app.state.cfg


def get_mod_ctx(request: Request) -> ModerationContext:
    """Built on first edit/recheck so read-only browsing never needs persona/
    policy files (same lazy posture as web/views.py:_mod_ctx)."""
    ctx = getattr(request.app.state, "mod_ctx", None)
    if ctx is None:
        from .. import state
        from ..moderation.policies import load_app_policy, load_instance_policy

        cfg: AppConfig = request.app.state.cfg
        persona = state.load_persona(cfg.persona_dir / "persona.toml")
        ctx = ModerationContext(
            disclosure=persona.disclosure,
            app_policy=load_app_policy(cfg.app_policy),
            instance_policies={
                domain: load_instance_policy(cfg.policies_dir, domain)
                for domain in cfg.instances
            },
        )
        request.app.state.mod_ctx = ctx
    return ctx


def get_llm_moderator(request: Request):
    moderator = getattr(request.app.state, "llm_moderator", None)
    if moderator is None:
        from ..moderation.openrouter_mod import OpenRouterModerator

        cfg: AppConfig = request.app.state.cfg
        moderator = OpenRouterModerator(model=cfg.model)
        request.app.state.llm_moderator = moderator
    return moderator
