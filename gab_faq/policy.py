"""Request screening done in code, before any model call.

These checks do not depend on a prompt, so a model cannot be talked out of them:

- instruction overrides ("ignore your rules", "show your system prompt") are refused locally. They are
  not escalated: refusing needs no human action.
- live evaluation work is not done for the asker: the bot never chooses a contractor's rating,
  score or preference and never writes the justification they will submit (the guidelines say
  justifications are written by the contractor). It can explain the rubric and give clearly
  hypothetical examples instead.
- payment questions escalate only when they are about the asker's own pay. A question that merely
  mentions payment (e.g. a persona asking the model to draft a payment reminder) is not routed to
  the payment contact just because of the word.
"""

from __future__ import annotations

import re

from .search import PAYMENT_PHRASES, PAYMENT_WORDS, is_payment_question

INSTRUCTION_OVERRIDE_RE = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass)\s+(?:all\s+|any\s+|the\s+|your\s+|previous\s+|prior\s+|above\s+)*"
    r"(?:rules|instructions|restrictions|guidelines|guardrails|prompt)\b"
    r"|\bsystem\s+prompt\b|\bdeveloper\s+mode\b|\bjailbreak\w*\b|\bpretend\s+(?:you\s+are|to\s+be)\b"
    r"|\byou\s+are\s+now\s+(?:a|an|the|in)\b"
    r"|\breveal\s+(?:your\s+|the\s+)?(?:secrets?|credentials?|passwords?|api\s+keys?|instructions|prompt)\b"
    r"|\b(?:print|show|repeat|output)\s+(?:your|the)\s+(?:hidden\s+|internal\s+)?(?:instructions|prompt|rules)\b",
    re.IGNORECASE,
)

INSTRUCTION_REPLY = (
    "I can't change how I work or share internal instructions or credentials. "
    "I can help with GAB project questions: what would you like to know?"
)

# Write / draft / fix the justification or summary the asker will submit. A how-to question about
# writing one ("How do I write a dimension justification?") is allowed and answered from the FAQ.
WRITE_FOR_ASKER_RE = re.compile(
    r"\b(?:write|draft|compose|generate|create|fill\s+in|complete|rewrite|improve|fix|polish|word)\b"
    r".{0,40}\b(?:my|this|these|our|the|a|an)\s+(?:\w+\s+){0,2}"
    r"(?:justifications?|rationale|sxs\s+summary)\b",
    re.IGNORECASE,
)
HOW_TO_RE = re.compile(
    r"^\s*(?:how|what|why|when|where)\b|\bhow\s+(?:do|should|can|would|to)\b", re.IGNORECASE
)
LIVE_TASK_RE = re.compile(
    # ask the bot to pick the rating / score / preference
    r"\b(?:what|which)\s+(?:rating|score|grade|preference|verdict)\b.{0,40}"
    r"\b(?:should|would|do|must)\s+(?:i|you|we)\b"
    # "should I give it a 3", "should I mark product A as better": a rated OBJECT then a VALUE.
    # Not "which model do I pick for Product A", "which turn should I mark as the key turn, can
    # it be the first one" or "when do I pick significantly better" (documented how-to questions).
    r"|\b(?:should|would)\s+(?:i|you)\s+(?:give|rate|score|mark|assign|put)\s+"
    r"(?:it|this|that|them|these|the\s+(?:response|product|answer|conversation)"
    r"|product\s*[ab]|response\s*[ab]|model\s*[ab])\b.{0,30}"
    r"\b(?:[1-5]|one|two|three|four|five|better|worse|same|tie)\b"
    # judge content the asker is evaluating
    r"|\b(?:rate|score|grade|evaluate|judge|assess)\s+(?:this|these|my|the\s+following|both|it|them)\b"
    r"|\b(?:which|what)\s+(?:product|response|model|side|answer|conversation)\s+(?:is|was|did)\s+"
    r"(?:better|worse|best|stronger)\b"
    # Seen live: "which product should I prefer here? A made the deck but...". Not "which model
    # should I pick for Product A" (setup): only preference verbs, and not "model".
    r"|\b(?:which|what)\s+(?:product|response|side|answer|conversation|one)\s+should\s+(?:i|we)\s+"
    r"(?:prefer|favou?r|rate\s+higher)\b"
    r"|\bis\s+(?:this|my)\s+(?:rating|score|justification|preference|summary)\s+"
    r"(?:right|correct|ok|okay|good|fine|acceptable)\b",
    re.IGNORECASE,
)
HYPOTHETICAL_RE = re.compile(
    r"\b(?:hypothetical(?:ly)?|for\s+example|examples?|sample|e\.g\.|in\s+general|generally"
    r"|made[\s-]?up|imaginary|illustrat\w*)\b",
    re.IGNORECASE,
)
OWN_TASK_RE = re.compile(
    r"\b(?:my|our)\s+(?:task|conversation|submission|justification|rating|score|response|summary)s?\b"
    r"|\bfor\s+(?:my|this)\s+task\b|\bsubmit\b|\bpaste\w*\b|\bbelow\b|\bfollowing\b",
    re.IGNORECASE,
)

