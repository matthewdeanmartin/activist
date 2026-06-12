"""Load policy texts for moderation.

Machine-readable extraction (hourly limits) lives in activist.ratelimit:
rate limiting is enforced by the scheduler, not judged by the moderator.
"""

from __future__ import annotations

import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def load_app_policy(path: Path) -> str:
    if not path.is_file():
        LOGGER.warning("App policy not found: %s", path)
        return ""
    return path.read_text(encoding="utf-8")


def load_instance_policy(policies_dir: Path, instance: str) -> str:
    path = policies_dir / f"{instance}.txt"
    if not path.is_file():
        raise FileNotFoundError(
            f"No policy file for instance {instance!r} at {path} "
            f"(fetch it with: python -m policy_fetcher)"
        )
    return path.read_text(encoding="utf-8")
