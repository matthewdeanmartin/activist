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
        "fetch", help="fetch live RSS feeds from activist.toml, digest, and dedupe"
    )
    p_fetch.add_argument("--config", type=Path, default=Path("activist.toml"))
    p_fetch.add_argument(
        "--dry-run",
        action="store_true",
        help="report what's new without touching the cache, seen.jsonl, or the store",
    )

    p_ui = sub.add_parser("ui", help="run the local review dashboard (read-only in U1)")
    p_ui.add_argument("--config", type=Path, default=Path("activist.toml"))

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
        "--app-policy", type=Path, default=Path("docs/draft_governing_policy.md")
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
    from .fetch import fetch_news
    from .store import Store

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not cfg.feeds:
        print("no [[feed]] entries in config; nothing to fetch", file=sys.stderr)
        return 1
    result = fetch_news(cfg, dry_run=args.dry_run)
    print(
        f"{len(cfg.feeds)} feeds: {result.feeds_ok} fetched, "
        f"{result.feeds_unchanged} unchanged (304), {result.feeds_failed} failed."
    )
    for outcome in result.outcomes:
        if outcome.status == "failed":
            print(f"  FAILED {outcome.name}: {outcome.detail}")
    print(f"{len(result.new_items)} new items ({result.seen_skipped} already seen):")
    for item in result.new_items:
        topics = result.relevant_topics.get(item.id, [])
        tag = f" [{', '.join(topics)}]" if topics else " [off-beat]"
        print(f"  {item.id} {item.title}{tag}")
    if args.dry_run:
        print("(dry-run: cache, seen.jsonl, and store untouched)")
    else:
        summary = f"{len(result.new_items)} new, {result.seen_skipped} seen, {result.feeds_failed} failed"
        Store(cfg.db_path).log_event("-", "fetcher", "fetch", summary)
    return 0 if result.feeds_failed < len(cfg.feeds) else 1


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
