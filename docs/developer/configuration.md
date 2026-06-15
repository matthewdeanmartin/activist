# Configuration System

## Loader behavior

`load_config()` reads TOML into `AppConfig` and then validates:

- positive numeric intervals and ports
- known engine names
- known moderation engine names
- path existence for `persona` and `policies`
- optional app policy path existence

CLI flags then override selected config values at runtime, especially engine and model selection.

## Identity selection

The config chooses an identity key such as `TECH`. The Mastodon client then looks up secrets using that key. This makes multi-identity support mostly a matter of config and environment layout, even though each process instance operates on one identity at a time.

## Path strategy

Configurable paths allow you to relocate:

- the queue database
- persona state
- output artifacts
- policies
- dry-run publish log
- poster lock file

That matters if you want to package the app differently, run multiple environments, or isolate tests.

## Current limitations

The config format already includes settings for poster live mode, but the runtime still blocks live posting. That field is a design placeholder in today’s codebase, not an operator switch that can enable real publishing.
