# CLI Internals and Contributing

## CLI structure

`src/activist/cli.py` is a straightforward subcommand dispatcher. The current command set is:

- `run`
- `fetch`
- `ui`
- `poster`
- `replies`
- `moderate`
- `render`
- `reset-memory`

The CLI is also careful about Windows console encoding so Unicode output does not crash.

## Contributing mindset

The codebase is small enough that most features cut across a few core seams rather than one isolated file. Before changing behavior, identify which category you are actually modifying:

- input acquisition
- persona reasoning
- moderation policy
- lifecycle and queue semantics
- UI actions
- publishing semantics

That framing helps keep policy, prompting, and persistence responsibilities separated.

## Safe places to customize first

- `persona/persona.toml`
- `persona/opinions.toml`
- `persona/knowledge.md`
- `policies/*.txt`
- `activist.toml`
- engine prompt templates in `engine/openrouter.py`
- deterministic moderation rules in `moderation/mockmod.py`

## Higher-risk changes

Treat these areas carefully because they affect correctness across processes:

- `store.py` transition rules
- `poster.py` claim logic
- `reply_fetch.py` checkpoint semantics
- `ratelimit.py` spacing logic

## Docs contribution rule for this repo

When documenting behavior, prefer what the code currently does. Use `spec/` to explain intent and design constraints, but call out unimplemented pieces directly rather than implying they already work.
