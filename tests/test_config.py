"""activist.toml loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from activist.config import AppConfig, ConfigError, load_config


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "activist.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_repo_sample_config_loads(repo_root: Path):
    cfg = load_config(repo_root / "activist.toml")
    assert cfg.mastodon_id == "TECH"
    assert cfg.feeds and all(f.url.startswith("https://") for f in cfg.feeds)
    assert cfg.poster_live is False  # the hard gate ships closed


def test_defaults_from_empty_file(tmp_path: Path):
    cfg = load_config(write(tmp_path, ""))
    assert cfg == AppConfig()


def test_missing_file():
    with pytest.raises(ConfigError, match="not found"):
        load_config(Path("does/not/exist.toml"))


def test_feed_requires_url(tmp_path: Path):
    with pytest.raises(ConfigError, match=r"\[\[feed\]\] #1"):
        load_config(write(tmp_path, '[[feed]]\nname = "no url"\n'))


def test_feed_name_defaults_to_url(tmp_path: Path):
    cfg = load_config(write(tmp_path, '[[feed]]\nurl = "https://x.invalid/rss"\n'))
    assert cfg.feeds[0].name == "https://x.invalid/rss"


def test_bad_engine_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="engine.name"):
        load_config(write(tmp_path, '[engine]\nname = "gpt9"\n'))


def test_bad_moderation_engine_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="moderation.engine"):
        load_config(write(tmp_path, '[moderation]\nengine = "vibes"\n'))


def test_nonpositive_interval_rejected(tmp_path: Path):
    with pytest.raises(ConfigError, match="must be positive"):
        load_config(write(tmp_path, "[fetch]\ninterval_minutes = 0\n"))


def test_invalid_toml(tmp_path: Path):
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(write(tmp_path, "not = [toml"))


def test_mastodon_id_uppercased(tmp_path: Path):
    cfg = load_config(write(tmp_path, '[identity]\nmastodon_id = "dmv"\n'))
    assert cfg.mastodon_id == "DMV"
