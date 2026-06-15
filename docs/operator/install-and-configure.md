# Install and Configure

## Requirements

The package currently declares Python `>=3.14` in `pyproject.toml`.

Core runtime dependencies already included by the project:

- `httpx`
- `beautifulsoup4`
- `flask`
- `python-dotenv`
- `openai`
- `tomli-w`

## Install

Typical local install:

```bash
pip install activist
```

For working from a checkout, the repository also includes `pyproject.toml`, `uv.lock`, `Makefile`, and MkDocs configuration.

## Required local files

Activist expects these paths by default:

- `activist.toml`
- `.env`
- `persona/persona.toml`
- `persona/opinions.toml`
- `persona/knowledge.md`
- `policies/`

## Configure `activist.toml`

The active configuration loader is `src/activist/config.py`. Its current shape includes:

```toml
[identity]
mastodon_id = "TECH"
instances = ["mastodon.social"]

[fetch]
interval_minutes = 60
cache_dir = ".cache/feeds"
article_body = false
write_artifacts = true

[[feed]]
name = "CleanTechnica"
url = "https://cleantechnica.com/feed/"

[replies]
enabled = false
interval_minutes = 15

[engine]
name = "mockbot"
# model = "anthropic/claude-sonnet-4.5"

[moderation]
engine = "mockmod"

[rate_limit]
# posts_per_hour = 4

[ui]
host = "127.0.0.1"
port = 8765

[poster]
live = false
check_interval_minutes = 5

[paths]
db = "data/activist.db"
persona = "persona"
out = "out"
policies = "policies"
dryrun_log = "data/published_dryrun.jsonl"
poster_lock = "data/poster.lock"
```

## Configure `.env`

Mastodon credentials are selected by identity name. For identity `TECH`, the code expects:

- `MASTODON_ID_TECH_BASE_URL`
- `MASTODON_ID_TECH_CLIENT_ID`
- `MASTODON_ID_TECH_CLIENT_SECRET`
- `MASTODON_ID_TECH_ACCESS_TOKEN`

OpenRouter drafting or moderation additionally needs:

- `OPENROUTER_API_KEY`
- optionally `OPENROUTER_MODEL`
- optionally repeated `OPENROUTER_MODELS_FREE`
- optionally `OPENROUTER_ROTATE_MODELS`

## Validate before running

Sanity checks that matter operationally:

- `persona/persona.toml` must exist
- `policies/` must exist
- every `[[feed]]` entry must include a URL
- `poster.live` must stay `false` in the current codebase
