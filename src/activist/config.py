"""Load and validate activist.toml (see spec/real_overview.md §4).

Secrets never live here — they stay in .env. This file holds everything a
human should review in a diff: feeds, identity selection, intervals, ports.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    """activist.toml is missing, malformed, or fails validation."""


@dataclass
class FeedConfig:
    name: str
    url: str
    type: str = "rss"  # only rss/atom today; the field leaves the door open


@dataclass
class AppConfig:
    # [identity]
    mastodon_id: str = "TECH"  # selects MASTODON_ID_<id>_* from .env
    instances: list[str] = field(default_factory=list)
    # [fetch]
    fetch_interval_minutes: int = 60
    cache_dir: Path = Path(".cache/feeds")
    fetch_article_body: bool = False
    # [[feed]]
    feeds: list[FeedConfig] = field(default_factory=list)
    # [replies]
    replies_enabled: bool = False
    replies_interval_minutes: int = 15
    # [engine]
    engine: str = "mockbot"
    model: str | None = None
    # [moderation]
    moderation_engine: str = "mockmod"
    # [ui]
    ui_host: str = "127.0.0.1"
    ui_port: int = 8765
    # [poster]
    poster_live: bool = False  # hard gate; see spec/poster_service.md
    poster_check_interval_minutes: int = 5
    # [paths]
    db_path: Path = Path("data/activist.db")
    persona_dir: Path = Path("persona")
    out_dir: Path = Path("out")
    policies_dir: Path = Path("policies")


def load_config(path: Path) -> AppConfig:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc

    cfg = AppConfig()
    identity = data.get("identity", {})
    cfg.mastodon_id = str(identity.get("mastodon_id", cfg.mastodon_id)).upper()
    cfg.instances = list(identity.get("instances", []))

    fetch = data.get("fetch", {})
    cfg.fetch_interval_minutes = _positive_int(
        fetch.get("interval_minutes", cfg.fetch_interval_minutes), "fetch.interval_minutes"
    )
    cfg.cache_dir = Path(fetch.get("cache_dir", cfg.cache_dir))
    cfg.fetch_article_body = bool(fetch.get("article_body", cfg.fetch_article_body))

    for i, raw in enumerate(data.get("feed", [])):
        if "url" not in raw:
            raise ConfigError(f"[[feed]] #{i + 1} is missing 'url'")
        cfg.feeds.append(
            FeedConfig(
                name=raw.get("name", raw["url"]),
                url=raw["url"],
                type=raw.get("type", "rss"),
            )
        )

    replies = data.get("replies", {})
    cfg.replies_enabled = bool(replies.get("enabled", cfg.replies_enabled))
    cfg.replies_interval_minutes = _positive_int(
        replies.get("interval_minutes", cfg.replies_interval_minutes), "replies.interval_minutes"
    )

    engine = data.get("engine", {})
    cfg.engine = engine.get("name", cfg.engine)
    if cfg.engine not in ("mockbot", "openrouter"):
        raise ConfigError(f"engine.name must be 'mockbot' or 'openrouter', got {cfg.engine!r}")
    cfg.model = engine.get("model")

    moderation = data.get("moderation", {})
    cfg.moderation_engine = moderation.get("engine", cfg.moderation_engine)
    if cfg.moderation_engine not in ("mockmod", "openrouter"):
        raise ConfigError(
            f"moderation.engine must be 'mockmod' or 'openrouter', got {cfg.moderation_engine!r}"
        )

    ui = data.get("ui", {})
    cfg.ui_host = ui.get("host", cfg.ui_host)
    cfg.ui_port = _positive_int(ui.get("port", cfg.ui_port), "ui.port")

    poster = data.get("poster", {})
    cfg.poster_live = bool(poster.get("live", cfg.poster_live))
    cfg.poster_check_interval_minutes = _positive_int(
        poster.get("check_interval_minutes", cfg.poster_check_interval_minutes),
        "poster.check_interval_minutes",
    )

    paths = data.get("paths", {})
    cfg.db_path = Path(paths.get("db", cfg.db_path))
    cfg.persona_dir = Path(paths.get("persona", cfg.persona_dir))
    cfg.out_dir = Path(paths.get("out", cfg.out_dir))
    cfg.policies_dir = Path(paths.get("policies", cfg.policies_dir))
    return cfg


def _positive_int(value: object, name: str) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from exc
    if number <= 0:
        raise ConfigError(f"{name} must be positive, got {number}")
    return number
