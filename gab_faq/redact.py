"""Text filters used wherever text crosses a trust boundary (no imports from the rest of gab_faq, so
anything can use them).

    redact_secrets      API keys, tokens, private keys, "password: ..." -> [redacted]   (everywhere)
    redact_personal     emails, phone/card-like numbers -> [email] / [number]   (text sent to an AI)
    neutralize_markup   removes the tags the bot uses to frame prompts, so user text can't fake them
    scrub_mentions      Discord user/role mentions and @everyone/@here -> harmless text
"""

from __future__ import annotations

import re

SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),  # Anthropic
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),  # OpenAI-style
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),  # Google / Gemini
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),  # Groq
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),  # Slack bot/user tokens
    re.compile(r"\bxapp-[A-Za-z0-9-]{10,}"),  # Slack app token
    re.compile(
        r"\b[MNO][A-Za-z\d_-]{23,27}\.[A-Za-z\d_-]{6}\.[A-Za-z\d_-]{27,}"
    ),  # Discord bot token
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)"),
    re.compile(
        r"\b(?:password|passwd|pwd|passcode|api[_ -]?key|secret|token)\s*(?:is|=|:)\s*\S+",
        re.IGNORECASE,
    ),
]

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
# 9+ digits possibly split by spaces/dashes: phone numbers, card or account numbers.
NUMBER_RE = re.compile(r"(?<![\w-])\+?\d(?:[ -]?\d){8,}(?![\w-])")

# Tags the bot's prompts use (brain.py). User text may not open or close them.
PROMPT_TAG_RE = re.compile(
    r"</?\s*(faq|faq_entries|faq_document|entry|asker_role|question|untrusted[\w-]*|system|instructions?)"
    r"\b[^>]*>",
    re.IGNORECASE,
)

MENTION_RE = re.compile(r"<@[!&]?\d+>")
MASS_MENTION_RE = re.compile(r"@(everyone|here)\b", re.IGNORECASE)


def contains_secret(text: str) -> bool:
    return any(p.search(text or "") for p in SECRET_PATTERNS)


def redact_secrets(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text or "")
    return text


def redact_personal(text: str) -> str:
    text = EMAIL_RE.sub("[email]", text or "")
    return NUMBER_RE.sub("[number]", text)


def neutralize_markup(text: str) -> str:
    return PROMPT_TAG_RE.sub(" ", text or "")


def scrub_mentions(text: str) -> str:
    text = MENTION_RE.sub("@someone", text or "")
    return MASS_MENTION_RE.sub(lambda m: "@​" + m.group(1), text)


def clean_untrusted(text: str) -> str:
    """User-written text on its way to an answering engine (and possibly an external AI)."""
    return redact_personal(redact_secrets(neutralize_markup(text))).strip()
