# Policy Distillation — Overview

**Status:** distillation, 2026-06-13. Source: `policies/*.txt` (53 instance
reports from `policy_fetcher`). Scope: a single-user bot that transforms
LLM-generated/curated content about green energy advocacy, queues it for
**human sign-off**, then posts/replies on Mastodon.

The raw policy reports are long and mostly about things that don't apply to
this bot (NSFW media, age requirements, EU jurisdiction boilerplate, donation
links). This distillation pulls out the ~10% that's actually load-bearing for
an automated posting account and sorts it by **who/what enforces it**.

## How to read these files

| File                               | Content                                                                  |
|------------------------------------|--------------------------------------------------------------------------|
| `01_bot_disclosure.md`             | Rules about labeling the account as a bot/automated/AI, per instance     |
| `02_attribution_and_ai_content.md` | Rules about attributing sourced content and disclosing AI-generated text |
| `03_rate_and_volume.md`            | Posting frequency/visibility limits — mechanically enforceable           |
| `04_checks_by_enforcement.md`      | The cross-cutting table: mechanical check / LLM check / human check      |
| `05_exclude_or_flag.md`            | Instances that are a poor fit (bot-hostile, AI-hostile, or off-topic)    |

## The shape of the answer

Almost every instance's rules fall into one of four buckets for this bot:

1. **Doesn't apply.** NSFW/adult content, gore, age (13+/18+) requirements,
   EU/Australia/Canada legal jurisdiction notices, donation/Patreon
   boilerplate, "About Mastodon" explainer text. This is the bulk of every
   report. Green-energy advocacy text is not going to trip these.

2. **Applies to the *account*, checked once at setup, not per-post.**
   "This is a bot account" checkbox, bio must name an owner/contact,
   bot-account eligibility (some instances require admin permission first).
   → one-time admin task per identity, not pipeline logic.

3. **Applies to every post, mechanically checkable.** Posting frequency caps
   (e.g. "max 1/hour, 24/day"), visibility defaults for automated posts
   (must be `unlisted` unless under a frequency threshold), no-bot-to-bot /
   `#nobot` / consent-to-reply rules. → `ratelimit.py` and `replies.py`,
   already noted in `spec/real_overview.md` as "ordinary code."

4. **Applies to content quality, needs judgment.** "Don't post AI content
   without disclosing it," "attribute content created by others," "no
   spreading misinformation," "no spam/excessive promotion," "stay on
   topic." → split between an LLM pre-check (cheap, catches the obvious
   cases) and the human reviewer (catches the rest, and is the actual gate
   per `real_overview.md`'s `pending_review` → `approved` flow).

The rest of this distillation is mostly buckets 2–4, organized so the
pipeline pieces map onto specific rule text instead of vague "be a good
bot" vibes.
