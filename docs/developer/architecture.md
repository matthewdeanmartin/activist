# Architecture

## Package layout

The runtime is a single Python package with multiple CLI entry points rather than separate services.

Core layers:

- ingestion: `ingest.py`, `fetch.py`, `digest.py`, `reply_fetch.py`
- filtering and pacing: `relevance.py`, `ratelimit.py`
- drafting: `engine/`
- moderation: `moderation/`
- persistence: `state.py`, `store.py`, `queue_io.py`
- presentation: `render.py`, `web/`
- orchestration: `pipeline.py`, `poster.py`, `cli.py`

## Two execution families

There are two parallel workflows in the code:

- fixture-first workflows for offline development: `activist run`, `activist replies`, `activist moderate`, `activist render`
- live queue workflows: `activist fetch`, `activist ui`, `activist poster`

The project keeps them aligned by reusing the same model types and engine seams.

## Shared model types

`src/activist/models.py` defines the main data contracts:

- `NewsItem`
- `Opinion`
- `Persona`
- `OpinionChange`
- `DraftPost`
- `Mention`
- `SaidEntry`
- `Flag`
- `Reaction`

These dataclasses are the easiest place to start when tracing behavior across modules.
