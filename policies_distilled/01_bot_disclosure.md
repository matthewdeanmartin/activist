# Bot / Automation Disclosure

What each instance requires for an account that is openly run by software.
This is **account setup**, not pipeline logic — a one-time checklist per
`MASTODON_ID_*` identity before it posts anywhere, per `real_overview.md`
§4 (`activist.toml` → `[identity]`).

## Universal baseline (do this for every identity, every instance)

1. Enable the **"This is a bot account"** profile flag. Several instances
   make this mandatory and a few actively police accounts that "display
   signs of being a bot" without it (mindly.social). Enabling it is strictly
   safer everywhere — no instance penalizes a *disclosed* bot for disclosing.
2. Put the bot owner / contact info in the **bio**. Required explicitly by
   `theblower.au`, recommended generally ("Bot policy. Bots are welcome, but
   please include an owner/contact link and a description of what the bot
   does" — `mastodon.bot`). This is also just good practice for an
   "activist" account that wants to be trusted.
3. Default new automated posts to **`unlisted`** visibility unless an
   instance's frequency carve-out applies (see below and
   `03_rate_and_volume.md`). Unlisted is the safe default across nearly
   every instance that mentions bots at all.

## Per-instance specifics

| Instance                  | Requirement                                                                                                                                                                                            | Notes                                                                                                                                                                                                                                                               |
|---------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `infosec.exchange`        | If >50% of posts are automated, must set "bot" label. Automated posts ≤ 1/hour, ≤ 24/day **may** be `public`; otherwise `unlisted`.                                                                    | Frequency-gated visibility — feeds `03_rate_and_volume.md`.                                                                                                                                                                                                         |
| `mas.to`, `mastodon.scot` | Bot flag required. Must respect `#nobot` markers. `unlisted` unless <1 post/hour.                                                                                                                      | `#nobot` consent check belongs in `replies.py` per `real_overview.md` §2 ("Consent gates in code").                                                                                                                                                                 |
| `mstdn.plus`              | Bot flag required; automated posts should be `unlisted`.                                                                                                                                               |                                                                                                                                                                                                                                                                     |
| `mstdn.ca`                | "This is a bot account" checkbox required. Posts must be `unlisted`. Must enable "Automated post deletion" (max age ~1 month, excluding pinned/DMs).                                                   | The auto-deletion requirement is unusual — would need a scheduled cleanup job against this identity's own post history if this instance is used. Flag as extra setup cost.                                                                                          |
| `mindly.social`           | Bot flag required or account gets limited/suspended. Also: accounts that *only* post links without commentary get limited — relevant since this bot transforms feed content.                           | The "no link-only posting" rule overlaps with the attribution/transform requirement in `02_attribution_and_ai_content.md` — the bot's *transform* step (LLM commentary, not raw link-drop) is what keeps this compliant.                                            |
| `theblower.au`            | Bot accounts permitted only if: visibility ∈ {unlisted, followers-only, direct}; bot checkbox set; owner identified in bio; **bot must not @-mention accounts that haven't interacted with it first**. | The no-unsolicited-mention rule is stricter than most — already covered by "no bot-to-bot, explicit summon only" in `replies.py` per `real_overview.md` §2, but double-check it also blocks unsolicited top-level @-mentions of human accounts, not just bots.      |
| `fosstodon.org`           | "Do not use automated tools to post without also monitoring and/or interacting from your account."                                                                                                     | Interpreted as: a human must be in the loop watching the account — satisfied by the `pending_review`/admin-UI design generally, but this instance phrases it as ongoing monitoring, not just pre-publish approval. Worth a periodic human check-in if posting here. |
| `c.im`                    | Bot accounts welcome, must be "clearly marked as a bot," must not generate "excessive traffic."                                                                                                        | Traffic cap is vague — fold into the general rate limit.                                                                                                                                                                                                            |
| `mastodon.bot`            | Whole instance is *for* bots. Requires following "Rules for Bots" (linked, not in our cached text) and the general server rules (no ads/spam, no adult content, no impersonation).                     | Friendliest instance for this bot's purpose if it ever needs a home base, but it's bot-only — humans there expect bot traffic, doesn't help with reach into the green-energy advocacy audience.                                                                     |
| `hachyderm.io`            | Bot accounts "allowed with restrictions," **invite/contact required first** ("email admin@hachyderm.io before creating").                                                                              | This is a **pre-registration gate**, not a posting rule — can't be satisfied by pipeline code at all. Either skip this instance or get the email approval done manually before onboarding the identity.                                                             |

## Hard "no" — exclude these instances for an automated identity

| Instance         | Rule                                                                                                | Verdict                                                                                                          |
|------------------|-----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| `nerdculture.de` | "No automated posts by bots, except with admin permission. **No AI (LLM) Agents (no exceptions).**" | Exclude outright. This is a content-and-account ban on exactly what this bot is, stated as having no exceptions. |

See `05_exclude_or_flag.md` for the full exclusion list including
non-bot-specific reasons (off-topic communities, AI-art bans, etc.).
