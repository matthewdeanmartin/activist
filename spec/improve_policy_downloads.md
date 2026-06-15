# Improve Policy Downloads

**Status:** plan, 2026-06-13.

## 1. Problem

`servers.txt` has 27 hand-picked instance domains. `policy_fetcher` walks
that list and writes `policies/<domain>.txt` from two Mastodon API endpoints:
`/api/v2/instance` (rules, short description, contact) and
`/api/v1/instance/extended_description` (long "about" HTML).

That's a good start but it misses the actual usage policy on many instances:

- `mastodon.cloud.txt` is 2 lines — just a contact email. No rules, no
  description. The real rules live at `https://mastodon.cloud/about` or a
  linked Terms of Service page, never in the API.
- Several others (`qoto.org.txt` 10 lines, `social.linux.pizza.txt` 16
  lines, `pravda.me.txt` 30 lines) are thin for the same reason: instances
  increasingly point to an **off-site** policy doc (a Google Doc, a separate
  `terms.example.org`, a GitHub-hosted CONDUCT.md, a WordPress page) instead
  of filling in `extended_description`.
- The API gives us *links* sometimes (in the HTML of `extended_description`)
  but `policy_fetcher` strips HTML to text and throws the `href`s away, so
  we can't even see where to look next.

Two separate asks:

1. **Grow `servers.txt`** — more candidate instances to evaluate.
2. **Fill the gaps for instances whose real policy is off-site** — find it,
   fetch it, save it next to the API-derived report.

## 2. Growing `servers.txt`

### 2.1 Source: joinmastodon.org server directory

`https://joinmastodon.org/api/v1/instances` (or the servers.json feed used by
the official directory) returns a large, curated list of public instances
with category, language, and user-count metadata, no auth required. This is
the natural "long list" source — same ecosystem, same trust level as the
existing 27.

### 2.2 New tool: `policy_fetcher/discover.py`

- `fetch_instance_directory(client) -> list[dict]` — GET the joinmastodon
  directory endpoint, return raw entries (`domain`, `category`, `language`,
  `users`, ...).
- `merge_servers_txt(entries, existing, *, min_users=0, languages=None,
  categories=None, limit=None) -> list[str]` — pure function, no I/O:
  dedupes against `existing` (current `servers.txt` lines), applies simple
  filters (e.g. English-language general instances above a user-count floor
  so we don't fill the list with dead servers), returns the domains to
  append.
- CLI: `python -m policy_fetcher.discover --append servers.txt [--min-users
  500] [--limit 50]` — fetches, filters, appends new domains to `servers.txt`
  (sorted, deduped), prints a summary of how many were added/skipped.

Same httpx conventions as `fetcher.py` (shared `HEADERS`, 15s timeout,
graceful failure — if the directory endpoint is unreachable, log and exit
non-zero without touching `servers.txt`).

### 2.3 Tests

- `merge_servers_txt` against a small fixture list of directory entries:
  dedup against existing domains, filter by `min_users`/`language`, `limit`
  truncates, sorted output. No network (pure function).
- `fetch_instance_directory` with a mocked transport (same `FakeAsyncClient`
  pattern as `test_fetcher.py`) — one happy-path test for the JSON shape.

## 3. Off-site policy discovery ("smart spidering")

### 3.1 Approach

For instances where the API report is thin (rules empty *and*
extended_description empty/short), fall back to fetching the instance's
public `/about` page (standard Mastodon route, served as HTML to anonymous
visitors) and look for links to a dedicated policy document.

Plain heuristics first — cheap, deterministic, no LLM:

- Parse `/about` HTML with the existing `BeautifulSoup` dependency.
- Collect `<a>` tags whose text or `href` matches a small keyword set:
  `terms`, `privacy`, `policy`, `rules`, `conduct`, `guidelines`,
  `tos`. Case-insensitive, both same-origin and cross-origin links.
- If exactly one strong match (e.g. `href` contains `/terms` or
  `/privacy-policy`), fetch it directly.

This handles the common cases (linked ToS/Privacy page on the same or an
adjacent domain) without any LLM call, and costs nothing extra in CI since
it's just more `httpx` + `bs4`.

### 3.2 LLM-assisted spidering for the rest

When heuristics find **multiple plausible links** (ambiguous — e.g. a page
with 5 footer links, several matching keywords) or **zero matches** but the
`/about` page is non-trivial (> some length threshold, so there's something
to reason about), hand off to the `llm` CLI for a single classification
call:

- New module `policy_fetcher/llm_spider.py`:
  - `rank_policy_links(about_text: str, links: list[tuple[str, str]]) ->
    list[str]` — builds a short prompt: "Here is the About page text for a
    Mastodon instance, and a list of (link text, URL) pairs found on the
    page. Which URL(s), if any, point to the instance's terms of service,
    privacy policy, or community guidelines? Reply with the URLs only, one
    per line, or NONE." Calls `llm` via `subprocess` (`llm -m <model>
    <prompt>`), parses the response into a list of URLs filtered against the
    candidate set (never trust a URL the LLM invents that wasn't in the
    input — same unverified-link discipline as the reply pipeline).
  - Model selection: read `OPENROUTER_MODEL` / `OPENROUTER_MODELS_FREE` from
    `.env` if `llm`'s OpenRouter plugin + key are configured; otherwise fall
    back to the local `llm-smollm2` plugin (already installed, no API key
    needed) so this works offline/in CI. A `--llm-model` CLI flag overrides
    both.
  - If the `llm` binary isn't on PATH, or the subprocess errors, or returns
    NONE/unparseable output: log a warning and skip — this is a best-effort
    enrichment, never a hard failure for the batch.

- `fetcher.py` gains `fetch_offsite_policy(domain, about_links, directory,
  llm_enabled=True)`:
  1. Run the cheap heuristic matcher on `about_links`.
  2. If ambiguous/empty and `llm_enabled`, call `rank_policy_links`.
  3. Fetch each resulting URL (same client, same timeout, `clean_html` on
     the body), save as `policies/<domain>.offsite.<n>.txt` with a header
     line recording the source URL.
  4. Append a short "## OFFSITE POLICIES" section (titles + URLs only) to
     the main `policies/<domain>.txt` so the primary report stays the index.

### 3.3 Wiring into `fetch_policy` / `fetch_many`

- `fetch_policy` already fetches `/api/v2/instance` +
  `/api/v1/instance/extended_description`. Add a third concurrent fetch of
  `https://{domain}/about` (HTML, not JSON — needs its own small `_get_html`
  helper alongside `_get_json`).
