"""Fetcher Phase F3: the live replies chain notifications → engine → store.

Recorded notification JSON (fixtures/notifications-sample.json, ids scrubbed)
is served through httpx.MockTransport, so the same consent gates and engine
run as the fixture path — but mentions arrive as live API shapes and survivors
land in the queue store as pending_review rows (kind='reply').
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import httpx
import pytest

from activist import state
from activist.config import AppConfig
from activist.engine import MockBot
from activist.mastodon_client import MastodonCredentials, MastodonReader
from activist.models import DraftPost, Reaction
from activist.reply_fetch import run_reply_chain, since_id_key
from activist.store import PENDING, Store

NOW = dt.datetime(2026, 6, 12, 15, 0, 0, tzinfo=dt.UTC)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "notifications-sample.json"


@pytest.fixture
def workspace(tmp_path, repo_root):
    shutil.copytree(repo_root / "persona", tmp_path / "persona")
    shutil.copyfile(
        repo_root / "tests" / "seed_opinions.toml", tmp_path / "persona" / "opinions.toml"
    )
    memory = tmp_path / "persona" / "memory"
    shutil.rmtree(memory, ignore_errors=True)
    memory.mkdir()
    return tmp_path


def make_cfg(workspace: Path, repo_root: Path) -> AppConfig:
    cfg = AppConfig()
    cfg.persona_dir = workspace / "persona"
    cfg.db_path = workspace / "data" / "queue.db"
    cfg.policies_dir = repo_root / "policies"
    cfg.mastodon_id = "TECH"
    return cfg


def reader_serving(payload: list[dict], capture: dict | None = None) -> MastodonReader:
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["params"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json=payload)

    creds = MastodonCredentials(
        identity="TECH",
        base_url="https://mas.example",
        client_id="c",
        client_secret="s",
        access_token="t",
    )
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url=creds.base_url)
    return MastodonReader(creds, client=client)


def fixture_notifications() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class TopicEngine:
    """A reply engine that answers any summoning mention from a held opinion —
    lets us exercise the 'a draft gets queued' path (MockBot keys off a fixture
    'asks' hint that live mentions don't carry)."""

    name = "topicbot"

    def react(self, *a, **k):  # pragma: no cover - not used in replies
        raise NotImplementedError

    def reply(self, mention, persona, opinions, knowledge, recent_said, created):
        if not opinions:
            return Reaction(post=None, diary_note="nothing held")
        op = next(iter(opinions.values()))
        text = f"{mention.author} I think {op.stance}.\n\n{persona.disclosure}"
        return Reaction(
            post=DraftPost(
                id=f"reply-{mention.id}",
                created=created,
                status="draft",
                text=text,
                char_count=len(text),
                source_url="",
                source_title=f"mention from {mention.author}",
                opinion_keys=[op.key],
                engine=self.name,
                reply_to_id=mention.id,
                reply_to_author=mention.author,
                reply_to_text=mention.text,
                reply_to_status_id=mention.status_id,
                visibility=mention.visibility,
            )
        )


# --- consent gates against live API shapes -----------------------------------


def test_consent_gates_filter_live_notifications(workspace, repo_root):
    """4 notifications: bot author, #nobot bio, not-summoned, one clean summon."""
    cfg = make_cfg(workspace, repo_root)
    store = Store(cfg.db_path)
    reader = reader_serving(fixture_notifications())
    result = run_reply_chain(cfg, MockBot(), store, reader=reader, now=NOW)

    assert result.mentions_total == 4
    # bot + #nobot + not-summoned are gated; only solarfan reaches the engine
    assert result.gated == 3
    assert result.eligible == 1
    # MockBot declines (live mentions carry no 'asks' hint) -> nothing queued
    assert result.declined == 1
    assert result.inserted == 0


# --- a real draft, threaded and audience-matched -----------------------------


def test_eligible_mention_queues_threaded_reply(workspace, repo_root):
    cfg = make_cfg(workspace, repo_root)
    store = Store(cfg.db_path)
    reader = reader_serving(fixture_notifications())
    result = run_reply_chain(cfg, TopicEngine(), store, reader=reader, now=NOW)

    assert result.eligible == 1
    assert result.inserted == 1
    rows = store.list_by_status(PENDING)
    assert len(rows) == 1
    row = rows[0]
    assert row.kind == "reply"
    # threads onto the real STATUS id (550000001), not the notification id
    assert row.in_reply_to_status_id == "550000001"
    # a DM stays a DM — the reply must not widen audience
    assert row.visibility == "private"
    assert row.reply_to_author == "@solarfan@mastodon.social"


# --- checkpointing + dedup ----------------------------------------------------


def test_since_id_checkpoint_is_set_and_sent(workspace, repo_root):
    cfg = make_cfg(workspace, repo_root)
    store = Store(cfg.db_path)
    reader = reader_serving(fixture_notifications())
    run_reply_chain(cfg, TopicEngine(), store, reader=reader, now=NOW)

    # checkpoint advances to the newest notification id seen (440000004)
    assert store.get_kv(since_id_key("TECH")) == "440000004"

    # a second run sends that since_id to the API
    capture: dict = {}
    reader2 = reader_serving([], capture=capture)
    run_reply_chain(cfg, TopicEngine(), store, reader=reader2, now=NOW)
    assert capture["params"]["since_id"] == "440000004"
    assert capture["params"]["types[]"] == "mention"


def test_handled_set_dedups_a_replayed_notification(workspace, repo_root):
    cfg = make_cfg(workspace, repo_root)
    store = Store(cfg.db_path)
    run_reply_chain(cfg, TopicEngine(), store, reader=reader_serving(fixture_notifications()), now=NOW)
    assert store.counts()[PENDING] == 1

    # same notifications replayed (e.g. checkpoint lost) -> handled set + PK guard
    second = run_reply_chain(
        cfg, TopicEngine(), store, reader=reader_serving(fixture_notifications()), now=NOW
    )
    assert second.eligible == 0  # already handled
    assert second.inserted == 0
    assert store.counts()[PENDING] == 1


# --- CLI: activist fetch --only-replies --------------------------------------


def write_config(workspace: Path, repo_root: Path) -> Path:
    cfg_path = workspace / "activist.toml"
    cfg_path.write_text(
        "\n".join(
            [
                "[identity]",
                'mastodon_id = "TECH"',
                "[engine]",
                'name = "mockbot"',
                "[replies]",
                "enabled = true",
                "[paths]",
                f'db = "{(workspace / "data" / "queue.db").as_posix()}"',
                f'persona = "{(workspace / "persona").as_posix()}"',
                f'policies = "{(repo_root / "policies").as_posix()}"',
            ]
        ),
        encoding="utf-8",
    )
    return cfg_path


def test_cli_only_replies_runs_without_feeds(workspace, repo_root, monkeypatch, capsys):
    from activist import cli, reply_fetch

    cfg_path = write_config(workspace, repo_root)
    monkeypatch.setattr(
        reply_fetch, "build_reader", lambda cfg: reader_serving(fixture_notifications())
    )
    rc = cli.main(["fetch", "--config", str(cfg_path), "--only-replies"])
    out = capsys.readouterr().out
    assert rc == 0
    # no [[feed]] entries, but --only-replies skips the feed guard and the news pass
    assert "replies: 4 mentions" in out
    assert "1 eligible" in out


# --- dry run ------------------------------------------------------------------


def test_dry_run_touches_nothing(workspace, repo_root):
    cfg = make_cfg(workspace, repo_root)
    store = Store(cfg.db_path)
    result = run_reply_chain(
        cfg, TopicEngine(), store, reader=reader_serving(fixture_notifications()),
        now=NOW, dry_run=True,
    )
    assert result.eligible == 1
    assert result.inserted == 0  # nothing written
    assert store.counts()[PENDING] == 0
    assert store.get_kv(since_id_key("TECH")) == ""
    assert state.load_handled_mentions(cfg.persona_dir / "memory") == set()
