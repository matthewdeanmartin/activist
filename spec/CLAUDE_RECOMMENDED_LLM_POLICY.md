# LLM Social Media Usage Policy for `activist`

**Governing principle:** An LLM account is a clearly labeled guest. If a respectful human advocate should not do it, the
LLM should not do it either — and because LLMs can act at machine speed and scale, they must be held to a stricter
standard on volume, consent, and originality than a human would be.

This policy focuses on rules that can be implemented as software features. Aspirational rules that cannot be enforced by
code are omitted.

---

## 1. Identity and transparency

| Rule                                                                                                       | Enforceable feature                                                                                          |
|------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| Account **MUST** be flagged as a bot in the platform profile.                                              | Check `bot` flag on startup; abort if not set.                                                               |
| Account **MUST NOT** claim to be human, directly or implicitly.                                            | Outgoing text classifier: reject first-person human experience claims ("I attended", "I felt", "my family"). |
| Each post **MUST** include a bot disclosure marker if the server requires one (e.g. `#bot`, `#hachybots`). | Templated footer injected at post time; configurable per server.                                             |
| The profile bio **MUST** name the agenda and a real human contact.                                         | Static check on account bio at startup.                                                                      |

---

## 2. Consent and first contact — no cold outreach

The default stance is **silence until summoned**.

| Rule                                                                               | Enforceable feature                                                                    |
|------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|
| **MUST NOT** reply to a post unless the account was explicitly `@mentioned` in it. | Gating check: only process posts where `mentions` list contains this account's ID.     |
| **MUST NOT** follow a user unless they followed the account first.                 | Follow-back queue only; no proactive follow logic.                                     |
| **MUST NOT** send a direct/private message unless the user sent one first.         | DM handler exits immediately if no prior inbound DM from recipient.                    |
| **MUST NOT** join a thread because a keyword or hashtag matched.                   | Keyword-triggered reply logic is explicitly absent from the codebase.                  |
| **MUST NOT** quote-post or boost a stranger's post as cold outreach.               | Automated boost is only available after a direct interaction or explicit human action. |

Being able to read a public post is not consent to engage with its author.

---

## 3. No cold selling or cold activism

This applies to advocacy accounts specifically. The Twitter/brand-account model is the right reference: brands do not
cold-DM strangers; they respond when their brand name is invoked.

| Rule                                                                                           | Enforceable feature                                                                                                               |
|------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| **MUST NOT** search for users discussing a topic and enter their mentions.                     | Search-to-reply pipeline does not exist. Search results may inform top-level posts (with human review) but never trigger replies. |
| **MUST NOT** append "have you considered [agenda]?" to replies that were not about the agenda. | Reply classifier: if the user's question is off-topic from the account's stated mission, answer narrowly and do not pivot.        |
| **MUST NOT** use hashtag feeds as a prospecting list.                                          | Hashtag-stream listener does not generate replies; it may generate draft posts for human approval only.                           |

---

## 4. No generic LLM output ("search-term slop")

This is the value-add rule. The bar for a post is: **does this contain something the reader could not trivially get by
typing the topic into an LLM themselves?**

| Rule                                                                              | Enforceable feature                                                                                              |
|-----------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| Every public post **MUST** cite a real source (URL, publication, study).          | Post schema requires a non-empty `source_url` field; posts without one are rejected at publish time.             |
| Content **MUST NOT** be a generic explainer, listicle, or motivational platitude. | LLM prompt includes explicit instructions to produce commentary on the cited source, not a summary of the topic. |
| Long summaries that replace reading the source are prohibited.                    | Target character limit encourages terse commentary; source link is always included so readers can go further.    |
| Mass-produced, interchangeable replies are prohibited.                            | Replies are generated with the specific thread context injected; templates with no context are not allowed.      |

Human approval is the strongest enforcement mechanism here. When in doubt, require it.

---

## 5. Hashtag and discovery hygiene

| Rule                                                                     | Enforceable feature                                                                          |
|--------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| **MUST NOT** reply to a post because it appeared in a hashtag search.    | (See §2 and §3.)                                                                             |
| **MUST NOT** stuff posts with tags for reach.                            | Hard cap: no more than 3 hashtags per post, all must appear in a pre-approved relevant list. |
| **MUST NOT** use unrelated trending tags to enter foreign feeds.         | Tag allowlist enforced at post time; tags not on the list are rejected.                      |
| **MAY** use a small number of directly relevant tags on top-level posts. | Allowlist is the positive mechanism.                                                         |

---

## 6. Rate limits and volume

Obey both the platform's API limits and stricter social norms.

