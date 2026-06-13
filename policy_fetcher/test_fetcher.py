import asyncio

import pytest
from pathlib import Path
import policy_fetcher.fetcher as fetcher


# pytest-network blocks socket.connect globally. On Windows, pytest-asyncio's
# default loop setup also uses a local socketpair, so these async tests need the
# enable_network fixture before asyncio creates its local event-loop sockets.


class FakeAsyncClient:
    def __init__(self, responses, *args, **kwargs):
        self.responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def get(self, url):
        response = self.responses.get(url)
        if response is None:
            return fetcher.httpx.Response(500, json={"error": "no route"})
        return response


def http_response(status_code, **kwargs):
    return fetcher.httpx.Response(
        status_code,
        request=fetcher.httpx.Request("GET", "https://mastodon.example/mock"),
        **kwargs,
    )


def mocked_client(monkeypatch, responses):
    monkeypatch.setattr(
        fetcher.httpx,
        "AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(responses, *args, **kwargs),
    )


def test_fetch_policy_from_api(enable_network, monkeypatch, tmp_path: Path):
    """
    Verifies file creation and content parsing using mocked Mastodon API
    responses. Live-network coverage belongs in an opt-in integration test.
    """
    domain = "mastodon.example"
    base = f"https://{domain}"
    mocked_client(
        monkeypatch,
        {
            f"{base}/api/v2/instance": http_response(
                200,
                json={
                    "title": "Mastodon Example",
                    "rules": [{"id": "1", "text": "Be kind."}],
                    "contact": {"email": "admin@example.invalid"},
                },
            ),
            f"{base}/api/v1/instance/extended_description": (
                http_response(
                    200,
                    json={"content": "<p>Privacy and terms live here.</p>"},
                )
            ),
        },
    )

    content = asyncio.run(fetcher.fetch_policy(domain, tmp_path))

    expected_file = tmp_path / f"{domain}.txt"
    assert expected_file.exists()
    assert "Mastodon Example" in content
    assert "Be kind." in content
    assert "Privacy and terms live here." in content


def test_cache_hit(enable_network, tmp_path: Path):
    """
    Verifies that if a file exists, no network call is made (implied by logic)
    and specific cached content is returned.
    """
    domain = "example.com"
    dummy_content = "CACHE_HIT_TEST_CONTENT"

    # Pre-seed the cache
    asyncio.run(fetcher.save_policy(domain, dummy_content, tmp_path))

    # Fetch without force_refresh
    content = asyncio.run(fetcher.fetch_policy(domain, tmp_path, force_refresh=False))

    assert content == dummy_content


def test_bad_domain(enable_network, monkeypatch, tmp_path: Path):
    """
    Verifies that a non-existent domain raises the specific custom exception.
    """
    domain = "this-domain-does-not-exist-12345.social"
    mocked_client(monkeypatch, {})

    with pytest.raises(fetcher.InstanceUnreachableError):
        asyncio.run(fetcher.fetch_policy(domain, tmp_path))


def test_server_list_processing(enable_network, monkeypatch, tmp_path: Path):
    """
    Verifies the batch processing capability.
    """
    domains = ["mastodon.example", "fosstodon.example"]
    responses = {}
    for domain in domains:
        base = f"https://{domain}"
        responses[f"{base}/api/v2/instance"] = http_response(
            200,
            json={
                "title": domain,
                "rules": [{"id": "1", "text": f"{domain} rule"}],
                "description": "Short description",
            },
        )
        responses[f"{base}/api/v1/instance/extended_description"] = (
            http_response(404)
        )
    mocked_client(monkeypatch, responses)

    asyncio.run(fetcher.fetch_many(domains, tmp_path))

    for domain in domains:
        assert (tmp_path / f"{domain}.txt").exists()
        content = (tmp_path / f"{domain}.txt").read_text()
        assert len(content) > 0
