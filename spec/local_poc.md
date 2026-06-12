# Local POC Plan: Persona-Driven Low-Carbon Activist Bot

**Status:** implemented 2026-06-11 (`src/activist/`, `persona/`, `fixtures/`, `tests/`)
**Scope:** the "Transform Input Flow" from `docs/TODO.md`, run entirely locally.
News fixtures in → would-be Mastodon posts out. Nothing is ever posted; the
deliverable of a run is a reviewable rendering of "the feed that would have been."

---

## 1. Goal and non-goals

### Goal

Simulate an activist bot whose beat is low(er)-carbon lifestyle (heat pumps,
e-bikes, induction stoves, home insulation, low-carbon diet, transit). It reads
public open-source news and transforms it into opinionated posts in a consistent
voice with continuity over time:

> "Brand XYZ used to be my top pick for heat pumps, but ABC's new cold-climate
> model has changed my mind."

The thing that distinguishes this from an RSS summarizer is **state**: the bot
has opinions, background knowledge, and memory of what it has read and said
before, and every post is generated *against* that state. When the news
contradicts a held opinion, the bot updates the opinion and the post narrates
the change of mind.

### Non-goals (this phase)

- No network posting, no Mastodon API, no credentials.
- No live RSS fetching (fixtures only; a `--fetch` flag is a later add).
- No moderation pass (Phase 2) and no reply handling (Phase 3).
- No real LLM calls by default — the deterministic MockBot is the default
  engine. OpenRouter wiring instructions are in §9 but are not run in CI.

---

## 2. Architecture overview

```
fixtures/feeds/*.xml ──┐
                       ▼
              [1] Ingestor          parse RSS/Atom → NewsItem list
                       ▼
              [2] Relevance filter  keyword/topic match vs persona beats
                       ▼
              [3] Persona engine    (MockBot | OpenRouterBot)
                       │            reads: opinions.toml, knowledge.md, memory/
                       │            emits: DraftPost(s) + OpinionChange(s)
                       ▼
              [4] State writer      apply opinion changes, append memory entries
                       ▼
              [5] Queue writer      out/<run-date>/feed.toml   (source of truth)
                       ▼
              [6] Renderer          feed.toml → out/<run-date>/feed.html
```

