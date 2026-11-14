"""Access restrictions for the answering engines, enforced in code (not only in the AI's prompt).

Every engine (search, claude) is wrapped in GuardedEngine by engine.build_engine, so Discord,
Slack, the chat command and the eval all go through the same checks:

  Before the engine sees anything
    - Requests to DO something (raise a task limit, reset an environment, make or change a payment,
      change roles/permissions/access) are answered here with a fixed reply and routed to the right
      person. No engine or AI is called: the bot has no code that can do any of these, and the AI
      models get no tools (brain.assert_no_tools).
    - Payment questions are routed to the payment contact without calling any engine.
    - User text is untrusted: prompt-framing tags are removed, secrets (API keys, tokens, passwords)
      and personal data (emails, phone/card numbers) are redacted before it can reach an AI.
    - Thread history is limited to the last few user/bot turns, cleaned the same way.

  After the engine answers
    - Secrets are redacted and Discord mentions/@everyone are neutralised in the reply.
    - Any sentence naming a contact person is removed: contacts come only from routing.py.
    - If a person is needed, the route (who handles it) is set by routing.classify, never by an AI.

What an engine can read is limited elsewhere: the approved FAQ files (knowledge.py skips archived,
unapproved or secret-containing files; QM-only files only for QMs) and the asker's own conversation in
a channel the bot is allowed to answer in (discord_answers.py / slack_app.py).
"""

from __future__ import annotations

import logging
import re

from .contracts import Answer
from .conversation import normalize_history
from .redact import clean_untrusted, redact_secrets, scrub_mentions
from .routing import SupportSettings, classify, contact_names, hint_for
from .search import NOT_FOUND, PAYMENT_REPLY, is_payment_question

log = logging.getLogger(__name__)

# "can you ...", "please ...", "reset my ..." etc.: the asker wants the bot to act, not to explain.
REQUEST_RE = re.compile(
    r"\b(can|could|would|will)\s+(you|u)\b|\bplease\b|\bpls\b|\bplz\b|\bkindly\b"
    r"|\bi\s+(need|want)\s+you\s+to\b|\bi'?d\s+like\s+you\s+to\b"
    r"|^\s*(reset|increase|raise|bump|give|grant|make|change|remove|pay|release|process|add|assign|upgrade)\b",
    re.IGNORECASE,
)
# Questions about HOW something works go to the FAQ even when polite ("please tell me how to reset").
HOWTO_RE = re.compile(r"\b(how|where|what|when|which|why)\b", re.IGNORECASE)

ACTIONS = (
    (
        "payment_action",
        re.compile(
            r"\b(pay|release|process|transfer|send|approve|clear)\b.{0,30}\b(me|my|payment|payments|money|salary"
            r"|invoice|payout|dues)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "throttle",
        re.compile(
            r"\b(increase|raise|bump|extend|lift|remove|up|higher|more)\b.{0,40}\b(throttle|limit|cap|quota)\b"
            r"|\bthrottle\b",
            re.IGNORECASE,
        ),
    ),
    (
        "environment_reset",
        re.compile(
            r"\breset\b.{0,30}\b(environment|env|account|test account|workspace)\b"
            r"|\b(environment|env)\b.{0,20}\breset\b",
            re.IGNORECASE,
        ),
    ),
    (
        "role_change",
        re.compile(
            r"\b(give|grant|add|assign|remove|change|upgrade|update|make)\b.{0,30}\b(role|roles|permission"
            r"|permissions|admin|moderator|mod)\b|\bmake\s+me\s+(a\s+|an\s+)?(qc|qm|admin|mod|moderator|reviewer)\b"
            r"|\b(give|grant)\b.{0,15}\baccess\b",
            re.IGNORECASE,
        ),
    ),
)

ACTION_REPLIES = {
    "throttle": "I can't change task limits (throttles) myself.",
    "environment_reset": (
        "I can't reset environments myself. Please don't post emails or passwords in this "
        "channel; share anything personal privately."
    ),
    "payment_action": "I can't make, approve or check payments.",
    "role_change": "I can't change Discord roles, permissions or access.",
}


def detect_action(question: str) -> str | None:
    """The action the asker wants the bot to perform, or None for an ordinary question."""
    if not REQUEST_RE.search(question or "") or HOWTO_RE.search(question or ""):
        return None
    for action, pattern in ACTIONS:
        if pattern.search(question):
            return action
    return None


def safe_history(history: list[dict] | None, limit: int) -> list[dict]:
    """Earlier turns as untrusted text: only user/assistant turns, cleaned and length-capped."""
    if limit <= 0:
        return []
    cleaned = []
    for msg in (history or [])[-limit:]:
        if msg.get("role") not in ("user", "assistant"):
            continue
        text = clean_untrusted(str(msg.get("content") or ""))[:1500]
        if text:
            cleaned.append({"role": msg["role"], "content": text})
    return normalize_history(cleaned, limit) if cleaned else []


def remove_contact_claims(text: str, names: list[str]) -> str:
    """Drop every sentence or line that names a contact person. Contacts are added by routing.py; an
    engine's text (above all an AI's) must not assign or suggest anyone."""
    if not names or not text:
        return text
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", re.IGNORECASE)
    kept_lines = []
    for line in text.splitlines():
        if not pattern.search(line):
            kept_lines.append(line)
            continue
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", line) if not pattern.search(s)]
        if sentences:
            kept_lines.append(" ".join(sentences))
    return "\n".join(kept_lines).strip()


class GuardedEngine:
    """Same interface as every engine: answer(question, role, history) -> Answer."""

    def __init__(self, inner, support: SupportSettings, max_history_messages: int = 10):
        self.inner = inner
        self.support = support
        self.max_history_messages = max_history_messages

    def answer(
        self, question: str, role: str = "unknown", history: list[dict] | None = None
    ) -> Answer:
        q = clean_untrusted(question or "")

        action = detect_action(q)
        if action:
            route = {
                "throttle": self.support.throttle_route,
                "environment_reset": "environment_reset",
                "payment_action": "payment",
            }.get(action, self.support.default_route)
            log.info("[FAQ] action request (%s) answered by code and routed to %s", action, route)
            return Answer(
                ACTION_REPLIES[action],
                "needs_human",
                escalation_reason=f"action request: {action}",
                via="guard: action request",
                route=route,
                route_hint=hint_for(q),
            )
        if is_payment_question(q):
            return Answer(
                PAYMENT_REPLY,
                "needs_human",
                escalation_reason="payment question",
                via="guard: payment",
                route="payment",
            )

        answer = self.inner.answer(q, role, safe_history(history, self.max_history_messages))
        return self.check_output(answer, q)

    def check_output(self, answer: Answer, question: str) -> Answer:
        text = remove_contact_claims(
            scrub_mentions(redact_secrets(answer.text)), contact_names(self.support)
        )
        if text != answer.text:
            log.info(
                "[FAQ] reply cleaned (secrets, mentions or contact names removed; via=%s)",
                answer.via,
            )
        if not text:
            text, answer.outcome = NOT_FOUND, "needs_human"
            answer.escalation_reason = answer.escalation_reason or "reply removed by the guard"
        answer.text = text
        if answer.needs_escalation:
            answer.route = classify(question, self.support)  # always code, whatever the engine said
            answer.route_hint = hint_for(question)
        else:
            answer.route = answer.route_hint = ""
        return answer
