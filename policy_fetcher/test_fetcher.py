import pytest
import asyncio
from pathlib import Path
import policy_fetcher.fetcher


# Enable async testing
@pytest.mark.asyncio
async def test_fetch_real_policy(tmp_path: Path):
    """
    Real integration test: Hits mastodon.social.
    Verifies file creation and content parsing.
    """
    domain = "mastodon.social"

    # Execute
    content = await fetcher.fetch_policy(domain, tmp_path)

    # Verification
    expected_file = tmp_path / f"{domain}.txt"
    assert expected_file.exists()

    # Check for keywords common in policy text
    # Note: Case insensitive check is safer
    lower_content = content.lower()
    assert "privacy" in lower_content or "terms" in lower_content
    assert len(content) > 100


@pytest.mark.asyncio
async def test_cache_hit(tmp_path: Path):
    """
    Verifies that if a file exists, no network call is made (implied by logic)
    and specific cached content is returned.
    """
    domain = "example.com"
    dummy_content = "CACHE_HIT_TEST_CONTENT"

    # Pre-seed the cache
    await fetcher.save_policy(domain, dummy_content, tmp_path)

    # Fetch without force_refresh
    content = await fetcher.fetch_policy(domain, tmp_path, force_refresh=False)

    assert content == dummy_content


@pytest.mark.asyncio
async def test_bad_domain(tmp_path: Path):
    """
    Verifies that a non-existent domain raises the specific custom exception.
    """
    # Use a domain that definitely doesn't exist
    domain = "this-domain-does-not-exist-12345.social"

    with pytest.raises(fetcher.InstanceUnreachableError):
        await fetcher.fetch_policy(domain, tmp_path)


@pytest.mark.asyncio
async def test_server_list_processing(tmp_path: Path):
    """
    Verifies the batch processing capability.
    We use two known stable instances.
    """
    domains = ["mastodon.social", "fosstodon.org"]

    await fetcher.fetch_many(domains, tmp_path)

    for domain in domains:
        assert (tmp_path / f"{domain}.txt").exists()
        content = (tmp_path / f"{domain}.txt").read_text()
        assert len(content) > 0