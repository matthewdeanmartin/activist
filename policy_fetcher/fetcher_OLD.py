import asyncio
import logging
from pathlib import Path
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

# -- Logging Setup for Module --
logger = logging.getLogger(__name__)


# -- Custom Exceptions --
class PolicyFetchError(Exception):
    """Base exception for policy fetching errors."""
    pass


class InstanceUnreachableError(PolicyFetchError):
    """Raised when the network request fails."""
    pass


class PolicyNotFoundError(PolicyFetchError):
    """Raised when the page loads but policy content is missing."""
    pass


__all__ = [
    'ensure_policy_dir',
    'get_policy_url',
    'extract_policy_text',
    'save_policy',
    'fetch_policy',
    'get_cached_policy',
    'fetch_many',
    'PolicyFetchError',
    'InstanceUnreachableError',
    'PolicyNotFoundError'
]


def ensure_policy_dir(directory: Path) -> None:
    """Checks if directory exists; creates it if not."""
    if not directory.exists():
        logger.debug(f"Creating directory: {directory}")
        directory.mkdir(parents=True, exist_ok=True)
    else:
        logger.debug(f"Directory exists: {directory}")


def get_policy_url(domain: str) -> str:
    """Normalizes domain to the about page URL."""
    clean_domain = domain.strip().lower()
    if clean_domain.startswith("http"):
        # Strip scheme if provided to ensure consistency
        clean_domain = clean_domain.split("://")[-1]

    # Remove trailing slashes
    clean_domain = clean_domain.rstrip("/")
    return f"https://{clean_domain}/about"


def extract_policy_text(html_content: str) -> str:
    """Parses HTML to extract the rich formatting text from Mastodon /about pages."""
    try:
        soup = BeautifulSoup(html_content, "html.parser")

        # Remove scripts and styles
        for script in soup(["script", "style"]):
            script.decompose()

        # Target the standard Mastodon extended description container
        # Note: Mastodon versions vary, but .rich-formatting is standard for the long form text
        content_div = soup.find("div", class_="rich-formatting")

        if not content_div:
            # Fallback for older instances or different themes
            logger.debug("Class .rich-formatting not found, attempting fallback search.")
            content_div = soup.find("div", id="mastodon") or soup.body

        if not content_div:
            logger.error("Could not locate policy content in HTML.")
            raise PolicyNotFoundError("HTML structure invalid or content missing.")

        text = content_div.get_text(separator="\n", strip=True)
        logger.debug("Successfully extracted policy text.")
        return text

    except Exception as e:
        logger.debug(f"Parsing failed: {e}")
        raise PolicyNotFoundError(f"Failed to parse content: {e}")


async def save_policy(domain: str, text: str, directory: Path) -> Path:
    """Writes text to file asynchronously (offloaded to thread)."""
    file_path = directory / f"{domain}.txt"

    def _write():
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(text)

    # Run blocking I/O in a separate thread to avoid blocking the async event loop
    await asyncio.to_thread(_write)

    logger.info(f"Saved policy for {domain} to {file_path}")
    return file_path


async def get_cached_policy(domain: str, directory: Path) -> Optional[str]:
    """Returns the text if file exists, else None."""
    file_path = directory / f"{domain}.txt"
    if file_path.exists():
        logger.debug(f"Cache hit for {domain}")
        # Run blocking I/O in a thread
        return await asyncio.to_thread(file_path.read_text, encoding="utf-8")
    return None


async def fetch_policy(domain: str, directory: Path, force_refresh: bool = False) -> str:
    """Main logic: Check cache -> Fetch -> Parse -> Save -> Return."""
    ensure_policy_dir(directory)

    # 1. Check Cache
    if not force_refresh:
        cached_text = await get_cached_policy(domain, directory)
        if cached_text:
            return cached_text

    # 2. Network Request
    url = get_policy_url(domain)
    logger.info(f"Fetching policy from {url}...")

    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error {e.response.status_code} for {domain}")
            raise InstanceUnreachableError(f"HTTP {e.response.status_code}") from e
        except httpx.RequestError as e:
            logger.error(f"Connection error for {domain}: {e}")
            raise InstanceUnreachableError(f"Connection failed: {e}") from e

    # 3. Extract
    text = extract_policy_text(response.text)

    # 4. Save
    await save_policy(domain, text, directory)

    return text


async def fetch_many(domains: List[str], directory: Path) -> None:
    """Batch processes multiple domains."""
    logger.info(f"Starting batch fetch for {len(domains)} domains.")

    tasks = [fetch_policy(domain, directory) for domain in domains]

    # gather returns results, but we define return_exceptions=True so one failure
    # doesn't crash the whole batch.
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for domain, result in zip(domains, results):
        if isinstance(result, Exception):
            logger.error(f"Failed to process {domain}: {result}")
        else:
            logger.info(f"Successfully processed {domain}")