Every stage is a pure-ish function over files on disk, so a run is reproducible
and the whole state is reviewable/revertable with git (`persona/` is committed;
`out/` is gitignored or committed at the user's discretion).

---

## 3. Directory layout

Code goes in `src/activist/` — `pyproject.toml` already declares the package,
build targets, and the `activist = "activist.cli:main"` console script.

```
src/activist/
    __init__.py
    cli.py              # argparse CLI: `activist run`, `activist render`, `activist reset-memory`
    models.py           # dataclasses: NewsItem, DraftPost, OpinionChange, RunResult
    ingest.py           # RSS/Atom parsing (stdlib xml.etree; no feedparser dep)
    relevance.py        # topic/keyword scoring against persona beats
    engine/
        __init__.py
        base.py         # PersonaEngine protocol (the LLM seam)
        mockbot.py      # deterministic rule-based engine (default)
        openrouter.py   # real LLM engine, OpenAI-compatible client (§9)
    state.py            # load/save opinions.toml, append memory, knowledge loader
    queue_io.py         # write/read feed.toml (tomllib + tomli-w)
    render.py           # feed.toml → HTML via stdlib string.Template
    templates/
        feed.html.tmpl  # Mastodon-timeline-ish single-file HTML, inline CSS

persona/
    persona.toml        # who the bot is: name, bio, voice rules, beats
    opinions.toml       # the opinions file — bot-updated, human-readable
    knowledge.md        # stable background facts the bot "knows"
    memory/
        seen.jsonl      # one line per NewsItem ever ingested (dedupe)
        said.jsonl      # one line per approved-for-feed post (continuity)
        diary.md        # human-readable digest the bot appends per run

fixtures/
    feeds/
        cleantechnica-sample.xml
        canarymedia-sample.xml
        heatpumped-sample.xml
    README.md           # provenance of each fixture, date captured

out/                    # gitignored
    2026-06-11/
        feed.toml
        feed.html
        run.log
```

---

## 4. Persona state files

### 4.1 `persona/persona.toml` — identity (human-edited only)

```toml
[identity]
name = "Lowwatt"
handle = "@lowwatt@example.invalid"
bio = "Human-in-the-loop bot tracking the low-carbon lifestyle beat. Runs on news, opinions, and a memory file. Operator: @matthew"
disclosure = "🤖 bot post, human approved"   # appended to every post

[voice]
tone = "enthusiast friend, not press release"
rules = [
  "first person, but never claims human experiences (no 'my house', 'I drove')",
  "always links the source article",
  "opinions are owned: 'I think', 'changed my mind', never 'experts say'",
  "no engagement bait, no rage, no dunking",
]

[beats]
topics = ["heat pumps", "e-bikes", "induction stoves", "home insulation",
          "EVs", "rooftop solar", "transit", "low-carbon diet"]
```

### 4.2 `persona/opinions.toml` — the opinions file (bot-updated)

This is the load-bearing file. Each opinion is a keyed table with a stance,
strength, and history. The bot updates it via stage [4]; because it is TOML
under git, every change of mind is a reviewable diff.

```toml
[heat-pump-top-pick]
topic = "heat pumps"
stance = "Brand XYZ's HP-9 is the best cold-climate heat pump for most homes"
strength = 0.8            # 0..1 conviction; low strength = easily swayed
since = "2026-04-02"
basis = "COP 3.1 at -15C, field data from the NEEP database"
history = [
  { date = "2026-04-02", stance = "XYZ HP-9 is top pick", trigger = "initial seed" },
]

[ebike-vs-car]
topic = "e-bikes"
stance = "an e-bike replaces the second car for most two-car households"
strength = 0.9
since = "2026-03-15"
basis = "trip-length distribution studies"
history = [ { date = "2026-03-15", stance = "initial", trigger = "initial seed" } ]
```

Seed it with ~8–12 opinions across the beats, several deliberately set up to be
contradicted by the fixtures (that's what produces the "changed my mind" posts).

### 4.3 `persona/knowledge.md` — background knowledge (human-edited)

Stable facts and framing the bot may assume without citation: what COP means,
why methane leakage matters, typical e-bike price ranges. Markdown with `##`
sections per beat. The engine receives only the sections matching the article's
topic (token-efficient when the real LLM is wired in).

### 4.4 `persona/memory/`

- `seen.jsonl` — `{id, url, title, date_seen, topic}` per ingested item.
  Dedupe: an item whose URL or title-hash is present is skipped.
- `said.jsonl` — `{date, post_id, topic, opinion_keys, summary}` per generated
  post. Enables continuity ("as I posted last week…") and per-topic pacing
  (don't post about heat pumps three times in one run).
- `diary.md` — append-only, one short paragraph per run written by the engine:
  what it read, what changed its mind, what it ignored. Purely for the human.

---

## 5. Data model and the TOML queue

`models.py` dataclasses (plain dataclasses; pydantic not needed at this size):

```python
@dataclass
class NewsItem:
    id: str            # sha256 of url, first 12 hex chars
    feed: str
    title: str
    url: str
    published: str     # ISO date
    summary: str       # text-stripped via bs4 (already a dependency)

@dataclass
class OpinionChange:
    key: str               # e.g. "heat-pump-top-pick"
    old_stance: str
    new_stance: str
    trigger_item: str      # NewsItem.id
    reason: str

@dataclass
class DraftPost:
    id: str
    created: str
    status: str            # always "draft" in this phase
    text: str              # the would-be toot, incl. disclosure footer
    char_count: int        # must be <= 500
    source_url: str
    source_title: str
    opinion_keys: list[str]    # opinions consulted
    opinion_change: OpinionChange | None
    engine: str            # "mockbot" or model id
```

### `out/<date>/feed.toml`

The queue file is the single source of truth for a run; HTML is derived from it.
TOML chosen per user preference: token-efficient for LLM round-trips, diffable,
and `tomllib` reads it with zero dependencies.

```toml
[run]
date = "2026-06-11"
engine = "mockbot"
items_ingested = 14
items_relevant = 5
posts = 4

[[post]]
id = "a3f9c1d20e77"
created = "2026-06-11T09:00:00"
status = "draft"
text = """Brand XYZ's HP-9 used to be my top pick for cold-climate heat pumps. ABC's new
GW-200 just posted a COP of 3.4 at -20C in independent testing — that changes my mind.
Sorry XYZ, the crown moves. https://example.com/abc-gw200-review
🤖 bot post, human approved"""
char_count = 311
source_url = "https://example.com/abc-gw200-review"
source_title = "ABC GW-200 cold-climate test results"
opinion_keys = ["heat-pump-top-pick"]
engine = "mockbot"

[post.opinion_change]
key = "heat-pump-top-pick"
old_stance = "Brand XYZ's HP-9 is the best cold-climate heat pump for most homes"
new_stance = "ABC's GW-200 is the best cold-climate heat pump for most homes"
reason = "independent test shows higher COP at lower temp than the HP-9"
```

**Dependency note:** Python 3.14's `tomllib` is read-only. Add `tomli-w` to
`[project.dependencies]` for writing. (Alternative: emit TOML with a small
hand-rolled writer — not worth it; `tomli-w` is tiny and pure-Python.)

---

## 6. The engine seam (`engine/base.py`)

This is the only place the mock and the real LLM differ. Everything upstream
and downstream is shared.

```python
class PersonaEngine(Protocol):
    def react(
        self,
        item: NewsItem,
        persona: Persona,            # parsed persona.toml
        opinions: dict[str, Opinion],# parsed opinions.toml (relevant subset)
        knowledge: str,              # matching knowledge.md sections
        recent_said: list[SaidEntry],# last N said.jsonl entries for continuity
    ) -> Reaction: ...

@dataclass
class Reaction:
    post: DraftPost | None       # None = "read it, nothing worth saying"
    opinion_changes: list[OpinionChange]
    diary_note: str
```

### 6.1 `mockbot.py` — deterministic engine (the default)

No randomness, no network. Same inputs → byte-identical outputs (seeded only by
content hashes), so it's fully unit-testable.

Rules, in order:

1. **Challenge detection.** Fixture items carry structured hints in a custom
   RSS element `<activist:hint>` (e.g. `challenges=heat-pump-top-pick;
   claim=ABC GW-200 COP 3.4 @ -20C`). The ingestor passes hints through. If an
   item challenges an opinion whose `strength < 0.85`, MockBot emits a
   **changed-my-mind post** from a sentence template:
   `"{old_subject} used to be my {role}, but {new_evidence} has changed my
   mind. {one_liner} {url}"` — plus the matching `OpinionChange`.
   If `strength >= 0.85`, it emits a **pushback post** instead ("Interesting
   claim from {source}, but I'm not convinced yet — {basis}.") and a history
   entry without changing stance.
2. **Reinforcement.** If the item supports an existing opinion, emit an
   opinion-flavored commentary post: `"This is why {stance_restated}. {url}"`,
   and bump `strength` by +0.05 (capped 1.0).
3. **Continuity.** If `said.jsonl` shows a post on the same `opinion_key`
   within the run history, prepend a callback clause: `"Last time I said
   {prior_summary} — today's news backs that up:"`.
4. **Pacing.** Max 1 post per opinion key per run, max N posts per run
   (configurable, default 6). Excess relevant items get a diary mention only.
5. **Abstention.** Relevant item, no opinion matched → `post=None`,
   diary note "read but had nothing to add" (resisting the summarizer urge is
   itself a feature).

The `<activist:hint>` element is a fixture-only affordance: it makes the
deterministic engine produce *interesting* state transitions without NLP. The
OpenRouter engine ignores hints and works from the article text itself. Real
feeds won't have hints, which is fine — hints only gate rule 1's precision,
and by then the real engine is doing that job.

### 6.2 Relevance filter (`relevance.py`)

Shared by both engines (cheap pre-filter before any LLM tokens are spent):
lowercase keyword/phrase match of title+summary against `persona.beats.topics`
plus a per-topic synonym list. Score = matched-term count; threshold = 1.
Misses are logged to `seen.jsonl` with `relevant=false`.

---

## 7. Rendering (`render.py` + `templates/feed.html.tmpl`)

`feed.toml → feed.html` with **stdlib `string.Template`** — no Jinja dependency.
The template is one HTML file with inline CSS styled like a Mastodon timeline:

- Header card: persona avatar placeholder, name, handle, bio, run stats.
- One card per post: text (URLs auto-linked), char count badge
  (green ≤ 500, red over), source link, engine tag.
- **Changed-my-mind posts get a highlighted strip**: old stance ▸ new stance ▸
  reason — so the reviewer can audit the state transition, not just the prose.
- Footer: opinion diff summary for the run (every `OpinionChange`), and the
  diary entry.

Renderer logic: parse `feed.toml` with `tomllib`, build the per-post HTML
fragments in Python, substitute into the page template. (Loops live in Python,
not the template — that's what makes `string.Template` sufficient.)

`activist render out/2026-06-11/feed.toml` re-renders without re-running the
pipeline, so template tweaks don't touch state.

---

## 8. CLI, tests, and workflow

### CLI (`cli.py`)

```
activist run    [--fixtures DIR] [--date YYYY-MM-DD] [--engine mockbot|openrouter] [--dry-state]
activist render <feed.toml>
activist reset-memory [--keep-opinions]
```

- `run` executes stages 1–6. `--dry-state` skips stage 4 (state writes) for
  experimenting without mutating `persona/`.
- `--date` defaults to today; it namespaces `out/` and timestamps memory.

### Run workflow (the human loop, this phase)

1. `uv run activist run`
2. Open `out/<date>/feed.html`, read the feed that would have been.
3. Like it? Commit `persona/` (the opinion/memory diffs are the interesting
   review surface). Don't like it? `git checkout -- persona/` and tweak
   opinions/templates/fixtures, rerun.

### Tests (pytest, per existing tox/pytest setup)

- `test_ingest.py` — fixture XML → expected `NewsItem`s; malformed feed
  degrades gracefully (skip item, log).
- `test_relevance.py` — on/off-topic classification table.
- `test_mockbot.py` — the core suite: given seeded opinions + a challenging
  hint item, assert a changed-my-mind post with correct `OpinionChange`;
  strength≥0.85 yields pushback; reinforcement bumps strength; pacing cap;
  dedupe via `seen.jsonl`; determinism (two identical runs → identical
  `feed.toml` minus timestamps, or freeze time).
- `test_state.py` — opinions round-trip through TOML preserving history;
  memory appends are idempotent per item id.
- `test_render.py` — feed.toml → HTML contains each post text, escapes HTML
  in article titles (bs4 strips tags at ingest, but render must escape too),
  flags over-500-char posts.
- `test_e2e.py` — full `run` against fixtures into a tmp dir; golden-file
  compare of `feed.toml`.

### New dependencies

- `tomli-w` (runtime) — TOML writing. That's it. RSS parsing is
  `xml.etree.ElementTree`, templating is `string.Template`, HTML stripping
  reuses the existing `beautifulsoup4`.

---

## 9. Wiring up OpenRouter (instructions for later, not part of POC build)

The seam is `PersonaEngine`. `engine/openrouter.py` implements the same
protocol using the **already-present `openai` dependency** pointed at
OpenRouter's OpenAI-compatible endpoint:

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)
```

Steps when you're ready:

1. Put `OPENROUTER_API_KEY=sk-or-...` in `.env` (loaded via the existing
   `python-dotenv` dependency; ensure `.env` is gitignored).
2. Pick a model, e.g. `anthropic/claude-sonnet-4-6` or any OpenRouter model id;
   configure as `--model` flag or `[engine.openrouter]` table in `persona.toml`.
3. Prompt assembly (one chat call per relevant `NewsItem`):
   - **system**: persona identity + voice rules + hard constraints
     (≤ 500 chars incl. disclosure footer, must include source URL, no human
     experience claims, may decline by returning `post = ""`).
   - **user**: the matching `knowledge.md` sections, the relevant opinion
     entries (TOML excerpt verbatim — it's compact and the model can quote
     stances exactly), last ~5 `said.jsonl` summaries, then the `NewsItem`
     title + summary + URL.
   - **response format**: ask for a TOML body matching the `Reaction` shape
     (`post`, `opinion_changes`, `diary_note`) and parse with `tomllib`;
     on parse failure, retry once with the error appended, then abstain.
4. Guardrails stay in code, not in the prompt: char-count check, URL-present
   check, opinion-key validation (a change to a nonexistent key is dropped and
   logged), strength clamping, pacing caps — all enforced by stage [4]/[5]
   exactly as for MockBot.
5. Keep MockBot the default engine; `--engine openrouter` opts in. CI and
   tests never hit the network.

---

## 10. Roadmap after this POC

- **Phase 2 — Moderator bot.** ✅ Implemented 2026-06-11
  (`src/activist/moderation/`). A second pass over `feed.toml`:

  ```
  activist moderate out/<date>/feed.toml --instance infosec.exchange --instance mas.to [--engine openrouter]
  ```

  Two layers. `MockModerator` (always runs): the code-enforceable content
  rules from `docs/draft_governing_policy.md` — char limit, disclosure footer
  present, source link present, hashtag bans, cold @-mentions,
  human-experience-claim regexes, unverified links in replies.
  `OpenRouterModerator` (`--engine openrouter`, layered on top): reads the
  full policy texts against each post for the judgment calls — tone, sarcasm,
  controversy, impersonation. Same free-first model rotation as the persona
  engine (shared `RotatingCompleter`).

  **Rate limiting is NOT moderation.** Pacing lives in `ratelimit.py` as
  ordinary code: `activist run`/`activist replies` take `--instance DOMAIN`
  (repeatable), parse hourly limits out of `policies/<server>.txt` prose
  ("one post per hour" etc.), take the strictest of those and the persona's
  `posts_per_hour` (app policy §3, default 4), and schedule draft `created`
  timestamps at the resulting spacing (4/hour → 15-minute slots, 1/hour →
  hourly). The moderator never sees rate rules.

  Output: `[[post.flags]]` (severity/policy/rule/detail) written back into
  the same feed.toml plus a `[run.moderation]` summary; the HTML gets a
  purple moderation strip per flagged post and a 🛡️/⏳ status in the header.
  Re-moderation replaces prior flags (idempotent). Posts are flagged, never
  silently dropped — the human adjudicates.
- **Phase 3 — Replies.** ✅ Implemented 2026-06-11 (`src/activist/replies.py`,
  `fixtures/mentions-sample.toml`).

  ```
  activist replies [--mentions fixtures/mentions-sample.toml] [--engine openrouter] [--instance DOMAIN]
  ```

  Simulated inbound mentions (TOML fixture) → consent gates **in ordinary
  code** before any engine sees a mention: explicit @mention of the bot's
  handle required (silence until summoned), `#nobot` in the author bio
  respected, bot authors skipped (no bot-to-bot loops), already-handled
  mentions deduped via `memory/mentions.jsonl`. Survivors go through the
  same `PersonaEngine` seam (`MockBot.reply` / `OpenRouterBot.reply` with a
  reply-specific prompt), the same rate-limit slot scheduling, and out to
  `out/<date>/replies.toml` + `replies.html` (reply cards show a quoted
  "↩ replying to" strip). `activist moderate` works on replies.toml
  unchanged; replies are exempt from cold-mention and missing-source-link,
  and any URL in a reply is flagged `unverified-link` (the pipeline supplied
  none, so the model invented it — caught live on the first real Gemma run).
- **Later.** Live RSS fetching with on-disk cache; approval queue with
  persisted approve/reject status in `feed.toml`; actual Mastodon posting
  behind the human-approval gate.
