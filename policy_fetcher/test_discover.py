import asyncio
from pathlib import Path

import pytest

import policy_fetcher.discover as discover
import policy_fetcher.fetcher as fetcher


SAMPLE_ENTRIES = [
    {
        "domain": "mastodon.social",
        "total_users": 921100,
        "languages": ["en"],
        "categories": ["general"],
    },
    {
        "domain": "infosec.exchange",
        "total_users": 45935,
        "languages": ["en"],
        "categories": ["tech"],
    },
    {
        "domain": "tiny.example",
        "total_users": 12,
        "languages": ["en"],
        "categories": ["general"],
    },
    {
        "domain": "exemple.social",
        "total_users": 5000,
        "languages": ["fr"],
        "categories": ["general"],
    },
    {
        "domain": "furry.example",
        "total_users": 8000,
        "languages": ["en"],
        "categories": ["furry"],
    },
]


def test_merge_servers_txt_dedupes_existing():
    existing = ["mastodon.social", "other.example"]
    result = discover.merge_servers_txt(SAMPLE_ENTRIES, existing)
    assert "mastodon.social" not in result
    assert "infosec.exchange" in result
    assert "tiny.example" in result


def test_merge_servers_txt_min_users_filter():
    result = discover.merge_servers_txt(SAMPLE_ENTRIES, [], min_users=500)
    assert "tiny.example" not in result
    assert "infosec.exchange" in result
    assert "mastodon.social" in result


def test_merge_servers_txt_language_filter():
    result = discover.merge_servers_txt(SAMPLE_ENTRIES, [], languages=["fr"])
    assert result == ["exemple.social"]


def test_merge_servers_txt_category_filter():
    result = discover.merge_servers_txt(SAMPLE_ENTRIES, [], categories=["tech"])
    assert result == ["infosec.exchange"]


def test_merge_servers_txt_limit_and_sorted():
    result = discover.merge_servers_txt(SAMPLE_ENTRIES, [], limit=2)
    assert len(result) == 2
    assert result == sorted(result)


def test_merge_servers_txt_no_duplicates_in_entries():
    entries = SAMPLE_ENTRIES + [SAMPLE_ENTRIES[0]]
    result = discover.merge_servers_txt(entries, [])
    assert result.count("mastodon.social") == 1


class FakeAsyncClient:
    def __init__(self, response, *args, **kwargs):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def get(self, url):
        return self.response


def test_fetch_instance_directory(enable_network, monkeypatch):
    response = fetcher.httpx.Response(
        200,
        json=SAMPLE_ENTRIES,
        request=fetcher.httpx.Request("GET", discover.DIRECTORY_URL),
    )
    monkeypatch.setattr(
        discover.httpx,
        "AsyncClient",
        lambda *a, **kw: FakeAsyncClient(response, *a, **kw),
    )

    async def run():
        async with discover.httpx.AsyncClient() as client:
            return await discover.fetch_instance_directory(client)

    entries = asyncio.run(run())
    assert entries == SAMPLE_ENTRIES


def test_fetch_instance_directory_bad_shape(enable_network, monkeypatch):
    response = fetcher.httpx.Response(
        200,
        json={"not": "a list"},
        request=fetcher.httpx.Request("GET", discover.DIRECTORY_URL),
    )
    monkeypatch.setattr(
        discover.httpx,
        "AsyncClient",
        lambda *a, **kw: FakeAsyncClient(response, *a, **kw),
    )

    async def run():
        async with discover.httpx.AsyncClient() as client:
            return await discover.fetch_instance_directory(client)

    with pytest.raises(ValueError):
        asyncio.run(run())


def test_main_appends_new_domains(enable_network, monkeypatch, tmp_path: Path):
    server_list = tmp_path / "servers.txt"
    server_list.write_text("mastodon.social\n", encoding="utf-8")

    response = fetcher.httpx.Response(
        200,
        json=SAMPLE_ENTRIES,
        request=fetcher.httpx.Request("GET", discover.DIRECTORY_URL),
    )
    monkeypatch.setattr(
        discover.httpx,
        "AsyncClient",
        lambda *a, **kw: FakeAsyncClient(response, *a, **kw),
    )

    rc = discover.main(["--append", str(server_list), "--min-users", "1000"])
    assert rc == 0

    lines = [l.strip() for l in server_list.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert "mastodon.social" in lines
    assert "infosec.exchange" in lines
    assert "tiny.example" not in lines


def test_main_handles_fetch_failure(enable_network, monkeypatch, tmp_path: Path):
    server_list = tmp_path / "servers.txt"
    server_list.write_text("mastodon.social\n", encoding="utf-8")

    class FailingClient(FakeAsyncClient):
        async def get(self, url):
            raise fetcher.httpx.ConnectError("boom")

    monkeypatch.setattr(
        discover.httpx,
        "AsyncClient",
        lambda *a, **kw: FailingClient(None, *a, **kw),
    )

    rc = discover.main(["--append", str(server_list)])
    assert rc == 1
    # File untouched on failure
    assert server_list.read_text(encoding="utf-8") == "mastodon.social\n"
