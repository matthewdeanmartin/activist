"""Cheap keyword pre-filter shared by all engines.

Runs before any LLM tokens are spent. A topic matches when any of its
synonyms appears (word-bounded) in the item's title + summary.
"""

from __future__ import annotations

import re

from .models import NewsItem

SYNONYMS: dict[str, list[str]] = {
    "heat pumps": ["heat pump", "heat pumps", "heatpump", "mini-split", "cold-climate", "cop"],
    "e-bikes": ["e-bike", "e-bikes", "ebike", "ebikes", "electric bike", "electric bikes", "cargo bike", "cargo bikes"],
    "induction stoves": ["induction", "gas stove", "gas stoves", "cooktop", "cooktops", "electric range"],
    "home insulation": ["insulation", "insulate", "weatherization", "air sealing", "air-sealing", "retrofit", "retrofits"],
    "EVs": ["electric vehicle", "electric vehicles", "ev", "evs", "electric car", "electric cars", "charging network"],
    "rooftop solar": ["rooftop solar", "solar", "solar panel", "solar panels", "photovoltaic", "net metering"],
    "transit": ["transit", "bus rapid transit", "light rail", "rail", "subway", "bus lane", "bus lanes"],
    "low-carbon diet": ["plant-based", "beef", "food emissions", "diet"],
}


def match_topics(item: NewsItem, topics: list[str]) -> list[str]:
    """Return the persona beats this item touches, in beats order."""
    text = f"{item.title} {item.summary}".lower()
    matched: list[str] = []
    for topic in topics:
        synonyms = SYNONYMS.get(topic, []) or [topic.lower()]
        for syn in synonyms:
            if re.search(rf"\b{re.escape(syn)}\b", text):
                matched.append(topic)
                break
    return matched


def is_relevant(item: NewsItem, topics: list[str]) -> bool:
    return bool(match_topics(item, topics))
