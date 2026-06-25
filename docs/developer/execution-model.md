# Pipeline Execution Model

## Fixture post pipeline

`activist run` follows this broad flow:

1. parse XML fixtures into `NewsItem` objects
2. load persona, opinions, knowledge, and recent memory
3. filter for relevant topics
4. call `engine.react(...)`
5. enforce pacing and one-post-per-opinion-key-per-run rules
6. write persona state updates
7. write `feed.toml` and render HTML

The orchestrator for that path is `pipeline.run()`.

## Live fetch pipeline

`activist fetch` reuses the same engine loop but changes the source and sink:

1. fetch live RSS or Atom feeds with conditional GET
2. dedupe against `seen.jsonl`
3. improve summaries with `digest.py`
4. run `react_to_items(...)`
5. moderate each draft
6. convert drafts to `ContentRow`
7. insert them into SQLite as `pending_review`
8. optionally emit legacy debug artifacts under `out/`

## Live replies pipeline

`activist fetch --replies` or `--only-replies` does this:

1. read mention notifications through `MastodonReader`
2. map API JSON to `Mention`
3. apply consent gates
4. derive relevant opinions and knowledge slices
5. call `engine.reply(...)`
6. moderate each reply draft
7. insert drafts into SQLite as `pending_review`
8. checkpoint `since_id` in the store and append handled mentions to memory

## Poster tick

`poster_tick(...)` does this:

1. load due approved rows for one identity
2. enforce minimum spacing from the last published item
3. claim a row with `approved -> publishing`
4. publish through the configured transport
5. mark `published` on success or `failed` on transport exception

By default the transport is `DryRunTransport`, so this flow mutates local state but not Mastodon. With the triple publish gate open (`[poster].live = true`, `ACTIVIST_LIVE=1`, `--live`), step 4 uses `MastodonTransport` and really does publish — see [Targeting mastodon-mock](mastodon-mock.md) to exercise that path against a disposable local server.
