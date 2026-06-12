"""Persona engines. MockBot is the deterministic default."""

from __future__ import annotations

from .base import PersonaEngine
from .mockbot import MockBot

__all__ = ["PersonaEngine", "MockBot", "get_engine"]


def get_engine(name: str, model: str | None = None) -> PersonaEngine:
    if name == "mockbot":
        return MockBot()
    if name == "openrouter":
        from .openrouter import OpenRouterBot  # lazy: needs openai + API key

        return OpenRouterBot(model=model)
    raise ValueError(f"Unknown engine: {name!r}")