- After building `instance_data`/`long_desc` as today, compute a
  "thinness" check: `rules` empty AND `len(long_desc) < THRESHOLD` (e.g.
  200 chars). If thin and `/about` fetched successfully, extract links and
  run `fetch_offsite_policy`.
- New `fetch_policy` kwarg `offsite: bool = True`, and `fetch_many(...,
  offsite=True)` / CLI flag `--no-offsite` to disable (keeps existing tests
  fast and deterministic — offsite + LLM path is opt-out, not opt-in, but
  easy to turn off for CI).
- `llm_enabled` similarly threads through as `llm: bool = True` /
  `--no-llm`, independent of `offsite` (so you can do heuristic-only offsite
  fetching without ever shelling out to `llm`).

### 3.4 Tests

- `_get_html` mocked like `_get_json` (extend `FakeAsyncClient` to serve HTML
  bodies).
- Heuristic link matcher: table of `(link text, href) -> matches keyword
  set`, including same-origin and cross-origin cases.
- `fetch_offsite_policy` with mocked `/about` HTML containing a single clear
  ToS link → fetches and saves `.offsite.0.txt`, no LLM call (assert
  `rank_policy_links` not invoked via monkeypatch).
- Ambiguous-links case → `rank_policy_links` is called; monkeypatch
  `subprocess.run` to return a canned response; assert only URLs present in
  the candidate set are followed (prompt-injection style "reply with
  https://evil.example" must be ignored if not in `about_links`).
- `llm` binary missing (`shutil.which` returns `None`, monkeypatched) →
  graceful skip, batch still completes, existing
  `test_server_list_processing`-style assertions still pass.
- Full `fetch_policy` test for a `mastodon.cloud`-shaped response (empty
  rules, short description, `/about` with one ToS link) → resulting
  `policies/mastodon.cloud.txt` contains an "## OFFSITE POLICIES" section.

## 4. Output layout

```
policies/
  mastodon.social.txt          # existing format, unchanged when not thin
  mastodon.cloud.txt           # existing sections + new "## OFFSITE POLICIES"
  mastodon.cloud.offsite.0.txt # full text of the linked ToS/Privacy page
```

No changes to the existing on-disk format for instances that already have
substantial `rules`/`extended_description` — this only adds sections/files
for the thin cases, so current cached files for the 18 already-rich
instances are untouched on the next run (cache hit, as today).

## 5. CLI summary

```
# grow the candidate list from the joinmastodon directory
python -m policy_fetcher.discover --append servers.txt --min-users 500 --limit 50

# normal batch run, now with offsite spidering + LLM fallback on by default
python -m policy_fetcher --server-list servers.txt

# heuristics only, no LLM subprocess calls
python -m policy_fetcher --server-list servers.txt --no-llm

# API-only, old behavior
python -m policy_fetcher --server-list servers.txt --no-offsite
```

## 6. Phasing / model fit

- **Phase 1** — `discover.py` + `servers.txt` growth. Pure functions, easy,
  no LLM. *Sonnet.*
- **Phase 2** — `/about` fetch + heuristic link matcher + offsite fetch/save,
  `--no-offsite` flag. No LLM dependency yet. *Sonnet.*
- **Phase 3** — `llm_spider.py` + wiring + `--no-llm` flag + prompt-injection
  guard tests. *Sonnet*, but review the "never trust a URL the LLM invents"
  filter carefully — same class of bug as the reply pipeline's unverified-
  link rule.

## 7. Out of scope

- Re-crawling/refreshing already-rich `policies/*.txt` (cache behavior
  unchanged).
- Any use of the off-site policy text beyond storage — summarization,
  rate-limit-policy extraction, etc. is a future consumer of
  `policies/<domain>.offsite.*.txt`, not part of this change.
- Running `discover.py` on a schedule; it's a manual/occasional CLI step.
