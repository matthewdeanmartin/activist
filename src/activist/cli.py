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
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.command == "run":
        return _cmd_run(args)
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

    p_render = sub.add_parser("render", help="re-render an existing feed.toml to HTML")
    p_render.add_argument("feed_toml", type=Path)

    p_reset = sub.add_parser("reset-memory", help="clear memory/ (seen, said, diary)")
    p_reset.add_argument("--persona", type=Path, default=Path("persona"))
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    if not args.fixtures.is_dir():
        print(f"fixtures dir not found: {args.fixtures}", file=sys.stderr)
        return 1
    if not (args.persona / "persona.toml").is_file():
        print(f"persona.toml not found in: {args.persona}", file=sys.stderr)
        return 1
    engine = get_engine(args.engine, model=args.model)
    result = run(
        RunConfig(
            fixtures_dir=args.fixtures,
            persona_dir=args.persona,
            out_dir=args.out,
            date=args.date,
            engine=engine,
            dry_state=args.dry_state,
            max_posts=args.max_posts,
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
    for name in (state.SEEN_FILE, state.SAID_FILE, state.DIARY_FILE):
        path = memory_dir / name
        if path.exists():
            path.unlink()
            cleared.append(name)
    print(f"cleared: {', '.join(cleared) or 'nothing (memory already empty)'}")
    print("opinions.toml left alone — use git to revert it if needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
