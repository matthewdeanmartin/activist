"""Build the static demo site published to GitHub Pages under ./demo/.

`out/` is gitignored, so CI can't ship a committed snapshot — it regenerates
one. The catch (and the reason this isn't just `activist run --out demo`): a
demo run against the real `persona/` produces nothing, because that persona's
`memory/seen.jsonl` has already seen every fixture item and its default
`opinions.toml` holds no stance the fixtures engage. So we stage the same clean
workspace the tests use — `tests/seed_opinions.toml` as the opinions, an empty
memory — which is what yields the rich 5-posts / 2-replies demo.

Output layout (everything self-contained; the rendered HTML inlines its CSS):

    demo/
      index.html            generated here — links into the run
      <date>/feed.html      `activist run`     against fixtures/feeds
      <date>/replies.html   `activist replies` against fixtures/mentions-sample.toml

Usage: python scripts/build_demo.py [--date YYYY-MM-DD] [--demo-dir demo]
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_activist(args: list[str]) -> None:
    """Invoke the activist CLI in-process-equivalent via the module, failing loudly."""
    cmd = [sys.executable, "-m", "activist.cli", *args]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def stage_workspace(work: Path) -> Path:
    """A pristine persona: seeded opinions + empty memory (matches the test fixtures)."""
    persona = work / "persona"
    shutil.copytree(REPO_ROOT / "persona", persona)
    shutil.copyfile(REPO_ROOT / "tests" / "seed_opinions.toml", persona / "opinions.toml")
    memory = persona / "memory"
    shutil.rmtree(memory, ignore_errors=True)
    memory.mkdir(parents=True)
    return persona


def persona_meta() -> tuple[str, str, str]:
    data = tomllib.loads((REPO_ROOT / "persona" / "persona.toml").read_text(encoding="utf-8"))
    identity = data.get("identity", {})
    return (
        identity.get("name", "activist"),
        identity.get("handle", ""),
        identity.get("bio", ""),
    )


def generate(date: str, demo_dir: Path) -> dict:
    """Produce demo/<date>/{feed,replies}.html; return a small manifest."""
    with tempfile.TemporaryDirectory(prefix="activist-demo-") as tmp:
        work = Path(tmp)
        persona = stage_workspace(work)
        out = work / "out"

        run_activist(
            [
                "run",
                "--fixtures", str(REPO_ROOT / "fixtures" / "feeds"),
                "--persona", str(persona),
                "--out", str(out),
                "--date", date,
                "--dry-state",
            ]
        )
        run_activist(
            [
                "replies",
                "--mentions", str(REPO_ROOT / "fixtures" / "mentions-sample.toml"),
                "--persona", str(persona),
                "--out", str(out),
                "--date", date,
                "--dry-state",
            ]
        )

        run_out = out / date
        dest = demo_dir / date
        dest.mkdir(parents=True, exist_ok=True)
        pages = []
        for name, label in (("feed.html", "Feed"), ("replies.html", "Replies")):
            src = run_out / name
            if src.exists():
                shutil.copyfile(src, dest / name)
                pages.append({"file": f"{date}/{name}", "label": label})
    return {"date": date, "pages": pages}


def write_index(demo_dir: Path, manifest: dict) -> None:
    name, handle, bio = persona_meta()
    date = manifest["date"]
    cards = []
    for page in manifest["pages"]:
        cards.append(
            f'      <a class="card" href="{html.escape(page["file"])}">'
            f'<span class="card-label">{html.escape(page["label"])}</span>'
            f'<span class="card-sub">run of {html.escape(date)}</span></a>'
        )
    cards_html = "\n".join(cards) or "      <p>No demo pages were generated.</p>"
    generated = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(name)} — activist demo</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 3rem 1rem;
    background: #191b22; color: #e6e9ef;
    font: 16px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
  }}
  .column {{ max-width: 600px; margin: 0 auto; }}
  h1 {{ margin: 0 0 .25rem; font-size: 1.4rem; }}
  .handle {{ color: #9aa0b5; font-size: .95rem; }}
  .bio {{ margin: .75rem 0 0; color: #c3c8d4; font-size: .95rem; }}
  .note {{
    margin: 1.5rem 0; padding: .75rem 1rem; font-size: .85rem;
    background: #20283b; border-left: 3px solid #6364ff; border-radius: 6px;
    color: #c3c8d4;
  }}
  .cards {{ display: grid; gap: .75rem; margin-top: 1.5rem; }}
  .card {{
    display: flex; flex-direction: column; gap: .2rem;
    padding: 1rem 1.25rem; text-decoration: none;
    background: #282c37; border-radius: 12px; color: #e6e9ef;
    border: 1px solid transparent; transition: border-color .15s;
  }}
  .card:hover {{ border-color: #6364ff; }}
  .card-label {{ font-weight: 600; font-size: 1.05rem; }}
  .card-sub {{ color: #9aa0b5; font-size: .85rem; }}
  footer {{ margin-top: 2.5rem; color: #6b7186; font-size: .8rem; }}
  footer a {{ color: #8c8dff; }}
</style>
</head>
<body>
  <div class="column">
    <h1>{html.escape(name)}</h1>
    <div class="handle">{html.escape(handle)}</div>
    <p class="bio">{html.escape(bio)}</p>
    <div class="note">
      A static demo of the <strong>activist</strong> human-in-the-loop bot: the
      feed it <em>would have</em> posted and the replies it <em>would have</em>
      drafted, generated from fixture news and mentions. Nothing here was ever
      published — every item waits for a human in the real review queue.
    </div>
    <div class="cards">
{cards_html}
    </div>
    <footer>
      Regenerated {generated} ·
      <a href="https://github.com/matthewdeanmartin/activist">source on GitHub</a>
    </footer>
  </div>
</body>
</html>
"""
    (demo_dir / "index.html").write_text(doc, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the GitHub Pages demo site.")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="run date label")
    parser.add_argument("--demo-dir", type=Path, default=REPO_ROOT / "demo")
    args = parser.parse_args(argv)

    demo_dir = args.demo_dir.resolve()
    shutil.rmtree(demo_dir, ignore_errors=True)
    demo_dir.mkdir(parents=True)

    manifest = generate(args.date, demo_dir)
    write_index(demo_dir, manifest)
    print(f"demo built at {demo_dir} ({len(manifest['pages'])} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
