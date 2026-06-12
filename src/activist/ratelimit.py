"""Rate limiting is ordinary code, not a moderator judgment.

The run pipeline asks for the effective posts-per-hour limit (the app's own
pacing rule and the strictest target-instance policy) and schedules draft
timestamps that satisfy it. The moderator never sees rate rules.
"""

from __future__ import annotations

import datetime as dt
import re

# Drafts are scheduled from this hour of the run date.
START_HOUR = 9

_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_HOURLY_RE = re.compile(r"\b(\d+|one|two|three|four|five|six)\s+posts?\s+per\s+hour", re.IGNORECASE)


def parse_hourly_limit(policy_text: str) -> int | None:
    """Extract 'N post(s) per hour' from policy prose, if present.

    Matches digits and number words, e.g. infosec.exchange's "limited to one
    post per hour" and mas.to's "less than one post per hour".
    """
    match = _HOURLY_RE.search(policy_text)
    if not match:
        return None
    token = match.group(1).lower()
    return int(token) if token.isdigit() else _WORD_NUMBERS[token]


def effective_hourly_limit(app_limit: int, instance_policies: dict[str, str]) -> int:
    """The strictest applicable limit: the app's own cap and every target instance's."""
    limits = [app_limit]
    for policy_text in instance_policies.values():
        parsed = parse_hourly_limit(policy_text)
        if parsed is not None:
            limits.append(parsed)
    return max(1, min(limits))


def slot_time(date: str, index: int, per_hour: int) -> str:
    """Scheduled ISO timestamp for the index-th draft of a run."""
    interval_minutes = max(1, 60 // max(1, per_hour))
    start = dt.datetime.fromisoformat(f"{date}T{START_HOUR:02d}:00:00")
    return (start + dt.timedelta(minutes=index * interval_minutes)).isoformat()


def assign_slots(count: int, date: str, per_hour: int) -> list[str]:
    return [slot_time(date, i, per_hour) for i in range(count)]
