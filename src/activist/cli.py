"""Command-line interface: activist run | render | reset-memory."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

from . import __version__, render, state
from .engine import get_engine
from .pipeline import RunConfig, run


def main(argv: list[str] | None = None) -> int:
    # Windows consoles often default to cp1252, which can't print the
    # disclosure emoji or policy quotes; never let printing crash the CLI.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "fetch":
        return _cmd_fetch(args)
    if args.command == "ui":
        return _cmd_ui(args)
    if args.command == "api":
        return _cmd_api(args)
    if args.command == "poster":
        return _cmd_poster(args)
    if args.command == "replies":
        return _cmd_replies(args)
    if args.command == "moderate":
        return _cmd_moderate(args)
    if args.command == "render":
        return _cmd_render(args)
    if args.command == "reset-memory":
        return _cmd_reset_memory(args)
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="activist",
        description="Human-in-the-loop activist bot POC. Simulates posts; never publishes.",
    )
    parser.add_argument("--version", action="version", version=f"activist {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="ingest fixtures and produce the feed that would have been")
    p_run.add_argument("--fixtures", type=Path, default=Path("fixtures/feeds"), help="dir of *.xml feed files")
    p_run.add_argument("--persona", type=Path, default=Path("persona"), help="persona state dir")
    p_run.add_argument("--out", type=Path, default=Path("out"), help="output dir")
    p_run.add_argument("--date", default=dt.date.today().isoformat(), help="run date YYYY-MM-DD")
    p_run.add_argument("--engine", choices=["mockbot", "openrouter"], default="mockbot")
    p_run.add_argument("--model", default=None, help="model id for --engine openrouter")
    p_run.add_argument("--max-posts", type=int, default=None, help="override persona post cap")
    p_run.add_argument("--dry-state", action="store_true", help="do not write opinions/memory")
    _add_instance_args(p_run)

    p_fetch = sub.add_parser(
        "fetch",
        help="full live chain: fetch RSS → engine → moderate → review queue (never publishes)",
    )
    p_fetch.add_argument("--config", type=Path, default=Path("activist.toml"))
    p_fetch.add_argument(
        "--dry-run",
        action="store_true",
        help="preview the chain without touching the cache, persona/, the store, or out/",
    )
    p_fetch.add_argument(
        "--engine", choices=["mockbot", "openrouter"], default=None, help="override config engine"
    )
    p_fetch.add_argument("--model", default=None, help="model id for openrouter")
    p_fetch.add_argument(
        "--max-engine-calls",
        type=int,
        default=None,
        help="cap engine.react() calls this run (overrides [engine].call_budget); "
        "each call is a real LLM request for openrouter",
    )
    p_fetch.add_argument(
        "--replies",
        dest="replies",
        action="store_true",
        default=None,
        help="also draft replies to live Mastodon mentions (read-only). "
        "Defaults to [replies].enabled in the config.",
    )
    p_fetch.add_argument(
        "--no-replies",
        dest="replies",
        action="store_false",
        help="skip the replies pass even if [replies].enabled is set",
    )
    p_fetch.add_argument(
        "--only-replies",
        action="store_true",
        help="run only the replies pass, skipping the news fetch",
    )

    p_ui = sub.add_parser("ui", help="run the local review dashboard (read-only in U1)")
    p_ui.add_argument("--config", type=Path, default=Path("activist.toml"))

    p_api = sub.add_parser(
        "api", help="run the FastAPI admin site (JSON API + built Angular SPA)"
    )
    p_api.add_argument("--config", type=Path, default=Path("activist.toml"))
    p_api.add_argument("--host", default=None, help="override [api].host")
    p_api.add_argument("--port", type=int, default=None, help="override [api].port")
    p_api.add_argument(
        "--dev-cors",
        action="store_true",
        help="allow the Angular dev server (localhost:4200) to call the API",
    )
    p_api.add_argument("--reload", action="store_true", help="uvicorn auto-reload (dev)")

    p_poster = sub.add_parser(
        "poster",
        help="publish due approved drafts (dry-run transport only until Phase P2)",
    )
    p_poster.add_argument("--config", type=Path, default=Path("activist.toml"))
    p_poster.add_argument(
        "--loop",
        action="store_true",
        help="keep running, ticking every poster.check_interval_minutes (default: one tick)",
    )
    p_poster.add_argument(
        "--skip-verify",
        action="store_true",
        help="skip the read-only Mastodon token check before ticking",
    )
    p_poster.add_argument(
        "--live",
        action="store_true",
        help="publish for real (third part of the gate; also needs [poster].live=true "
        "and ACTIVIST_LIVE=1). Without all three, the dry-run transport is used.",
    )

    p_rep = sub.add_parser(
        "replies", help="draft replies to inbound mentions (simulated; consent gates in code)"
    )
    p_rep.add_argument(
        "--mentions",
        type=Path,
        default=Path("fixtures/mentions-sample.toml"),
        help="TOML file of inbound mentions",
    )
    p_rep.add_argument("--persona", type=Path, default=Path("persona"))
    p_rep.add_argument("--out", type=Path, default=Path("out"))
    p_rep.add_argument("--date", default=dt.date.today().isoformat())
    p_rep.add_argument("--engine", choices=["mockbot", "openrouter"], default="mockbot")
    p_rep.add_argument("--model", default=None, help="model id for --engine openrouter")
    p_rep.add_argument("--max-replies", type=int, default=None, help="override persona reply cap")
    p_rep.add_argument("--dry-state", action="store_true", help="do not write memory")
    _add_instance_args(p_rep)

    p_mod = sub.add_parser(
        "moderate", help="flag posts in a feed.toml against app and instance policies"
    )
    p_mod.add_argument("feed_toml", type=Path)
    p_mod.add_argument("--persona", type=Path, default=Path("persona"), help="for the disclosure footer")
    p_mod.add_argument(
        "--app-policy",
        type=Path,
        default=None,
        help="override the packaged governing policy used by the moderator",
    )
    p_mod.add_argument("--policies-dir", type=Path, default=Path("policies"))
    p_mod.add_argument(
        "--instance",
        action="append",
        default=[],
        metavar="DOMAIN",
        help="instance to check (repeatable), e.g. --instance infosec.exchange",
    )
    p_mod.add_argument(
        "--engine",
        choices=["mockmod", "openrouter"],
        default="mockmod",
        help="mockmod = deterministic checks only; openrouter adds LLM judgment on top",
    )
    p_mod.add_argument("--model", default=None, help="model id(s) for --engine openrouter")

    p_render = sub.add_parser("render", help="re-render an existing feed.toml to HTML")
    p_render.add_argument("feed_toml", type=Path)

    p_reset = sub.add_parser("reset-memory", help="clear memory/ (seen, said, mentions, diary)")
    p_reset.add_argument("--persona", type=Path, default=Path("persona"))
    return parser


def _add_instance_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--instance",
        action="append",
        default=[],
        metavar="DOMAIN",
        help="target instance (repeatable); its policy tightens the hourly pacing",
    )
    parser.add_argument("--policies-dir", type=Path, default=Path("policies"))


def _load_instance_policies(args: argparse.Namespace) -> dict[str, str]:
    from .moderation.policies import load_instance_policy

    return {
        instance: load_instance_policy(args.policies_dir, instance)
        for instance in args.instance
    }


def _cmd_run(args: argparse.Namespace) -> int:
    if not args.fixtures.is_dir():
        print(f"fixtures dir not found: {args.fixtures}", file=sys.stderr)
        return 1
    if not (args.persona / "persona.toml").is_file():
        print(f"persona.toml not found in: {args.persona}", file=sys.stderr)
        return 1
    engine = get_engine(args.engine, model=args.model)
    try:
        instance_policies = _load_instance_policies(args)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    result = run(
        RunConfig(
            fixtures_dir=args.fixtures,
            persona_dir=args.persona,
            out_dir=args.out,
            date=args.date,
            engine=engine,
            dry_state=args.dry_state,
            max_posts=args.max_posts,
            instance_policies=instance_policies,
        )
    )
    print(
        f"{result.items_ingested} ingested, {result.items_relevant} relevant, "
        f"{len(result.posts)} would-be posts."
    )
    print(f"queue:  {result.feed_toml}")
    print(f"review: {result.feed_html}")
    if args.dry_state:
        print("(dry-state: persona/ untouched)")
    else:
        print("state updated — review with: git diff persona/")
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    from .config import ConfigError, load_config
    from .fetch import run_news_chain
    from .store import Store

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not cfg.feeds and not args.only_replies:
        print("no [[feed]] entries in config; nothing to fetch", file=sys.stderr)
        return 1
    if not (cfg.persona_dir / "persona.toml").is_file():
        print(f"persona.toml not found in: {cfg.persona_dir}", file=sys.stderr)
        return 1
    if args.max_engine_calls is not None:
        cfg.engine_call_budget = args.max_engine_calls
    engine = get_engine(args.engine or cfg.engine, model=args.model or cfg.model)
    llm_moderator = None
    if cfg.moderation_engine == "openrouter":
        from .moderation.openrouter_mod import OpenRouterModerator

        llm_moderator = OpenRouterModerator(model=args.model)
    store = Store(cfg.db_path)

    do_replies = cfg.replies_enabled if args.replies is None else args.replies
    do_news = not args.only_replies
    if args.only_replies:
        do_replies = True

    news_failed = False
    if do_news:
        result = run_news_chain(
            cfg, engine, store, dry_run=args.dry_run, llm_moderator=llm_moderator
        )
        fetched = result.fetch
        print(
            f"{len(cfg.feeds)} feeds: {fetched.feeds_ok} fetched, "
            f"{fetched.feeds_unchanged} unchanged (304), {fetched.feeds_failed} failed."
        )
        for outcome in fetched.outcomes:
            if outcome.status == "failed":
                print(f"  FAILED {outcome.name}: {outcome.detail}")
        print(
            f"{len(fetched.new_items)} new items ({fetched.seen_skipped} already seen) -> "
            f"{len(result.posts)} drafts ({result.errors} error flags, {result.warns} warns)."
        )
        for post in result.posts:
            kind = "CHANGED-MIND" if post.opinion_change else "POST"
            print(f"  {post.id} [{kind}] slot {post.created} keys={post.opinion_keys}")
        if args.dry_run:
            print("(dry-run: cache, persona/, store, and out/ untouched)")
        else:
            print(
                f"queued: {result.inserted} pending review"
                + (f" ({result.duplicates} duplicates skipped)" if result.duplicates else "")
            )
        news_failed = fetched.feeds_failed >= len(cfg.feeds)

    replies_failed = False
    if do_replies:
        replies_failed = _run_replies_pass(cfg, engine, store, args, llm_moderator)

    if not args.dry_run:
        counts = store.counts()
        print(f"queue now: {counts['pending_review']} pending, {counts['approved']} approved")
        print("review with: activist ui")
    return 1 if (news_failed or replies_failed) else 0


def _run_replies_pass(cfg, engine, store, args, llm_moderator) -> bool:
    """Run the live replies chain; returns True on a hard failure (bad creds)."""
    from .reply_fetch import CredentialsError, build_reader, run_reply_chain

    reader = None
    try:
        reader = build_reader(cfg)
    except CredentialsError as exc:
        print(f"replies skipped — credentials: {exc}", file=sys.stderr)
        return True
    try:
        rresult = run_reply_chain(
            cfg, engine, store, reader=reader, dry_run=args.dry_run, llm_moderator=llm_moderator
        )
    except Exception as exc:  # network/API failure shouldn't crash the whole run
        print(f"replies pass failed: {exc}", file=sys.stderr)
        return True
    finally:
        if reader is not None:
            reader.close()
    print(
        f"replies: {rresult.mentions_total} mentions -> {rresult.eligible} eligible, "
        f"{rresult.gated} gated, {rresult.declined} declined, "
        f"{rresult.inserted} reply drafts queued "
        f"({rresult.errors} error flags, {rresult.warns} warns)."
    )
    if args.dry_run:
        print("(dry-run: store, checkpoint, and persona/ untouched)")
    return False


def _cmd_ui(args: argparse.Namespace) -> int:
    from .config import ConfigError, load_config
    from .web import create_app

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    app = create_app(cfg)
    print(f"review queue: http://{cfg.ui_host}:{cfg.ui_port}/")
    app.run(host=cfg.ui_host, port=cfg.ui_port)
    return 0


def _cmd_api(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_api
    from .config import ConfigError, load_config

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    host = args.host or cfg.api_host
    port = args.port or cfg.api_port
    app = create_api(cfg, dev_cors=args.dev_cors)
    print(f"admin site:  http://{host}:{port}/")
    print(f"API docs:    http://{host}:{port}/docs")
    if args.dev_cors:
        print("dev CORS on: run the Angular app with  cd admin-web && npm start")
    uvicorn.run(app, host=host, port=port, reload=args.reload)
    return 0


def _cmd_poster(args: argparse.Namespace) -> int:
    import os

    from .config import ConfigError, load_config
    from .poster import PosterLock, poster_loop, poster_tick
    from .store import Store
    from .transport import DryRunTransport, MastodonTransport, PublishGateError

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # The triple gate (spec/poster_service.md P2): config flag + env var + CLI
    # flag. All three required, or we fall back to dry-run with a loud reason.
    env_live = os.environ.get("ACTIVIST_LIVE") == "1"
    want_live = bool(cfg.poster_live and env_live and args.live)
    if (cfg.poster_live or args.live) and not want_live:
        print(
            "live publishing requested but the gate is not fully open: "
            f"[poster].live={cfg.poster_live}, ACTIVIST_LIVE={'1' if env_live else 'unset'}, "
            f"--live={args.live}. Falling back to dry-run.",
            file=sys.stderr,
        )
    if not args.skip_verify:
        import httpx

        from .mastodon_client import CredentialsError, MastodonCredentials, MastodonReader

        reader = None
        try:
            reader = MastodonReader(MastodonCredentials.from_env(cfg.mastodon_id))
            account = reader.verify_credentials()
            print(f"token ok: @{account.get('acct', '?')} on {reader.creds.base_url}")
        except (CredentialsError, httpx.HTTPError) as exc:
            print(f"credential check failed: {exc}", file=sys.stderr)
            return 1
        finally:
            if reader is not None:
                reader.close()
    transport: object
    if want_live:
        from .mastodon_client import CredentialsError, MastodonCredentials

        try:
            transport = MastodonTransport(
                MastodonCredentials.from_env(cfg.mastodon_id),
                default_visibility=cfg.default_visibility,
                live_flag=args.live,
                config_live=cfg.poster_live,
            )
        except (CredentialsError, PublishGateError) as exc:
            print(f"cannot start live transport: {exc}", file=sys.stderr)
            return 1
        print("LIVE transport: publishing to the real instance.")
    else:
        transport = DryRunTransport(cfg.dryrun_log)
    store = Store(cfg.db_path)
    try:
        with PosterLock(cfg.poster_lock):
            if args.loop:
                poster_loop(cfg, store, transport)
                return 0
            tick = poster_tick(cfg, store, transport)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"{tick.due} due: {len(tick.published)} published ({transport.name}), "
        f"{len(tick.failed)} failed, {tick.deferred_pacing} deferred by pacing, "
        f"{tick.skipped_race} lost claim races."
    )
    if tick.published:
        print(f"dry-run log: {cfg.dryrun_log}")
    return 0 if not tick.failed else 1


def _cmd_replies(args: argparse.Namespace) -> int:
    from .replies import ReplyRunConfig, run_replies

    if not args.mentions.is_file():
        print(f"mentions file not found: {args.mentions}", file=sys.stderr)
        return 1
    if not (args.persona / "persona.toml").is_file():
        print(f"persona.toml not found in: {args.persona}", file=sys.stderr)
        return 1
    engine = get_engine(args.engine, model=args.model)
    try:
        instance_policies = _load_instance_policies(args)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    result = run_replies(
        ReplyRunConfig(
            mentions_path=args.mentions,
            persona_dir=args.persona,
            out_dir=args.out,
            date=args.date,
            engine=engine,
            dry_state=args.dry_state,
            max_replies=args.max_replies,
            instance_policies=instance_policies,
        )
    )
    print(
        f"{result.mentions_total} mentions, {result.mentions_eligible} passed consent gates, "
        f"{len(result.posts)} would-be replies."
    )
    print(f"queue:  {result.replies_toml}")
    print(f"review: {result.replies_html}")
    if args.dry_state:
        print("(dry-state: persona/ untouched)")
    return 0


def _cmd_moderate(args: argparse.Namespace) -> int:
    from .moderation import ModerationContext, moderate_feed
    from .moderation.policies import load_app_policy, load_instance_policy

    if not args.feed_toml.is_file():
        print(f"not found: {args.feed_toml}", file=sys.stderr)
        return 1
    persona = state.load_persona(args.persona / "persona.toml")
    instance_policies: dict[str, str] = {}
    for instance in args.instance:
        try:
            instance_policies[instance] = load_instance_policy(args.policies_dir, instance)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    ctx = ModerationContext(
        disclosure=persona.disclosure,
        app_policy=load_app_policy(args.app_policy),
        instance_policies=instance_policies,
    )
    llm = None
    if args.engine == "openrouter":
        from .moderation.openrouter_mod import OpenRouterModerator

        llm = OpenRouterModerator(model=args.model)
    result = moderate_feed(args.feed_toml, ctx, llm_moderator=llm)
    print(
        f"{result.posts} posts reviewed: {result.flagged_posts} flagged "
        f"({result.errors} errors, {result.warns} warns)."
    )
    for flag in result.flags:
        print(f"  [{flag.severity}] {flag.policy}/{flag.rule}: {flag.detail}")
    print(f"queue:  {result.feed_toml}")
    print(f"review: {result.feed_html}")
    print("Flags never drop posts — you adjudicate.")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    if not args.feed_toml.is_file():
        print(f"not found: {args.feed_toml}", file=sys.stderr)
        return 1
    out = render.render_feed(args.feed_toml)
    print(f"rendered: {out}")
    return 0


def _cmd_reset_memory(args: argparse.Namespace) -> int:
    memory_dir = args.persona / "memory"
    cleared = []
    for name in (state.SEEN_FILE, state.SAID_FILE, state.MENTIONS_FILE, state.DIARY_FILE):
        path = memory_dir / name
        if path.exists():
            path.unlink()
            cleared.append(name)
    print(f"cleared: {', '.join(cleared) or 'nothing (memory already empty)'}")
    print("opinions.toml left alone — use git to revert it if needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
