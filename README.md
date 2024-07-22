# activist

This is a human-in-the-loop mastodon bot that will advocate for a position.

Design goals:
- Human approves all content
- Bot is transparent and always says upfront that it is a bot
- Contents is not denovo, it is always a comment on content found on the web
- 

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

## Features on roadmap

- CLI interface
- RSS/search events
- Mastodon Drafts
- Approval workflow

## Similar libraries and applications

- [mastodon.py](http://mastodonpy.readthedocs.io/en/latest/)