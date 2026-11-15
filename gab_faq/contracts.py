"""Transport- and provider-independent answer contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["annotator", "qc", "qm", "unknown"]
Outcome = Literal[
    "answered",  # approved FAQ text, or an explanation grounded in quoted FAQ entries
    "general",  # general guidance (definitions, writing tips), labelled as not an official rule
    "partial",
    "not_in_faq",
    "needs_human",
    "small_talk",
    "error",
    "limited",
    "clarification",
    "unrelated",
    "declined",  # e.g. choosing a rating or writing a justification for a live task
]
ESCALATE_OUTCOMES = frozenset({"partial", "not_in_faq", "needs_human", "error"})
# Replies that can be followed by "Didn't help? Ask a person".
HELPFUL_OUTCOMES = frozenset({"answered", "general"})


@dataclass
class Answer:
    text: str
    outcome: Outcome
    sources: list[str] = field(default_factory=list)
    escalation_reason: str = ""
    request_id: str | None = None
    via: str = ""
    route: str = ""
    route_hint: str = ""
    # A category a model proposed for a hand-off. Only a hint: routing.resolve_route validates it
    # against the fixed category names and the code classifier decides.
    suggested_route: str = ""

    @property
    def needs_escalation(self) -> bool:
        return self.outcome in ESCALATE_OUTCOMES


class AnswerEngine(Protocol):
    def answer(
        self, question: str, role: Role = "unknown", history: list[dict] | None = None
    ) -> Answer: ...
