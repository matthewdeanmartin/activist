import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urljoin, urlparse

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
    'extract_policy_links',
    'fetch_offsite_policy',
    'PolicyFetchError',
    'InstanceUnreachableError'
]

# -- Configuration --
# User-Agent is polite and prevents some default-blocking by WAFs
HEADERS = {
    "User-Agent": "MastodonPolicyFetcher/1.0 (+https://github.com/your/repo)",
    "Accept": "application/json"
}

# A report this short (rules empty AND description under this many chars)
# is considered "thin" -- the real policy likely lives off-site.
THIN_DESCRIPTION_THRESHOLD = 200

# Keywords matched (case-insensitively) against link text and href to find
# off-site Terms of Service / Privacy Policy / Community Guidelines pages.
POLICY_LINK_KEYWORDS = (
    "terms",
    "privacy",
    "policy",
    "policies",
    "rules",
    "conduct",
    "guidelines",
    "tos",
)


def ensure_policy_dir(directory: Path) -> None:
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)


def clean_html(html_text: str) -> str:
    """Converts HTML chunks (from API responses) into plain text."""
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    return soup.get_text(separator="\n", strip=True)


def extract_policy_links(html_text: str, base_url: str) -> List[Tuple[str, str]]:
    """Find links on a page that plausibly point to a ToS/Privacy/Rules page.

    Matches `<a>` tags whose link text or href contains one of
    `POLICY_LINK_KEYWORDS` (case-insensitive). Relative hrefs are resolved
    against `base_url`. Returns a deduped list of (link text, absolute URL)
    pairs, in document order.
    """
    if not html_text:
        return []

    soup = BeautifulSoup(html_text, "html.parser")
    results: List[Tuple[str, str]] = []
    seen_urls: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue

        text = anchor.get_text(separator=" ", strip=True)
        haystack = f"{text} {href}".lower()
        if not any(keyword in haystack for keyword in POLICY_LINK_KEYWORDS):
            continue

        absolute_url = urljoin(base_url, href)
        if absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)
        results.append((text, absolute_url))

    return results


async def fetch_offsite_policy(
    domain: str,
    links: List[Tuple[str, str]],
    directory: Path,
    client: httpx.AsyncClient,
    llm_enabled: bool = True,
    about_text: str = "",
) -> List[Tuple[str, str]]:
    """Resolve, fetch, and save off-site policy pages for `domain`.

    `links` is the candidate (text, url) list from `extract_policy_links`.
    If there's exactly one candidate, fetch it directly. If there are
    several and `llm_enabled`, ask the `llm` CLI to pick the best
    match(es) -- any URL it returns that isn't in `links` is ignored.

    Saves each resolved page as `policies/<domain>.offsite.<n>.txt` and
    returns the list of (title, url) pairs that were saved, for the caller
    to summarize in the main report.
    """
    if not links:
        return []

    if len(links) == 1:
        chosen = links
    else:
        chosen = []
        if llm_enabled:
            from policy_fetcher.llm_spider import rank_policy_links

            ranked_urls = rank_policy_links(about_text, links)
            url_to_text = {url: text for text, url in links}
            for url in ranked_urls:
                if url in url_to_text:
                    chosen.append((url_to_text[url], url))

        if not chosen:
            logger.info(
                f"{domain}: {len(links)} candidate policy links, none chosen "
                f"(llm_enabled={llm_enabled})"
            )
            return []

    saved: List[Tuple[str, str]] = []
    for index, (text, url) in enumerate(chosen):
        html_text = await _get_html(client, url)
        if not html_text:
            continue
        cleaned = clean_html(html_text)
        title = text or url
        report = f"=== OFFSITE POLICY: {title} ({url}) ===\n\n{cleaned}"
        file_path = directory / f"{domain}.offsite.{index}.txt"
        await asyncio.to_thread(file_path.write_text, report, encoding="utf-8")
        logger.info(f"Saved {file_path}")
        saved.append((title, url))

    return saved


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


async def _get_html(client: httpx.AsyncClient, url: str) -> Optional[str]:
    """Helper to fetch an HTML body safely. Returns None on 404/errors.

    Overrides the client's default `Accept: application/json` -- Mastodon
    (and many other servers) respond 406 Not Acceptable to HTML pages like
    /about when JSON is requested.
    """
    try:
        response = await client.get(url, headers={"Accept": "text/html"})
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text
    except httpx.HTTPError as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


async def fetch_policy(
    domain: str,
    directory: Path,
    force_refresh: bool = False,
    offsite: bool = True,
    llm: bool = True,
) -> str:
    """
    Fetches policy via Mastodon API:
    1. /api/v2/instance (General info + Rules)
    2. /api/v1/instance/extended_description (Long 'About' text)
    3. /about (HTML) -- used only as a source of off-site policy links when
       the API-derived report above is "thin" (see THIN_DESCRIPTION_THRESHOLD)

    If `offsite` is True and the API report is thin, off-site Terms of
    Service / Privacy Policy / Rules pages linked from /about are fetched
    and saved as `<domain>.offsite.<n>.txt`, with a summary section appended
    to the main report. If `llm` is True, an ambiguous set of candidate
    links is disambiguated via the `llm` CLI (see llm_spider.py); set to
    False to use heuristics only.
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
        about_url = f"{base_url}/about"

        try:
            # Run requests concurrently
            instance_data, ext_desc_data, about_html = await asyncio.gather(
                _get_json(client, instance_url),
                _get_json(client, desc_url),
                _get_html(client, about_url),
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

        # 4. Off-site policy pages (only when the report above is thin).
        # No machine-readable rules is the main signal -- instances that
        # publish rules via the API rarely also hide them off-site. A short
        # description on top of that is doubly thin.
        is_thin = not rules or len(long_desc) < THIN_DESCRIPTION_THRESHOLD
        if offsite and is_thin and about_html:
            about_text = clean_html(about_html)
            candidate_links = extract_policy_links(about_html, base_url)
            saved = await fetch_offsite_policy(
                domain, candidate_links, directory, client, llm_enabled=llm, about_text=about_text
            )
            if saved:
                if email:
                    lines.append("")
                lines.append("## OFFSITE POLICIES")
                for offsite_title, offsite_url in saved:
                    lines.append(f"- {offsite_title}: {offsite_url}")

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


async def fetch_many(
    domains: List[str], directory: Path, offsite: bool = True, llm: bool = True
) -> None:
    logger.info(f"Batch fetching {len(domains)} domains...")
    tasks = [fetch_policy(domain, directory, offsite=offsite, llm=llm) for domain in domains]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    success_count = 0
    for domain, res in zip(domains, results):
        if isinstance(res, Exception):
            logger.error(f"FAILED {domain}: {res}")
        else:
            success_count += 1
    logger.info(f"Batch complete. Success: {success_count}/{len(domains)}")