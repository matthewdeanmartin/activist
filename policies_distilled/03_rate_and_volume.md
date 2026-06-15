# Rate & Volume Limits

The numeric rules in this file are exactly the kind of thing
`real_overview.md` §2 means by **"Rate limiting is ordinary code
(`ratelimit.py`) — never moderation, never prompt text."** They're listed
here so `ratelimit.py`'s per-instance configuration has a sourced default
to start from, not because they need new design.

## Explicit numeric limits found

| Instance | Limit | Visibility consequence |
|---|---|---|
| `infosec.exchange` | Automated posts: ≤ 1/hour **and** ≤ 24/day | At/under limit → `public` allowed. Over limit → must be `unlisted` (no cap on unlisted). |
| `mas.to`, `mastodon.scot` | < 1 post/hour | At/under → bot flag + respect `#nobot` suffices for visibility. Over → must post `unlisted`. |

Both pairs amount to the same threshold: **roughly hourly cadence is the
line between "can be public" and "must be unlisted."** A conservative
shared default of **≤ 1 post/hour and ≤ 24/day per identity, across all
instances**, satisfies every numeric rule found in the corpus and gives
headroom under the strictest ones.

## Non-numeric volume/frequency signals

These don't give a number but describe the same shape of constraint —
"don't flood," "don't be the dominant voice in the timeline":

- `kolektiva.social`: "Do not flood the timeline with posts. If you still
  want to do that — please set the posts as 'unlisted'."
- `mstdn.ca`: requires "Automated post deletion" with max age ~1 month
  (excluding pinned/DMs) — a *retention* limit, not a posting-rate limit.
  Only relevant if this identity ever posts to mstdn.ca; would need a
  separate scheduled cleanup task against the bot's own post history.
- General "no excessive hashtags / no excessive promotion" rules
  (`mastodon.bot`, others) — about content shape per post, not frequency;
  covered in `02_attribution_and_ai_content.md` §4.

## Reply-specific pacing

`real_overview.md` §2 already lists consent gates — explicit summon,
`#nobot`, no bot-to-bot, dedupe — as **pre-engine** checks in `replies.py`.
None of the policy text adds a new *numeric* reply-rate rule beyond the
general post-frequency cap above; replies count toward the same per-hour/
per-day budget as top-level posts for rate-limiting purposes.

## What goes in `ratelimit.py`

A single default config that's a strict subset of every rule above:

```toml
[ratelimit]
max_posts_per_hour = 1
max_posts_per_day = 24
# Below this cadence, "public" visibility is allowed (subject to per-instance
# overrides below). At or above, force "unlisted".
public_visibility_below_per_hour = 1

[ratelimit.per_instance]
# mstdn.ca requires scheduled deletion of posts older than ~1 month
# (excluding pinned/DMs) if this identity posts there — track separately,
# not a posting-rate concern.
```

This is deliberately the *strictest common denominator* — instances with no
stated limit are still fine under a 1/hour cap, and it avoids needing
per-instance tuning until/unless a specific instance turns out to need
looser limits (none currently do; several are stricter than "1/hour" only
in the sense of requiring `unlisted` sooner, which the
`public_visibility_below_per_hour` knob already handles).
