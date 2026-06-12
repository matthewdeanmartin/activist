"""Parse RSS 2.0 / Atom files into NewsItems. Stdlib XML only."""

from __future__ import annotations

import hashlib
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from bs4 import BeautifulSoup

from .models import NewsItem

LOGGER = logging.getLogger(__name__)

ACTIVIST_NS = "https://github.com/matthewdeanmartin/activist/ns"
HINT_TAG = f"{{{ACTIVIST_NS}}}hint"
ATOM = "{http://www.w3.org/2005/Atom}"


def item_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def strip_html(text: str | None) -> str:
    return BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True)


def parse_hints(text: str | None) -> dict[str, str]:
    """Parse fixture-only hint grammar: ``key=value; key=value``."""
    hints: dict[str, str] = {}
    for part in (text or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        hints[key.strip()] = value.strip()
    return hints


def parse_feed(path: Path) -> list[NewsItem]:
    """Parse one feed file; a malformed feed degrades to an empty list."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        LOGGER.warning("Skipping unreadable feed %s: %s", path, exc)
        return []
    return parse_feed_bytes(data, source=path.stem)


def parse_feed_bytes(data: bytes, source: str) -> list[NewsItem]:
    """Parse a raw RSS/Atom body (live HTTP or file); malformed → empty list.

    ``source`` is a label for logs and the fallback feed title.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        LOGGER.warning("Skipping malformed feed %s: %s", source, exc)
        return []
    if root.tag == "rss":
        return _parse_rss(root, source)
    if root.tag == f"{ATOM}feed":
        return _parse_atom(root, source)
    LOGGER.warning("Skipping %s: unrecognized root element %r", source, root.tag)
    return []


def _parse_rss(root: ET.Element, source: str) -> list[NewsItem]:
    feed_title = root.findtext("channel/title") or source
    items: list[NewsItem] = []
    for el in root.findall("channel/item"):
        title = (el.findtext("title") or "").strip()
        url = (el.findtext("link") or "").strip()
        if not title or not url:
            LOGGER.warning("Skipping item without title/link in %s", source)
            continue
        items.append(
            NewsItem(
                id=item_id(url),
                feed=feed_title,
                title=title,
                url=url,
                published=(el.findtext("pubDate") or "").strip(),
                summary=strip_html(el.findtext("description")),
                hints=parse_hints(el.findtext(HINT_TAG)),
            )
        )
    return items


def _parse_atom(root: ET.Element, source: str) -> list[NewsItem]:
    feed_title = root.findtext(f"{ATOM}title") or source
    items: list[NewsItem] = []
    for el in root.findall(f"{ATOM}entry"):
        title = (el.findtext(f"{ATOM}title") or "").strip()
        link_el = el.find(f"{ATOM}link")
        url = (link_el.get("href") or "").strip() if link_el is not None else ""
        if not title or not url:
            LOGGER.warning("Skipping entry without title/link in %s", source)
            continue
        published = el.findtext(f"{ATOM}published") or el.findtext(f"{ATOM}updated") or ""
        summary = el.findtext(f"{ATOM}summary") or el.findtext(f"{ATOM}content") or ""
        items.append(
            NewsItem(
                id=item_id(url),
                feed=feed_title,
                title=title,
                url=url,
                published=published.strip(),
                summary=strip_html(summary),
                hints=parse_hints(el.findtext(HINT_TAG)),
            )
        )
    return items


def parse_fixtures_dir(fixtures_dir: Path) -> list[NewsItem]:
    """Parse every ``*.xml`` feed in a directory, sorted by filename."""
    items: list[NewsItem] = []
    for feed_path in sorted(fixtures_dir.glob("*.xml")):
        items.extend(parse_feed(feed_path))
    return items
