"""Render feed.toml into a single-file HTML review page.

stdlib string.Template only — loops and escaping live in Python, the
template is just the page shell.
"""

from __future__ import annotations

import html
import re
import tomllib
from importlib.resources import files
from pathlib import Path
from string import Template

from .engine.base import POST_CHAR_LIMIT

URL_RE = re.compile(r"(https?://[^\s<]+)")


def render_feed(feed_path: Path, out_path: Path | None = None) -> Path:
    """Render a queue file (feed.toml or replies.toml) to <same name>.html."""
    with feed_path.open("rb") as fh:
        data = tomllib.load(fh)
    run = data["run"]
    posts = data.get("post", [])

    cards = "\n".join(_post_card(p) for p in posts) or (
        '<div class="card empty">No posts this run — nothing new on the beat.</div>'
    )
    changes = [p["opinion_change"] for p in posts if "opinion_change" in p]
    template = files("activist").joinpath("templates/feed.html.tmpl").read_text(encoding="utf-8")
    page = Template(template).substitute(
        persona_name=html.escape(run.get("persona_name", "activist")),
        persona_handle=html.escape(run.get("persona_handle", "")),
        persona_bio=html.escape(run.get("persona_bio", "")),
        run_date=html.escape(run.get("date", "")),
        engine=html.escape(run.get("engine", "")),
        stats=(
            f"{run.get('items_ingested', 0)} ingested · "
            f"{run.get('items_relevant', 0)} relevant · "
            f"{run.get('posts', 0)} posts"
            + (f" · ⏱️ paced {run['posts_per_hour']}/hour" if run.get("posts_per_hour") else "")
            + _moderation_stats(run.get("moderation"))
        ),
        cards=cards,
        changes_html=_changes_html(changes),
        diary_html=_diary_html(run.get("diary", "")),
    )
    out = out_path or feed_path.with_suffix(".html")
    out.write_text(page, encoding="utf-8")
    return out


def _moderation_stats(moderation: dict | None) -> str:
    if not moderation:
        return " · ⏳ unmoderated"
    scope = ", ".join(moderation.get("instances", [])) or "app policy only"
    return (
        f" · 🛡️ moderated by {html.escape(moderation.get('engine', ''))} "
        f"({html.escape(scope)}): {moderation.get('errors', 0)} errors, "
        f"{moderation.get('warns', 0)} warns"
    )


def _rich_text(text: str) -> str:
    escaped = html.escape(text)
    linked = URL_RE.sub(r'<a href="\1">\1</a>', escaped)
    return linked.replace("\n", "<br>\n")


def _post_card(post: dict) -> str:
    count = post.get("char_count", 0)
    badge_class = "ok" if count <= POST_CHAR_LIMIT else "over"
    change_strip = ""
    if "opinion_change" in post:
        change = post["opinion_change"]
        change_strip = (
            '<div class="change-strip">🔄 <strong>Changed my mind</strong> '
            f'(<code>{html.escape(change["key"])}</code>)<br>'
            f'<span class="old">was: {html.escape(change["old_stance"])}</span> ▸ '
            f'<span class="new">now: {html.escape(change["new_stance"])}</span><br>'
            f'<span class="why">because: {html.escape(change["reason"])}</span></div>'
        )
    reply_strip = ""
    if post.get("reply_to_author"):
        reply_strip = (
            '<div class="reply-strip">↩️ replying to '
            f'<strong>{html.escape(post["reply_to_author"])}</strong>: '
            f'<em>“{html.escape(post.get("reply_to_text", ""))}”</em></div>'
        )
    if post.get("source_url"):
        source = (
            f'<div class="source">source: <a href="{html.escape(post["source_url"], quote=True)}">'
            f'{html.escape(post.get("source_title", ""))}</a></div>'
        )
    else:
        source = f'<div class="source">{html.escape(post.get("source_title", ""))}</div>'
    return f"""<article class="card">
  <div class="meta">
    <span class="badge {badge_class}">{count}/{POST_CHAR_LIMIT}</span>
    <span class="engine">{html.escape(post.get("engine", ""))}</span>
    <span class="created">{html.escape(post.get("created", ""))}</span>
  </div>
  {reply_strip}
  <div class="text">{_rich_text(post.get("text", ""))}</div>
  {change_strip}
  {_flags_strip(post.get("flags", []))}
  {source}
</article>"""


def _flags_strip(flags: list[dict]) -> str:
    if not flags:
        return ""
    rows = "".join(
        f'<li class="flag {html.escape(f.get("severity", "warn"))}">'
        f'{"⛔" if f.get("severity") == "error" else "⚠️"} '
        f'<code>{html.escape(f.get("policy", "app"))}/{html.escape(f.get("rule", ""))}</code> '
        f'{html.escape(f.get("detail", ""))}</li>'
        for f in flags
    )
    return f'<div class="flags-strip"><strong>Moderation flags</strong><ul>{rows}</ul></div>'


def _changes_html(changes: list[dict]) -> str:
    if not changes:
        return "<p>No opinions changed this run.</p>"
    rows = "".join(
        f"<li><code>{html.escape(c['key'])}</code>: "
        f'<span class="old">{html.escape(c["old_stance"])}</span> ▸ '
        f'<span class="new">{html.escape(c["new_stance"])}</span></li>'
        for c in changes
    )
    return f"<ul>{rows}</ul>"


def _diary_html(diary: str) -> str:
    if not diary.strip():
        return "<p>(empty)</p>"
    items = "".join(f"<li>{html.escape(line)}</li>" for line in diary.splitlines() if line.strip())
    return f"<ul>{items}</ul>"
