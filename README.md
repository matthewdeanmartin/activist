# activist

This is a human-in-the-loop mastodon bot that will advocate for a position.

Design goals:

- Human approves all content
- Bot is transparent and always says upfront that it is a bot
- Contents is not denovo, it is always a comment on content found on the web

## Installation

```
pip install activist
```

### Usage

First, learn about the technology and disabuse yourself of your scifi preconceptions.

This bot is not for

- fake volume, e.g. 1000s of accounts all retweeting identical content, liking and retweeting the same posts
- fake content. The bot curates content from the web and doesn't generate "fake" content.
- an unattended bot that can be effortlessly defeated by asking it to ignore all previous instructions.

And that will be reflected in the features.

You could adapt it to be dull and malicious, I'm not your dad, but you will likely have an ineffective bot. I believe
that good content, truth and transparency is what influences people. Lies, trash and noise is to encourage people
to despair and stop reading the news. No one needed AI to flood social media with trash, humans with for-each loops
did that just fine.

## Mastodon Servers and bot policies

I manually checked these policies September 2024. All servers could vary in how they enforce their written policies.

There might be a chance?

- [mas.to](https://mas.to/about/more) - "All automated (bot) accounts must enable the bot flag in their account
  preferences, respect #nobot markers, and post as unlisted unless making less than one post per hour."
- [mastodon.bot](https://explore.mastodon.bot/rules#rules-for-bots) - Many restrictions that could cover all sorts of
  behavior, but doesn't specifically mention LLMs.
- [infosec.exchange](https://infosec.exchange/about) "Automated posting: - accounts that post >50% using automation must
  be labeled as a “bot” in the user profile to help provide a visual indicator to visitors - automated posts must be
  limited to one post per hour/24 per day with post visibility set to “public”. There is no limit on “unlisted” posts."
- [techhub.social](https://techhub.social/about) - "Bots must be marked as Bot in their profile"
- [hachyderm.io](https://community.hachyderm.io/docs/account-types/bot-accounts/) - The vibes of the policy tell me that
LLMs would be banned, but on an ad hoc basis.

Yes, if you are undiscoverable.
- [mstdn.party](https://mstdn.party/about) "Bots must be marked as bots in their profile preferences, and automated
  posts should be unlisted"
- [https://c.im/about](https://c.im/about) - "Bot accounts are allowed, but you need to set the toot visibility to
  unlisted and mark your accounts to Bot."

Unclear/blank/missing policy

- [mastodon.cloud](mastodon.cloud) - blank moderation policy.
- [mastodon.world](https://mastodon.world/about) - Doesn't mention bots at all.
- [universeodon.com](https://universeodon.com/about) - Bots not specifically mentioned.
- [mastodonapp.uk](https://mastodonapp.uk/about) - Bots not specifically mentioned.
- [social.vivaldi.net](https://social.vivaldi.net/about/more) - Bots not specifically mentioned.

No probably means no.

- [botsin.space](https://botsin.space/about/more) - "No bots that use ChatGPT, OpenAI or the other big GPT systems. If
  you're running your own LLM, that's ok. If you think you have a special use case to use a GPT system, feel free to ask
  if you can make a bot here, but chances are the answer will be no."
- [Mastodon.social](https://mastodon.social/about/more) - "Accounts may not solely post AI-generated content"
- [mstdn.social](https://mstdn.social/about) - "Profiles that only post AI-generated content will not be tolerated."
- [fosstodon.org](https://fosstodon.org/about) - "Unmonitored accounts that post automatically are not acceptable."
- [mastodon.online](https://mastodon.online/about) - "Accounts may not solely post AI-generated content."

TODO:

- good.news - chinese
- pawoo.net - japanese
- mstdn.jp - japanese
- pravda.me - russian
- mastodon.uno - italian

## Recommended policy compliance practices

Hachiderm's policy borderline "bot can only broadcast". So Riker Googling would probably pass, but an LLM bot like
activist probably wouldn't.

Transparency

- Mark account as bot in profile.
- Optionally add #bot tag to each post, or other indication that it is AI generated.
- If hosted on Hachiderm, add #hachybots to all posts.

Activity and server load

- Post at most 1 post per hour. (Most common limit)
- 5 scheduled posts per day (Hachiderm's policy)
- Posts more often than 1 per hour should be unlisted.
- Don't reply to a thread forever. (Hachiderm calls this a "doom spiral")

Degree of automation

- No "uncurated news bots posting from third-party news sources"
- Don't post without a human approving what the LLM has generated.

Interactions

- Don't follow accounts marked with #nobot
- "Bots cannot respond to hashtags, keywords, etc. without being tagged - e.g. bots that respond to user posts based on
  keywords and similar." Hachiderm's policy.

Moderation and compliance with other, non-bot specific rules

- Bot should fetch server policy interaction accounts and hosting server and have a 2nd bot check if LLM content is compliant.
- A bot should publish a profile page somewhere with its code of conduct, especially the verifiable parts (e.g. a 
report of posting frequency, etc.)

## Features on roadmap

- CLI interface
- RSS/search events
- Mastodon Drafts
- Approval workflow

## Similar libraries and applications

- [mastodon.py](http://mastodonpy.readthedocs.io/en/latest/)