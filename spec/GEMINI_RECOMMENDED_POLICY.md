# Gemini Recommended LLM Bot Policy (The "Activist" Standard)

This policy is designed for LLM-driven social media accounts (specifically Mastodon bots) where the primary constraint is **content quality and engagement integrity**, rather than raw post volume. 

Traditional bot policies focus on preventing "cheap" automation (e.g., 1 post/second scripts). This policy assumes an LLM-based bot where each post has a non-trivial compute cost, making volume-based spam economically irrational but "AI slop" (low-value, generic content) a primary risk.

---

## 1. The Human-in-the-Loop (HiTL) Mandate

The LLM is a tool for the human operator, not an autonomous agent.

*   **Positive Approval:** No post shall be published to a public or unlisted timeline without a manual "Go" signal from a human operator.
*   **Accountability:** The human operator is the "legal person" responsible for the bot’s output. "The AI said it" is never a valid defense for policy violations.
*   **Override Capability:** The system must provide a "Kill Switch" that immediately halts all outgoing activity and clears the pending queue if the human operator detects unintended behavior.

## 2. Transparency & Disclosure

AI content should never be "passed off" as human.

*   **Visual Labeling:** Every post MUST contain a clear disclosure (e.g., `[AI-generated]` or a robot emoji 🤖).
*   **System Prompt Disclosure:** The bot's "Mission Statement" or "System Prompt" summary should be public (e.g., in the bio or a linked page) so users understand its bias and intent.
*   **Bot Flag:** The account must have the Mastodon `bot` flag enabled.

## 3. Interaction Ethics (Anti-Intrusion)

LLMs are powerful persuaders; they must not be used to ambush users.

*   **No Cold Mentions:** The bot must not mention a user who hasn't already interacted with it or opted in.
*   **No Keyword Camping:** The bot should not automatically reply to posts based on keyword matches alone. It may only reply if explicitly `@mentioned`.
*   **Thread Termination:** If a user expresses annoyance, hostility, or asks the bot to "stop," the bot must immediately cease all replies to that user and that thread. This must be an automated sentiment check followed by a hard-coded "Do Not Interact" list.

## 4. Content Quality (The "Anti-Slop" Bar)

Because LLM calls are expensive, each post must justify its existence.

*   **Source Requirement:** Every top-level post (not replies) must be a commentary on a specific, external URL or data point. De novo "thought leadership" or generic explainers are prohibited.
*   **No Circular Interaction:** The bot must not interact with other known bot accounts to boost visibility (no bot-to-bot "podding").
*   **Sentiment Alignment:** For replies, the LLM must analyze the thread's sentiment. If the thread is sensitive (grief, crisis, intense personal conflict), the bot should default to silence or route to human review.

## 5. Technical Guardrails & Realistic Moderation

Rules that can be enforced by the application logic.

*   **Rate Limits (Economic & Social):**
    *   Hard cap of **1 public post per hour**.
    *   Hard cap of **5 public posts per day**.
    *   (Replies are uncapped but limited by the `@mention` requirement).
*   **Hashtag Hygiene:** No more than 2 hashtags per post. Never use "Trending" hashtags unless the bot's human-approved content is directly relevant.
*   **Moderation Action - The "Self-Shadowban":** If the bot detects a high rate of blocks or mutes (via API feedback if available, or human observation), the system must automatically increase the "Human Approval" requirement to 100% for all interactions, including replies.

## 6. Salient & Enforceable Checks

Before any post is sent, the "Policy Layer" (a separate, smaller LLM or hard-coded check) must verify:

1.  **Is it a reply?** If yes, was the bot mentioned?
2.  **Is it a top-level post?** If yes, is there a source URL?
3.  **Is the bot flag set?**
4.  **Has a human clicked "Approve"?**
5.  **Is the recipient on the "Do Not Interact" list?**

If any check fails, the post is dropped and the operator is notified.

---

## Why this policy?

Most bot policies are written for $0-cost scripts. For a $0.05-per-post LLM bot, the danger isn't that you'll post 10,000 times an hour—you'd go broke. The danger is that you'll post 10 times an hour with content that is *almost* human but slightly "off," leading to a degraded social environment. This policy ensures the human remains the pilot and the AI remains the engine.
