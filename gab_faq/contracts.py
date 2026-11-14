"""Transport- and provider-independent answer contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["annotator", "qc", "qm", "unknown"]
Outcome = Literal[
    "answered", "partial", "not_in_faq", "needs_human", "small_talk", "error", "limited"
]
ESCALATE_OUTCOMES = frozenset({"partial", "not_in_faq", "needs_human", "error"})


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

    @property
    def needs_escalation(self) -> bool:
        return self.outcome in ESCALATE_OUTCOMES


class AnswerEngine(Protocol):
    def answer(
        self, question: str, role: Role = "unknown", history: list[dict] | None = None
    ) -> Answer: ...
