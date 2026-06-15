import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import httpx

from policy_fetcher.fetcher import HEADERS

logger = logging.getLogger(__name__)

__all__ = [
    "DIRECTORY_URL",
    "fetch_instance_directory",
    "merge_servers_txt",
    "main",
]

# Public, unauthenticated directory of Mastodon servers maintained by
# joinmastodon.org. Same trust level as the hand-picked servers.txt entries.
DIRECTORY_URL = "https://api.joinmastodon.org/servers"


async def fetch_instance_directory(client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """Fetch the joinmastodon.org server directory.

    Returns the raw list of entries (each with at least a "domain" key).
    Raises httpx.HTTPError on network/HTTP failure; callers should handle it.
    """
    response = await client.get(DIRECTORY_URL)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected directory response shape: {type(data)!r}")
    return data


def merge_servers_txt(
    entries: Sequence[Dict[str, Any]],
    existing: Sequence[str],
    *,
    min_users: int = 0,
    languages: Optional[Sequence[str]] = None,
    categories: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> List[str]:
    """Return new domains (not in `existing`) to append to servers.txt.

    Pure function, no I/O. `entries` is the raw joinmastodon directory list.
    Filters are applied in order: min_users, languages, categories, then
    limit caps the number of *new* domains returned. Result is sorted.
    """
    existing_set = {d.strip().lower() for d in existing if d.strip()}
    seen: set[str] = set()
    candidates: List[str] = []

    for entry in entries:
        domain = str(entry.get("domain", "")).strip().lower()
        if not domain or domain in existing_set or domain in seen:
            continue

        if min_users and int(entry.get("total_users", 0) or 0) < min_users:
            continue

        if languages:
            entry_languages = {
                str(lang).lower() for lang in entry.get("languages", []) or []
            }
            if not entry_languages & {lang.lower() for lang in languages}:
                continue

        if categories:
            entry_categories = {
                str(cat).lower() for cat in entry.get("categories", []) or []
            }
            if not entry_categories & {cat.lower() for cat in categories}:
                continue

        seen.add(domain)
        candidates.append(domain)

    candidates.sort()
    if limit is not None:
        candidates = candidates[:limit]
    return candidates


async def _run(args: argparse.Namespace) -> int:
    server_list_path: Path = args.append
    existing: List[str] = []
    if server_list_path.exists():
        raw = server_list_path.read_text(encoding="utf-8")
        existing = [line.strip() for line in raw.splitlines() if line.strip()]

    try:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=15.0, follow_redirects=True
        ) as client:
            entries = await fetch_instance_directory(client)
    except (httpx.HTTPError, ValueError) as e:
        logger.error(f"Failed to fetch instance directory: {e}")
        return 1

    new_domains = merge_servers_txt(
        entries,
        existing,
        min_users=args.min_users,
        languages=args.languages,
        categories=args.categories,
        limit=args.limit,
    )

    if not new_domains:
        logger.info("No new domains to add.")
        return 0

    merged = sorted(set(existing) | set(new_domains))
    server_list_path.write_text("\n".join(merged) + "\n", encoding="utf-8")
    logger.info(
        f"Added {len(new_domains)} new domain(s); {len(merged)} total in {server_list_path}."
    )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover Mastodon instances from the joinmastodon.org directory"
    )
    parser.add_argument(
        "--append",
        type=Path,
        required=True,
        help="Path to servers.txt to read existing domains from and append new ones to",
    )
    parser.add_argument(
        "--min-users",
        type=int,
        default=0,
        help="Only include instances with at least this many total_users (default: 0)",
    )
    parser.add_argument(
        "--language",
        dest="languages",
        action="append",
        help="Only include instances advertising this language (repeatable)",
    )
    parser.add_argument(
        "--category",
        dest="categories",
        action="append",
        help="Only include instances in this category (repeatable)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of new domains to add",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
