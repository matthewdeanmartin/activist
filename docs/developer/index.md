# Developer Overview

Activist is built to be customized. Even when you only want to change configuration, it helps to understand the code seams because the project deliberately keeps important behavior in ordinary Python rather than burying it in prompts.

The main extension points are:

- engines in `src/activist/engine/`
- moderation in `src/activist/moderation/`
- queue lifecycle in `src/activist/store.py`
- scheduling in `src/activist/ratelimit.py`
- persona and memory files under `persona/`
- UI routes and templates in `src/activist/web/`

The developer docs below explain those seams in terms of the implemented code, not just the intended design.
