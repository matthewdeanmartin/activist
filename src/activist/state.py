"""Load/save persona state: persona.toml, opinions.toml, knowledge.md, memory/."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import tomli_w

from .models import Opinion, Persona, SaidEntry

SEEN_FILE = "seen.jsonl"
SAID_FILE = "said.jsonl"
MENTIONS_FILE = "mentions.jsonl"
DIARY_FILE = "diary.md"


# --- persona.toml -----------------------------------------------------------


def load_persona(path: Path) -> Persona:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    identity = data["identity"]
    voice = data.get("voice", {})
    limits = data.get("limits", {})
    return Persona(
        name=identity["name"],
        handle=identity["handle"],
        bio=identity["bio"],
        disclosure=identity["disclosure"],
        voice_tone=voice.get("tone", ""),
        voice_rules=voice.get("rules", []),
        topics=data.get("beats", {}).get("topics", []),
        max_posts_per_run=limits.get("max_posts_per_run", 6),
        posts_per_hour=limits.get("posts_per_hour", 4),
    )


# --- opinions.toml ----------------------------------------------------------


def load_opinions(path: Path) -> dict[str, Opinion]:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    opinions: dict[str, Opinion] = {}
    for key, body in data.items():
        opinions[key] = Opinion(
            key=key,
            topic=body["topic"],
            stance=body["stance"],
            strength=float(body["strength"]),
            since=body["since"],
            basis=body["basis"],
            subject=body.get("subject", ""),
            history=body.get("history", []),
        )
    return opinions


def save_opinions(path: Path, opinions: dict[str, Opinion]) -> None:
    doc: dict[str, dict] = {}
    for key, op in opinions.items():
        body: dict = {
            "topic": op.topic,
            "stance": op.stance,
            "strength": op.strength,
            "since": op.since,
            "basis": op.basis,
        }
        if op.subject:
            body["subject"] = op.subject
        body["history"] = op.history
        doc[key] = body
    with path.open("wb") as fh:
        tomli_w.dump(doc, fh)


# --- knowledge.md -----------------------------------------------------------


def knowledge_sections(path: Path, topics: list[str]) -> str:
    """Return only the ``##`` sections of knowledge.md matching the topics.

    Token-efficient: when a real LLM is wired in, it only sees the beats
    the current article touches.
    """
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    wanted: list[str] = []
    for chunk in re.split(r"(?m)^##\s+", text)[1:]:
        heading = chunk.splitlines()[0].strip().lower()
        if any(topic.lower() in heading for topic in topics):
            wanted.append("## " + chunk.strip())
    return "\n\n".join(wanted)


# --- memory/ ----------------------------------------------------------------


def load_seen_ids(memory_dir: Path) -> set[str]:
    path = memory_dir / SEEN_FILE
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            ids.add(json.loads(line)["id"])
    return ids


def append_seen(memory_dir: Path, rows: list[dict]) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    with (memory_dir / SEEN_FILE).open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_said(memory_dir: Path, n: int = 5) -> list[SaidEntry]:
    path = memory_dir / SAID_FILE
    if not path.exists():
        return []
    entries: list[SaidEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(SaidEntry(**json.loads(line)))
    return entries[-n:]


def append_said(memory_dir: Path, entries: list[SaidEntry]) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    with (memory_dir / SAID_FILE).open("a", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(
                json.dumps(
                    {
                        "date": entry.date,
                        "post_id": entry.post_id,
                        "topic": entry.topic,
                        "opinion_keys": entry.opinion_keys,
                        "summary": entry.summary,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def load_handled_mentions(memory_dir: Path) -> set[str]:
    """Mention ids already replied to, declined, or gated."""
    path = memory_dir / MENTIONS_FILE
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            ids.add(json.loads(line)["id"])
    return ids


def append_handled_mentions(memory_dir: Path, rows: list[dict]) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    with (memory_dir / MENTIONS_FILE).open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_diary(memory_dir: Path, date: str, engine: str, notes: list[str]) -> None:
    if not notes:
        return
    memory_dir.mkdir(parents=True, exist_ok=True)
    with (memory_dir / DIARY_FILE).open("a", encoding="utf-8") as fh:
        fh.write(f"\n## {date} ({engine})\n\n")
        for note in notes:
            fh.write(f"- {note}\n")