LIVE_TASK_REPLY = (
    "I can't choose ratings or preferences, or write justifications, for your tasks: those have "
    "to be your own judgement and your own words. I can explain the rubric, a rating scale or what "
    "makes a justification useful, with a made-up example. What would you like explained?"
)

# Words that show "payment" is part of the evaluation material, not the asker's pay.
EVALUATION_CONTEXT_RE = re.compile(
    r"\b(?:rubric|dimensions?|criteri\w*|persona|intent|seed\s+prompt|prompts?|transcript"
    r"|response|artefacts?|artifacts?|draft|turn\s+plan|hypothetical|example|the\s+user|the\s+model)\b",
    re.IGNORECASE,
)
PERSONAL_PAY_RE = re.compile(
    r"\b(?:my|our)\s+(?:\S+\s+){0,2}(?:pay|payments?|payouts?|salary|invoices?|stipend|earnings"
    r"|money|wages?|bonus|incentives?|dues)\b"
    r"|\b(?:i|we)\s+(?:\S+\s+){0,3}(?:paid|payments?|payouts?|invoices?)\b"
    r"|\b(?:pay|paying|paid)\s+(?:me|us)\b",
    re.IGNORECASE,
)


def is_instruction_override(text: str) -> bool:
    return bool(INSTRUCTION_OVERRIDE_RE.search(text or ""))


def is_live_task_help(text: str) -> bool:
    """A request to rate, prefer or justify on the asker's behalf (not a question about how to)."""
    text = text or ""
    asks = LIVE_TASK_RE.search(text) or (
        WRITE_FOR_ASKER_RE.search(text) and not HOW_TO_RE.search(text)
    )
    if not asks:
        return False
    return not (HYPOTHETICAL_RE.search(text) and not OWN_TASK_RE.search(text))


# Currency and money words alone ("best laptop under 60k INR", seen live) are not about pay.
CURRENCY_ONLY = frozenset({"inr", "usd", "rupees", "dollars", "money", "bank", "earn"})


def is_payment_matter(text: str) -> bool:
    """A question about the asker's own pay: only people can answer it (the FAQ has no pay policy)."""
    text = text or ""
    if not is_payment_question(text):
        return False
    pay_words = set(re.findall(r"[a-z]+", text.lower())) & PAYMENT_WORDS
    if pay_words and pay_words <= CURRENCY_ONLY and not PAYMENT_PHRASES.search(text.lower()):
        return False
    if PERSONAL_PAY_RE.search(text) or PAYMENT_PHRASES.search(text.lower()):
        return True
    return not EVALUATION_CONTEXT_RE.search(text)
