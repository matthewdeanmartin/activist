"""Who/what/how-richly routes: personas, account, profile (spec/admin_site.md §3).

Read-only. Personas live under git (state.py); the account's base_url comes from
.env via MastodonCredentials, but no token is ever returned. The verified handle
is best-effort: if a read-only check is cheap and succeeds we include it,
otherwise the field is null and the UI just shows the configured account.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from .. import state
from ..config import AppConfig
from ..store import Store
from .deps import get_cfg, get_store
from .schemas import (
    AccountOut,
    EngineProfileOut,
    EventOut,
    PersonaOut,
    ProfileOut,
)

log = logging.getLogger("activist.api")
router = APIRouter(prefix="/api", tags=["who"])

# Flips to True when the poster's live publisher (P2) lands and live status
# edit/delete become possible. Until then the UI disables those buttons.
LIVE_EDIT_AVAILABLE = False


def _persona_id(cfg: AppConfig) -> str:
    """The active persona's id = its directory name (personas.md §2)."""
    return cfg.persona_dir.name


def _load_persona_out(persona_dir: Path, active: bool) -> PersonaOut | None:
    toml = persona_dir / "persona.toml"
    if not toml.is_file():
        return None
    try:
        persona = state.load_persona(toml)
    except Exception as exc:  # a malformed persona shouldn't 500 the list
        log.warning("skipping persona %s: %s", persona_dir.name, exc)
        return None
    return PersonaOut(
        persona_id=persona_dir.name,
        name=persona.name,
        handle=persona.handle,
        bio=persona.bio,
        disclosure=persona.disclosure,
        active=active,
    )


@router.get("/personas", response_model=list[PersonaOut])
def list_personas(cfg: AppConfig = Depends(get_cfg)) -> list[PersonaOut]:
    """All personas discoverable beside the active one (read-only registry).

    Today persona_dir is a single dir (personas.md migration pending); we treat
    its parent as the registry root and list every child holding a persona.toml.
    """
    active_id = _persona_id(cfg)
    root = cfg.persona_dir.parent
    out: list[PersonaOut] = []
    seen: set[str] = set()
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "persona.toml").is_file():
                p = _load_persona_out(child, active=child.name == active_id)
                if p is not None:
                    out.append(p)
                    seen.add(child.name)
    if active_id not in seen:  # single-dir layout: ensure the active one is present
        p = _load_persona_out(cfg.persona_dir, active=True)
        if p is not None:
            out.append(p)
    return out


def _account(cfg: AppConfig, verify: bool = False) -> AccountOut:
    mastodon_id = cfg.mastodon_id
    base_url = ""
    handle = None
    verified = False
    try:
        from ..mastodon_client import MastodonCredentials

        creds = MastodonCredentials.from_env(mastodon_id)
        base_url = creds.base_url
        if verify:
            from ..mastodon_client import MastodonReader

            reader = MastodonReader(creds)
            try:
                account = reader.verify_credentials()
                handle = account.get("acct")
                verified = True
            finally:
                reader.close()
    except Exception as exc:  # missing creds / network — report what we have
        log.info("account info incomplete for %s: %s", mastodon_id, exc)
    return AccountOut(
        mastodon_id=mastodon_id,
        base_url=base_url,
        instances=list(cfg.instances),
        handle=handle,
        verified=verified,
    )


@router.get("/account", response_model=AccountOut)
def account(cfg: AppConfig = Depends(get_cfg)) -> AccountOut:
    # Verify is opt-in via this dedicated endpoint (it hits the network).
    return _account(cfg, verify=True)


@router.get("/profile", response_model=ProfileOut)
def profile(
    cfg: AppConfig = Depends(get_cfg), store: Store = Depends(get_store)
) -> ProfileOut:
    active_id = _persona_id(cfg)
    persona_out = _load_persona_out(cfg.persona_dir, active=True)
    if persona_out is None:
        raise HTTPException(500, f"active persona not loadable: {cfg.persona_dir}")
    last_fetch = store.last_event("fetch")
    return ProfileOut(
        persona=persona_out,
        account=_account(cfg, verify=False),  # cheap: no network on the header
        engine=EngineProfileOut(
            engine=cfg.engine,
            model=cfg.model,
            moderation_engine=cfg.moderation_engine,
            poster_live=cfg.poster_live,
            default_visibility=cfg.default_visibility,
        ),
        counts=store.counts(),
        last_fetch=EventOut.from_event(last_fetch) if last_fetch else None,
        live_edit_available=LIVE_EDIT_AVAILABLE,
    )
