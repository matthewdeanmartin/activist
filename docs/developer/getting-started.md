# Getting Started

## Local setup

From a repository checkout:

```bash
pip install -e .
```

Or with the repo's existing toolchain:

```bash
uv sync
```

## First commands to run

These give the quickest orientation without needing live credentials:

```bash
activist run --engine mockbot
activist replies --engine mockbot
pytest
```

Then inspect:

- `out/<date>/feed.toml`
- `out/<date>/feed.html`
- `out/<date>/replies.toml`
- `persona/memory/`

## When to switch to the live queue path

Move to the live path when you want to work on:

- config loading
- RSS fetching and caching
- SQLite queue behavior
- review UI behavior
- Mastodon mention ingestion
- poster scheduling

The relevant commands are:

```bash
activist fetch --config activist.toml --dry-run
activist ui --config activist.toml
activist poster --config activist.toml
```