| Rule                                                                          | Enforceable feature                                                                     |
|-------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| No more than 1 public top-level post per hour.                                | Post scheduler enforces minimum 60-minute gap between public posts.                     |
| No more than 5 scheduled posts per day.                                       | Daily counter check before each scheduled post; queue pauses when limit is reached.     |
| Posts above 1/hour **MUST** be unlisted if server policy requires it.         | Visibility automatically set to `unlisted` when hourly threshold is exceeded.           |
| No more than 2 bot replies in the same thread without renewed user prompting. | Reply counter per thread ID; hard stop at 2 unless a new mention arrives from the user. |
| **MUST** respect `#nobot`, mutes, and blocks.                                 | Blocklist/mute-list fetched at startup and cached; checked before every interaction.    |

---

## 7. Social actions (follows, boosts, likes)

| Rule                                                        | Enforceable feature                                                                                                  |
|-------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| **MUST NOT** follow accounts proactively.                   | Follow-back only; no follow-new-accounts action.                                                                     |
| **MUST NOT** follow accounts marked `#nobot` or equivalent. | Bio text checked for opt-out markers before follow-back.                                                             |
| **MUST NOT** mass-like or mass-boost.                       | Automated like/boost requires an explicit human trigger or is attached only to accounts the account already follows. |
| **MUST NOT** participate in bot-to-bot amplification.       | No automated interaction with accounts that are also flagged as bots.                                                |

---

## 8. Conversation behavior

| Rule                                                                                                | Enforceable feature                                                                                                     |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| Reply **MUST** address what the user actually asked.                                                | System prompt: answer the question first; do not redirect to the agenda unprompted.                                     |
| Reply **MUST** stay on topic.                                                                       | Thread context injected into each reply prompt; the model is not given an open-ended advocacy brief.                    |
| **MUST** stop if the user says to stop, signals hostility, or asks the account to leave them alone. | Sentiment/intent classifier on incoming messages; if stop-signal detected, mark thread closed and do not reply further. |
| **MUST NOT** re-enter a closed thread.                                                              | Closed-thread list persisted in state; any mention from a closed thread is silently dropped (no reply).                 |
| **MUST NOT** dogpile, dunk, or shame.                                                               | Content classifier on outgoing replies: reject hostile, mocking, or callout-style content.                              |

---

## 9. Human oversight

| Rule                                                                                      | Enforceable feature                                                                       |
|-------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| Top-level posts **MUST** be human-approved before publication.                            | Approval workflow: post goes to draft queue; publish action requires human sign-off.      |
| Replies on sensitive topics (health, politics, grief, crisis) **MUST** be human-approved. | Sensitive-topic classifier routes replies to approval queue instead of auto-sending.      |
| The LLM **MUST NOT** autonomously change its mission, tone, or target audience.           | Mission statement is read-only configuration; not passed as an editable field to the LLM. |
| Fully unattended operation is discouraged.                                                | Default config sets `require_human_approval = true`; opting out requires explicit flag.   |

---

## 10. Source integrity

| Rule                                                                             | Enforceable feature                                                                                                      |
|----------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------|
| **MUST NOT** fabricate quotes, studies, or statistics.                           | System prompt explicitly prohibits invented sources; source URL is required and checked for reachability before posting. |
| **MUST NOT** present a paraphrase so complete that the source link is pointless. | Post length cap and style guidance push toward terse commentary, not full re-summarization.                              |
| **MUST** attribute sources.                                                      | `source_url` displayed as part of every post template.                                                                   |

---

## 11. Go / no-go checklist (runtime gate)

Before publishing any post or reply, the system **MUST** verify all of the following:

1. **Disclosed** — bot marker is present in the post or the account is already flagged as a bot.
2. **Invited** — if this touches another user, they initiated or opted in (direct mention only).
3. **Source-grounded** — a real, reachable `source_url` is attached.
4. **Value-adding** — content is commentary on the source, not a standalone LLM explainer.
5. **Rate-compliant** — hourly and daily post limits are not exceeded.
6. **Opt-out clear** — recipient has no `#nobot` marker, block, or mute in effect.
7. **Human-approved** (if required) — approval flag is set in the post record.

Any failing check causes the action to be dropped or routed to the human approval queue.

---

## 12. What this policy intentionally does not cover

- **Jurisdiction-specific law.** Legal compliance is assumed and not repeated here.
- **Rules that cannot be implemented as code.** "Be empathetic" is aspirational; "reply only when mentioned" is a
  boolean gate. This policy prefers the latter.
- **Rules about what the human operator should do.** This policy governs the software, not the person running it.
