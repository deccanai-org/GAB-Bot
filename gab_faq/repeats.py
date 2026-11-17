"""Spot the same person asking the same question again and again.

The bot answers the first asks normally. Once one person has asked the same question
`max_asks` times inside `window_minutes`, the bot stops answering it: the ask that reaches the
limit is flagged to the team (one staff card), and later repeats in the window get a short
"already flagged" reply without another card or model call.

"The same question" means the same words after lower-casing and dropping punctuation, or nearly
the same set of words (one word added, removed or changed in a longer question). Counts live in
memory: one bot process serves the server (see docs/operations.md), and a restart only resets the
counts, which errs on the side of answering.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

WORD_RE = re.compile(r"[a-z0-9]+")
SIMILAR = 0.8  # word-set overlap (Jaccard) that counts as the same question
MIN_WORDS_FOR_SIMILAR = 4  # shorter questions must match exactly

FLAGGED_REPLY = (
    "You've asked this {count} times in the last {minutes} minutes. I've flagged it so a team "
    "member can pick it up. Please check the earlier answer in the meantime."
)
ALREADY_FLAGGED_REPLY = (
    "You've already asked this {count} times in the last {minutes} minutes, and it has been "
    "flagged for the team. A team member will follow up."
)


@dataclass(frozen=True)
class RepeatSettings:
    """gab_faq.repeat_limit in config.yaml."""

    max_asks: int = 3  # the ask that reaches this count is flagged instead of answered
    window_minutes: int = 60

    @classmethod
    def parse(cls, section: dict | None) -> RepeatSettings:
        section = section or {}
        d = cls()
        max_asks = int(section.get("max_asks", d.max_asks))
        window = int(section.get("window_minutes", d.window_minutes))
        if max_asks < 0 or window < 1:
            raise ValueError(
                "gab_faq.repeat_limit: max_asks must be 0 (off) or more, window_minutes 1 or more"
            )
        return cls(max_asks=max_asks, window_minutes=window)


def words(question: str) -> tuple[str, ...]:
    return tuple(WORD_RE.findall((question or "").lower()))


def same_question(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    sa, sb = set(a), set(b)
    if min(len(sa), len(sb)) < MIN_WORDS_FOR_SIMILAR:
        return sa == sb
    return len(sa & sb) / len(sa | sb) >= SIMILAR


@dataclass
class RepeatTracker:
    settings: RepeatSettings = field(default_factory=RepeatSettings)
    clock: callable = time.monotonic
    _asks: dict = field(default_factory=dict)  # user -> [(time, words)]

    def record(self, user: str, question: str) -> int:
        """Count this ask and return how many times (this one included) the person has asked the
        same question inside the window. 0 when the limit is off or the question is empty."""
        if self.settings.max_asks <= 0:
            return 0
        key = words(question)
        if not key:
            return 0
        now = self.clock()
        cutoff = now - self.settings.window_minutes * 60
        recent = [(t, w) for t, w in self._asks.get(user, []) if t > cutoff]
        count = 1 + sum(1 for _, w in recent if same_question(key, w))
        recent.append((now, key))
        self._asks[user] = recent[-50:]  # bounded per person
        if len(self._asks) > 5000:  # bounded overall: drop people with nothing recent
            self._asks = {u: a for u, a in self._asks.items() if a and a[-1][0] > cutoff}
        return count

    def reply(self, count: int) -> tuple[str, bool] | None:
        """(reply text, flag to the team?) once `count` reaches the limit, else None."""
        limit = self.settings.max_asks
        if limit <= 0 or count < limit:
            return None
        minutes = self.settings.window_minutes
        if count == limit:
            return FLAGGED_REPLY.format(count=count, minutes=minutes), True
        return ALREADY_FLAGGED_REPLY.format(count=count, minutes=minutes), False
