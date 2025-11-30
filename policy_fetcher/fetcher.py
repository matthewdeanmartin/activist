import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

import httpx
from bs4 import BeautifulSoup

# -- Logging Setup --
logger = logging.getLogger(__name__)


# -- Custom Exceptions --
class PolicyFetchError(Exception):
    pass


class InstanceUnreachableError(PolicyFetchError):
    pass


__all__ = [
    'ensure_policy_dir',
    'save_policy',
    'fetch_policy',
    'get_cached_policy',
    'fetch_many',
    'PolicyFetchError',
    'InstanceUnreachableError'
]

# -- Configuration --
# User-Agent is polite and prevents some default-blocking by WAFs
HEADERS = {
    "User-Agent": "MastodonPolicyFetcher/1.0 (+https://github.com/your/repo)",
    "Accept": "application/json"
}


def ensure_policy_dir(directory: Path) -> None:
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)


def clean_html(html_text: str) -> str:
    """Converts HTML chunks (from API responses) into plain text."""
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    return soup.get_text(separator="\n", strip=True)


async def _get_json(client: httpx.AsyncClient, url: str) -> Optional[Dict[str, Any]]:
    """Helper to fetch JSON safely."""
    try:
        response = await client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


async def fetch_policy(domain: str, directory: Path, force_refresh: bool = False) -> str:
    """
    Fetches policy via Mastodon API:
    1. /api/v2/instance (General info + Rules)
    2. /api/v1/instance/extended_description (Long 'About' text)
    """
    ensure_policy_dir(directory)

    # Clean domain input
    domain = domain.replace("https://", "").replace("http://", "").strip().rstrip("/")

    # 1. Check Cache
    if not force_refresh:
        cached_text = await get_cached_policy(domain, directory)
        if cached_text:
            return cached_text

    logger.info(f"Fetching policy for {domain} via API...")

    async with httpx.AsyncClient(headers=HEADERS, timeout=15.0, follow_redirects=True) as client:
        # Construct Endpoints
        # Try v2 first (standard for modern Mastodon)
        base_url = f"https://{domain}"
        instance_url = f"{base_url}/api/v2/instance"
        desc_url = f"{base_url}/api/v1/instance/extended_description"

        try:
            # Run requests concurrently
            instance_data, ext_desc_data = await asyncio.gather(
                _get_json(client, instance_url),
                _get_json(client, desc_url)
            )

            # Fallback for older instances (v1) if v2 failed
            if not instance_data:
                logger.info(f"v2 API failed for {domain}, trying v1...")
                instance_data = await _get_json(client, f"{base_url}/api/v1/instance")

            if not instance_data:
                raise InstanceUnreachableError(f"Could not retrieve instance data for {domain}")

        except Exception as e:
            logger.error(f"Network error fetching {domain}: {e}")
            raise InstanceUnreachableError(f"Network error: {e}")

    # -- Parse Data --
    lines = []

    # Title & Domain
    title = instance_data.get("title", domain)
    lines.append(f"=== POLICY REPORT: {title} ({domain}) ===\n")

    # 1. Server Rules (The most important part)
    rules = instance_data.get("rules", [])
    if rules:
        lines.append("## SERVER RULES")
        for rule in rules:
            # Rules object structure: {'id': '1', 'text': '...'}
            r_text = rule.get("text", "")
            lines.append(f"- {r_text}")
        lines.append("")  # Spacer

    # 2. Extended Description (The 'About' page text)
    # This is usually HTML, so we clean it.
    long_desc = ""
    if ext_desc_data and "content" in ext_desc_data:
        long_desc = ext_desc_data["content"]
    elif "description" in instance_data:
        # Fallback to short description
        long_desc = instance_data["description"]

    if long_desc:
        lines.append("## ABOUT / DESCRIPTION")
        lines.append(clean_html(long_desc))
        lines.append("")

    # 3. Contact Info
    contact = instance_data.get("contact", {})
    email = contact.get("email") or instance_data.get("email")
    if email:
        lines.append(f"## CONTACT: {email}")

    final_text = "\n".join(lines)

    # Save and Return
    await save_policy(domain, final_text, directory)
    return final_text


async def save_policy(domain: str, text: str, directory: Path) -> Path:
    file_path = directory / f"{domain}.txt"
    # Offload blocking I/O
    await asyncio.to_thread(file_path.write_text, text, encoding="utf-8")
    logger.info(f"Saved {file_path}")
    return file_path


async def get_cached_policy(domain: str, directory: Path) -> Optional[str]:
    file_path = directory / f"{domain}.txt"
    if file_path.exists():
        logger.debug(f"Cache hit for {domain}")
        return await asyncio.to_thread(file_path.read_text, encoding="utf-8")
    return None


async def fetch_many(domains: List[str], directory: Path) -> None:
    logger.info(f"Batch fetching {len(domains)} domains...")
    tasks = [fetch_policy(domain, directory) for domain in domains]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    success_count = 0
    for domain, res in zip(domains, results):
        if isinstance(res, Exception):
            logger.error(f"FAILED {domain}: {res}")
        else:
            success_count += 1
    logger.info(f"Batch complete. Success: {success_count}/{len(domains)}")