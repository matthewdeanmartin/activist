"""Deterministic rule-based persona engine.

No randomness, no network: same inputs produce byte-identical outputs.
It relies on the fixture-only ``<activist:hint>`` element to know whether
an article challenges or supports an opinion; the real LLM engine works
from article text instead and ignores hints.
"""

from __future__ import annotations

import hashlib

from ..models import DraftPost, NewsItem, Opinion, OpinionChange, Persona, Reaction, SaidEntry
from .base import CONVICTION_THRESHOLD


def _post_id(item_id: str, opinion_key: str) -> str:
    return hashlib.sha256(f"{item_id}:{opinion_key}".encode("utf-8")).hexdigest()[:12]


class MockBot:
    name = "mockbot"

    def react(
        self,
        item: NewsItem,
        persona: Persona,
        opinions: dict[str, Opinion],
        knowledge: str,
        recent_said: list[SaidEntry],
        created: str,
    ) -> Reaction:
        challenged = item.hints.get("challenges", "")
        supported = item.hints.get("supports", "")

        if challenged:
            opinion = opinions.get(challenged)
            if opinion is None:
                return Reaction(
                    post=None,
                    diary_note=f"Read '{item.title}' — hint references unknown opinion '{challenged}'.",
                )
            if opinion.strength < CONVICTION_THRESHOLD:
                return self._change_of_mind(item, persona, opinion, created)
            return self._pushback(item, persona, opinion, created)

        if supported:
            opinion = opinions.get(supported)
            if opinion is None:
                return Reaction(
                    post=None,
                    diary_note=f"Read '{item.title}' — hint references unknown opinion '{supported}'.",
                )
            return self._reinforce(item, persona, opinion, recent_said, created)

        # Relevant beat, but no opinion engaged: abstain. Resisting the urge
        # to summarize is the feature.
        return Reaction(
            post=None,
            diary_note=f"Read '{item.title}' — on my beat, but I had nothing to add.",
        )

    # --- behaviors ----------------------------------------------------------

    def _change_of_mind(
        self, item: NewsItem, persona: Persona, opinion: Opinion, created: str
    ) -> Reaction:
        claim = item.hints.get("claim", item.title)
        new_stance = item.hints.get("new_stance") or f"{item.title} has changed my outlook on {opinion.topic}"
        old_subject = opinion.subject or opinion.stance
        change = OpinionChange(
            key=opinion.key,
            old_stance=opinion.stance,
            new_stance=new_stance,
            trigger_item=item.id,
            reason=claim,
        )
        body = (
            f"{old_subject} used to be my top pick for {opinion.topic}, "
            f"but {claim} — and that changed my mind. "
            f"New take: {new_stance}. {item.url}"
        )
        post = self._post(item, persona, body, [opinion.key], created, change)
        return Reaction(
            post=post,
            opinion_changes=[change],
            diary_note=f"Read '{item.title}' — changed my mind on {opinion.key}.",
        )

    def _pushback(
        self, item: NewsItem, persona: Persona, opinion: Opinion, created: str
    ) -> Reaction:
        claim = item.hints.get("claim", item.title)
        body = (
            f"Big claim in {item.feed}: {claim}. "
            f"I'm not convinced — I still think {opinion.stance} ({opinion.basis}). "
            f"Show me replication. {item.url}"
        )
        post = self._post(item, persona, body, [opinion.key], created, None)
        return Reaction(
            post=post,
            pushbacks=[{"key": opinion.key, "reason": claim}],
            diary_note=(
                f"Read '{item.title}' — held firm on {opinion.key} "
                f"(strength {opinion.strength})."
            ),
        )

    def _reinforce(
        self,
        item: NewsItem,
        persona: Persona,
        opinion: Opinion,
        recent_said: list[SaidEntry],
        created: str,
    ) -> Reaction:
        claim = item.hints.get("claim", item.title)
        prior = next(
            (s for s in reversed(recent_said) if opinion.key in s.opinion_keys), None
        )
        if prior is not None:
            body = (
                f'Last time I said "{prior.summary}" — today\'s news backs that up. '
                f"{claim}. {item.url}"
            )
        else:
            body = f"This is why I keep saying {opinion.stance}: {claim}. {item.url}"
        post = self._post(item, persona, body, [opinion.key], created, None)
        return Reaction(
            post=post,
            reinforcements=[opinion.key],
            diary_note=f"Read '{item.title}' — reinforces {opinion.key}.",
        )

    # --- helpers ------------------------------------------------------------

    def _post(
        self,
        item: NewsItem,
        persona: Persona,
        body: str,
        opinion_keys: list[str],
        created: str,
        change: OpinionChange | None,
    ) -> DraftPost:
        text = f"{body}\n\n{persona.disclosure}"
        return DraftPost(
            id=_post_id(item.id, opinion_keys[0]),
            created=created,
            status="draft",
            text=text,
            char_count=len(text),
            source_url=item.url,
            source_title=item.title,
            opinion_keys=opinion_keys,
            engine=self.name,
            opinion_change=change,
        )
