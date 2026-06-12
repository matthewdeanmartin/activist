"""Turn fetched articles into something digestible for an engine.

Ordinary code, no LLM: normalize whitespace, cap length, and (optionally)
replace a thin RSS summary with text extracted from the article page itself.
Output stays a NewsItem — only ``summary`` gets better.
"""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from .models import NewsItem

LOGGER = logging.getLogger(__name__)

SUMMARY_CAP = 2000  # chars; roughly what an engine prompt should carry
_BOILERPLATE_TAGS = ("script", "style", "nav", "header", "footer", "aside", "form")


def normalize_text(text: str) -> str:
    """Collapse whitespace runs; the bs4 strip at ingest already removed tags."""
    return re.sub(r"\s+", " ", text or "").strip()


def truncate(text: str, cap: int = SUMMARY_CAP) -> str:
    """Cap at the last word boundary before ``cap``, with an ellipsis."""
    if len(text) <= cap:
        return text
    cut = text.rfind(" ", 0, cap)
    if cut <= 0:
        cut = cap
    return text[:cut].rstrip() + "…"


def extract_article_text(html: str) -> str:
    """Best-effort body extraction: <article>/<main>, else og:description."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_BOILERPLATE_TAGS):
        tag.decompose()
    container = soup.find("article") or soup.find("main")
    if container is not None:
        text = normalize_text(container.get_text(" ", strip=True))
        if len(text) > 100:  # too short means we grabbed chrome, not the story
            return text
    meta = soup.find("meta", attrs={"property": "og:description"})
    if meta is not None and meta.get("content"):
        return normalize_text(str(meta["content"]))
    return ""


def digest_item(
    item: NewsItem,
    client: httpx.Client | None = None,
    fetch_body: bool = False,
) -> NewsItem:
    """Normalize (and optionally enrich) one item's summary, in place."""
    summary = normalize_text(item.summary)
    if fetch_body and client is not None:
        try:
            resp = client.get(item.url, follow_redirects=True)
            resp.raise_for_status()
            body = extract_article_text(resp.text)
            # Prefer the article body only when it actually says more.
            if len(body) > len(summary):
                summary = body
        except httpx.HTTPError as exc:
            LOGGER.warning("Article fetch failed for %s (%s); keeping RSS summary", item.url, exc)
    item.summary = truncate(summary)
    return item
