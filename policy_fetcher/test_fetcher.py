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

    async def get(self, url, **kwargs):
        response = self.responses.get(url)
        if response is None:
            return fetcher.httpx.Response(
                500,
                json={"error": "no route"},
                request=fetcher.httpx.Request("GET", url),
            )
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


# -- Off-site policy discovery --

def test_extract_policy_links_keyword_match():
    html = """
    <html><body>
      <a href="/about/more">Server rules</a>
      <a href="/terms">Terms of Service</a>
      <a href="https://other.example/privacy">Privacy policy</a>
      <a href="/donate">Donate</a>
      <a href="#top">Back to top</a>
    </body></html>
    """
    links = fetcher.extract_policy_links(html, "https://mastodon.example")

    urls = [url for _, url in links]
    assert "https://mastodon.example/about/more" in urls
    assert "https://mastodon.example/terms" in urls
    assert "https://other.example/privacy" in urls
    assert "https://mastodon.example/donate" not in urls
    assert not any(url.endswith("#top") for url in urls)


def test_extract_policy_links_empty_html():
    assert fetcher.extract_policy_links("", "https://mastodon.example") == []


def test_fetch_offsite_policy_single_link(enable_network, monkeypatch, tmp_path: Path):
    domain = "mastodon.example"
    links = [("Terms of Service", "https://mastodon.example/terms")]

    async def run():
        responses = {
            "https://mastodon.example/terms": http_response(
                200, text="<html><body><h1>Terms</h1><p>Be nice.</p></body></html>"
            )
        }
        client = FakeAsyncClient(responses)

        # Spy: rank_policy_links must not be called for a single candidate.
        import policy_fetcher.llm_spider as llm_spider

        called = {"value": False}

        def fake_rank(*args, **kwargs):
            called["value"] = True
            return []

        monkeypatch.setattr(llm_spider, "rank_policy_links", fake_rank)

        saved = await fetcher.fetch_offsite_policy(domain, links, tmp_path, client)
        assert not called["value"]
        return saved

    saved = asyncio.run(run())
    assert saved == [("Terms of Service", "https://mastodon.example/terms")]

    offsite_file = tmp_path / f"{domain}.offsite.0.txt"
    assert offsite_file.exists()
    content = offsite_file.read_text(encoding="utf-8")
    assert "Be nice." in content
    assert "https://mastodon.example/terms" in content


def test_fetch_offsite_policy_ambiguous_uses_llm(enable_network, monkeypatch, tmp_path: Path):
    domain = "mastodon.example"
    links = [
        ("Terms of Service", "https://mastodon.example/terms"),
        ("Privacy Policy", "https://mastodon.example/privacy"),
        ("Donate", "https://mastodon.example/donate"),
    ]

    async def run():
        responses = {
            "https://mastodon.example/terms": http_response(
                200, text="<html><body>Terms text</body></html>"
            ),
        }
        client = FakeAsyncClient(responses)

        import policy_fetcher.llm_spider as llm_spider

        def fake_rank(about_text, candidate_links, **kwargs):
            # Only pick the terms link, ignoring privacy/donate and any
            # invented URL.
            return ["https://mastodon.example/terms", "https://evil.example/x"]

        monkeypatch.setattr(llm_spider, "rank_policy_links", fake_rank)

        return await fetcher.fetch_offsite_policy(
            domain, links, tmp_path, client, about_text="some about text"
        )

    saved = asyncio.run(run())
    assert saved == [("Terms of Service", "https://mastodon.example/terms")]
    assert (tmp_path / f"{domain}.offsite.0.txt").exists()
    assert not (tmp_path / f"{domain}.offsite.1.txt").exists()


def test_fetch_offsite_policy_no_links_returns_empty(enable_network, tmp_path: Path):
    async def run():
        client = FakeAsyncClient({})
        return await fetcher.fetch_offsite_policy("mastodon.example", [], tmp_path, client)

    assert asyncio.run(run()) == []


def test_fetch_policy_thin_report_fetches_offsite(enable_network, monkeypatch, tmp_path: Path):
    """
    A report with no rules and a short description is "thin": /about is
    fetched, a single matching link is found, and its content is saved and
    summarized.
    """
    domain = "mastodon.example"
    base = f"https://{domain}"

    about_html = """
    <html><body>
      <p>Welcome!</p>
      <a href="/terms">Terms of Service</a>
      <a href="/donate">Donate</a>
    </body></html>
    """

    responses = {
        f"{base}/api/v2/instance": http_response(
            200,
            json={
                "title": "Mastodon Example",
                "rules": [],
                "description": "Tiny.",
                "contact": {"email": "admin@example.invalid"},
            },
        ),
        f"{base}/api/v1/instance/extended_description": http_response(404),
        f"{base}/about": http_response(200, text=about_html),
        f"{base}/terms": http_response(
            200, text="<html><body><h1>Terms</h1><p>Play nice.</p></body></html>"
        ),
    }
    mocked_client(monkeypatch, responses)

    content = asyncio.run(fetcher.fetch_policy(domain, tmp_path, llm=False))

    assert "## OFFSITE POLICIES" in content
    assert f"{base}/terms" in content
    assert (tmp_path / f"{domain}.offsite.0.txt").exists()
    assert "Play nice." in (tmp_path / f"{domain}.offsite.0.txt").read_text(encoding="utf-8")


def test_fetch_policy_rich_report_skips_offsite(enable_network, monkeypatch, tmp_path: Path):
    """A report with real rules/description is not "thin" -- /about content
    is fetched (cheap, concurrent) but not used for offsite spidering."""
    domain = "mastodon.example"
    base = f"https://{domain}"

    responses = {
        f"{base}/api/v2/instance": http_response(
            200,
            json={
                "title": "Mastodon Example",
                "rules": [{"id": "1", "text": "Be kind."}],
                "description": "A".ljust(300, "x"),
            },
        ),
        f"{base}/api/v1/instance/extended_description": http_response(404),
        f"{base}/about": http_response(
            200, text='<html><body><a href="/terms">Terms</a></body></html>'
        ),
    }
    mocked_client(monkeypatch, responses)

    content = asyncio.run(fetcher.fetch_policy(domain, tmp_path))

    assert "## OFFSITE POLICIES" not in content
    assert not (tmp_path / f"{domain}.offsite.0.txt").exists()


def test_fetch_policy_offsite_disabled(enable_network, monkeypatch, tmp_path: Path):
    domain = "mastodon.example"
    base = f"https://{domain}"

    about_html = '<html><body><a href="/terms">Terms of Service</a></body></html>'
    responses = {
        f"{base}/api/v2/instance": http_response(
            200, json={"title": "Mastodon Example", "rules": [], "description": ""}
        ),
        f"{base}/api/v1/instance/extended_description": http_response(404),
        f"{base}/about": http_response(200, text=about_html),
        f"{base}/terms": http_response(200, text="<html><body>Terms</body></html>"),
    }
    mocked_client(monkeypatch, responses)

    content = asyncio.run(fetcher.fetch_policy(domain, tmp_path, offsite=False))

    assert "## OFFSITE POLICIES" not in content
    assert not (tmp_path / f"{domain}.offsite.0.txt").exists()
