# Checks by Enforcement Mechanism

The cross-cutting view: for every rule family that survives the "doesn't
apply to green-energy advocacy text" filter (see `00_overview.md` bucket 1),
what actually checks it — code, an LLM pass, or the human reviewer in
`pending_review`?

Three columns:

- **Mechanical** — plain code, deterministic, no model call. Cheapest,
  runs first, can run on every draft with zero marginal cost.
- **LLM pre-check** — a model call before `pending_review`, to *flag*
  (never silently fix or silently reject) for the human. Per
  `real_overview.md` §2: "MockModerator always runs; LLM moderation layered
  on top... flags never drop posts."
  Most importantly the pre-checks should never be the only modal check, the design intent is to keep
  the human in the loop — these checks save the human time by pre-sorting,
  not by replacing review.
- **Human** — the `pending_review → approved` decision in the admin UI.
  This is the actual gate for everything; the question is just how much
  *pre-sorting* happens before a human looks at it.

| Rule | Mechanical | LLM pre-check | Human (final gate) | Source |
|---|---|---|---|---|
| Posting frequency ≤ 1/hr, ≤ 24/day | ✅ `ratelimit.py` slot spacing — hard enforced, poster won't even attempt over-limit publishes (`poster_service.md` "pacing backstop") | — | — | `03_rate_and_volume.md` |
| Visibility (`public` vs `unlisted`) by cadence | ✅ derived from the same rate counters | — | reviewer can override per-post if context warrants | `01_bot_disclosure.md`, `03_rate_and_volume.md` |
| Bot-account flag, bio/owner disclosure | ✅ one-time account setup, not per-post | — | — | `01_bot_disclosure.md` |
| `#nobot` / explicit-summon / no bot-to-bot / dedupe (replies) | ✅ `replies.py` consent gates, pre-engine | — | reviewer sees the reply's context regardless | `01_bot_disclosure.md`, `real_overview.md` §2 |
| Per-post AI-disclosure footer present | ✅ fixed string injected by the post template — presence is a string-contains check, trivial to assert in tests | — | — | `02_attribution_and_ai_content.md` §1 |
| Source attribution link present (when post is derived from an article) | ✅ template requires `source_url` to be non-empty and rendered, when `opinion_keys`/`source_*` fields are populated | — | reviewer confirms the *right* source is credited (not just *a* link) | `02_attribution_and_ai_content.md` §1 |
| Length / character limits per instance | ✅ trivial string-length check against the instance's known max (500 default; some instances differ) | — | — | mechanical, not separately sourced in policy text — standard Mastodon API constraint |
| Output is link+headline only, no commentary ("link-spam" rules) | ⚠️ a *weak* mechanical proxy is possible (e.g. minimum non-URL word count) but doesn't really capture "commentary" | ✅ natural fit — "does this post add framing/opinion beyond the headline?" | reviewer is the real check; LLM flag just deprioritizes obvious link-drops | `02_attribution_and_ai_content.md` §4 |
| Claims/numbers/citations not present in source text (hallucination risk) | ⚠️ could mechanically diff named entities/numbers between draft and source as a crude flag, but high false-positive rate | ✅ primary check — "is every factual claim in this draft supported by the source article?" | reviewer makes the actual call, especially on borderline paraphrase | `02_attribution_and_ai_content.md` §3, unverified-link rule precedent |
| General misinformation / "no false or misleading info" | — | ✅ same pass as above, broadened to opinion/framing (e.g. does the post overstate scientific consensus?) | ✅ final gate — this is exactly what `pending_review` exists for | `02_attribution_and_ai_content.md` §3 |
| Topic relevance (on-topic for green energy advocacy, not drifting into unrelated political content) | — | ✅ cheap classifier-style check — "is this post about green energy / climate tech?" | reviewer confirms tone/framing fit for the specific instance's culture | new — not a literal policy line, but several instances (`climatejustice.social`, `hachyderm.io`'s topic list) imply community-fit matters |
| Harassment/hate-speech/slurs/personal attacks | — | ✅ MockModerator + LLM moderation layer, standard content-safety pass | ✅ final gate | near-universal across all 53 policies — not green-energy-specific but the baseline safety net |
| Per-instance pre-approval (bot invite, AI-content approval) | — | — | ✅ **one-time, pre-onboarding** human action, not a per-post check at all | `01_bot_disclosure.md` (`hachyderm.io`), `02_attribution_and_ai_content.md` §2 (`mastodon.au`) |
| Excluded instances (hard incompatibility) | ✅ — simplest possible check: identity's `instances` list in `activist.toml` never includes these domains | — | — | `05_exclude_or_flag.md` |

## Reading the table

The mechanical column is doing almost all the *enforcement* work — which
matches the existing architecture (`ratelimit.py`, `replies.py` consent
gates, templates). The LLM column is entirely **advisory flagging** that
feeds the human queue with better-sorted items; nothing in this corpus
justifies an LLM having authority to silently reject or silently rewrite.
The human column is short because it's not meant to be exhaustive — *every*
draft passes through `pending_review`, this column just marks where the
human is the **only** check (pre-onboarding approvals) versus one of
several.

## Net new work implied (beyond what's already speced)

1. A fixed AI-disclosure string in the post template + a test asserting
   its presence (`02_attribution_and_ai_content.md` §1) — small, Sonnet-
   sized, fits naturally into the existing template work.
2. An LLM pre-check pass for "claims supported by source" and "adds
   commentary beyond headline" — natural extension of the existing
   moderation layer (`real_overview.md` §2), same flag-not-reject pattern
   as the unverified-link rule. Opus-worth-a-look only insofar as it's
   another instance of the "don't let the LLM's own output be trusted
   uncritically" pattern that already burned the project once (gemma fake
   citation, per memory).
3. Excluding `nerdculture.de` (and flagging `mastodon.au`,
   `climatejustice.social`, `hachyderm.io` per `05_exclude_or_flag.md`) from
   any `activist.toml [identity].instances` list — a config/data change,
   not code.
