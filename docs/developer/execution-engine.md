# Execution Engine

## Engine protocol

The drafting seam is the `PersonaEngine` protocol in `engine/base.py`:

- `react(...)` drafts top-level posts from `NewsItem`
- `reply(...)` drafts replies from `Mention`

Anything implementing that protocol can be plugged into the pipeline.

## `MockBot`

`MockBot` is deterministic and does not use network access. It relies on fixture hints such as `supports`, `challenges`, `claim`, `new_stance`, and `asks`.

Use it when:

- writing tests
- debugging queue behavior
- validating pipeline invariants
- wanting byte-stable outputs

## `OpenRouterBot`

`OpenRouterBot` is the real LLM-backed engine. Important runtime behavior:

- uses OpenRouter’s OpenAI-compatible API
- can rotate through multiple candidate models
- retries once on TOML parse failure
- still defers all hard guardrails to ordinary Python checks

This split is important: prompts ask for compliance, but the code decides whether a draft survives.

## How to add a new engine

At minimum you need to:

1. implement the `PersonaEngine` protocol
2. return `Reaction` objects with valid `DraftPost` fields
3. register it through `engine/__init__.py` and CLI selection
4. make sure tests cover guardrail behavior and failure modes

The safest pattern is to keep drafting logic in the engine and everything policy-related outside it.
