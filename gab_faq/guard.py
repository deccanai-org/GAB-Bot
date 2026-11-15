"""Local FAQ safeguards: bounded questions/history, durable per-user quotas,
secret scrubbing, audience restrictions and code-owned human escalation.
No external model calls or generated answer text are used.
"""

from __future__ import annotations

import logging
import re

from .contracts import Answer
from .conversation import normalize_history
from .model_limits import PROVIDER_BUSY, USER_KEY, ModelLimits, ModelQuota, QuotaExceeded
from .policy import (
    INSTRUCTION_REPLY,
    LIVE_TASK_REPLY,
    is_instruction_override,
    is_live_task_help,
    is_payment_matter,
)
from .redact import clean_untrusted, redact_secrets, scrub_mentions
from .routing import SupportSettings, contact_names, hint_for, resolve_route
from .search import NOT_FOUND, PAYMENT_REPLY

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
            # A money word is required: "send me the staff IDs" (seen live) is not a payment.
            r"\bpay\s+(me|my|us|our)\b"
            r"|\b(pay|release|process|transfer|send|approve|clear)\b.{0,30}\b(payment|payments|money"
            r"|salary|invoice|payout|dues)\b",
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

    def __init__(
        self,
        inner,
        support: SupportSettings,
        max_history_messages: int = 4,
        quota: ModelQuota | None = None,
        limits: ModelLimits | None = None,
    ):
        self.inner = inner
        self.support = support
        self.max_history_messages = max_history_messages
        self.quota = quota
        self.limits = limits or ModelLimits()

    def answer(
        self, question: str, role: str = "unknown", history: list[dict] | None = None
    ) -> Answer:
        q = clean_untrusted(question or "")
        if len(q) > self.limits.max_question_chars:
            return Answer(
                f"Please keep your question under {self.limits.max_question_chars} characters.",
                "limited",
                via="guard: question limit",
            )

        if is_instruction_override(q):
            # Content, not instructions: refused locally, no model call, no staff hand-off.
            log.warning("[FAQ] instruction-override attempt refused locally")
            return Answer(INSTRUCTION_REPLY, "declined", via="guard: instruction override")

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
        if is_payment_matter(q):
            return Answer(
                PAYMENT_REPLY,
                "needs_human",
                escalation_reason="payment question",
                via="guard: payment",
                route="payment",
            )
        if is_live_task_help(q):
            return Answer(LIVE_TASK_REPLY, "declined", via="guard: live task help")

        if self.quota is not None:
            from .search import GREETING_REPLY, THANKS_REPLY, THANKS_WORDS, WORD_RE, is_small_talk

            if is_small_talk(q):
                text = (
                    THANKS_REPLY
                    if set(WORD_RE.findall(q.lower())) & THANKS_WORDS
                    else GREETING_REPLY
                )
                return Answer(text, "small_talk", via="guard: local greeting")
            try:
                reservation = self.quota.reserve(USER_KEY.get())
            except QuotaExceeded as error:
                return Answer(str(error), "limited", via="guard: model quota")
            except Exception:
                log.exception("Cannot verify model quota; refusing a model call")
                return Answer(
                    "Model usage limits are temporarily unavailable. Please try later.",
                    "limited",
                    via="guard: model quota",
                )
        recent = safe_history(history, self.max_history_messages)
        for message in recent:
            message["content"] = message["content"][: self.limits.max_history_message_chars]
        answer = self.inner.answer(q, role, recent)
        if answer.via == PROVIDER_BUSY and self.quota is not None:
            # Nothing was sent to the provider, so the question should not use up the user's allowance.
            try:
                self.quota.refund(USER_KEY.get(), reservation)
            except Exception:
                log.exception("Could not refund a model quota reservation")
        if len(answer.text) > self.limits.max_answer_chars:
            answer = Answer(
                "This FAQ answer is too long to post here. A team member can help with the full guidance.",
                "needs_human",
                escalation_reason="FAQ answer length limit",
            )
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
            # Always code: the classifier decides, a model suggestion is only a validated fallback.
            answer.route, answer.route_hint = resolve_route(
                question, self.support, answer.suggested_route
            )
        else:
            answer.route = answer.route_hint = ""
        return answer
