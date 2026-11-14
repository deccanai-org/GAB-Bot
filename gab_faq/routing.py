"""Who handles what: a fixed table from question category to contact person, and a keyword
classifier that picks the category.

Both are plain code and config.yaml (gab_faq.support.contacts). No AI is involved at any point, so an
AI answer can never invent, change or reassign a contact: the bot adds the contact line itself, after
the answer is written (see guard.py, which also removes any contact claims from AI text).

Categories and default contacts:
    task_qc            task queries and QC      Amtul / Adiba
    playground         playground issues        Rachana
    payment            payment queries          Amtul
    environment_reset  environment resets       Divya Sai
Throttle (task limit) increase requests and task issue reports go to task_qc unless configured otherwise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CATEGORIES = ("task_qc", "playground", "payment", "environment_reset")

# A mention in config.yaml must be one or more Discord user/role mentions: "<@123>", "<@&456>".
# Anything else (e.g. "@everyone", a name, a channel) is rejected so a typo can never mass-ping.
MENTION_TOKEN_RE = re.compile(r"<@(!?|&)(\d{5,25})>")
MENTIONS_ONLY_RE = re.compile(r"^\s*(<@(!?|&)\d{5,25}>\s*)*$")


@dataclass(frozen=True)
class Contact:
    name: str  # shown to freelancers, e.g. "Amtul / Adiba"
    label: str  # what they handle, e.g. "task queries and QC"
    mention: str = ""  # optional Discord mention(s), e.g. "<@123> <@456>"; empty = no ping

    def mention_ids(self) -> tuple[list[int], list[int]]:
        """(user IDs, role IDs) in `mention`, for an AllowedMentions that pings only them."""
        users, roles = [], []
        for kind, ident in MENTION_TOKEN_RE.findall(self.mention):
            (roles if kind == "&" else users).append(int(ident))
        return users, roles


DEFAULT_CONTACTS = {
    "task_qc": Contact("Amtul / Adiba", "task queries and QC"),
    "playground": Contact("Rachana", "playground issues"),
    "payment": Contact("Amtul", "payment queries"),
    "environment_reset": Contact("Divya Sai", "environment resets"),
}


@dataclass(frozen=True)
class SupportSettings:
    """gab_faq.support in config.yaml."""

    enabled: bool = True
    contacts: dict = field(default_factory=lambda: dict(DEFAULT_CONTACTS))
    throttle_route: str = "task_qc"  # who gets /throttle-request
    task_issue_route: str = "task_qc"  # who gets /task-issue
    default_route: str = "task_qc"  # questions that match no other category
    # Channel (name or ID) for /throttle-request and /task-issue cards. Empty = the
    # unanswered-questions channel. Make it staff-only.
    requests_channel: str = ""
    # Ping the contact in the public reply too (off: the reply names them; only the staff card pings).
    mention_in_reply: bool = False
    request_cooldown_seconds: int = 60  # per person, per command
    max_attachment_mb: int = 8

    def contact(self, category: str) -> Contact:
        return self.contacts.get(category) or self.contacts[self.default_route]


def parse_contacts(section: dict | None) -> dict:
    """config.yaml contacts -> {category: Contact}. Unknown categories or malformed mentions raise
    ValueError, so a broken routing table stops the FAQ part at startup instead of misrouting."""
    contacts = dict(DEFAULT_CONTACTS)
    for category, value in (section or {}).items():
        if category not in CATEGORIES:
            raise ValueError(
                f"gab_faq.support.contacts: unknown category {category!r}; use one of {CATEGORIES}"
            )
        value = value or {}
        name = str(value.get("name") or "").strip()
        mention = str(value.get("mention") or "").strip()
        if not name:
            raise ValueError(f"gab_faq.support.contacts.{category}: name is required")
        if mention and not MENTIONS_ONLY_RE.match(mention):
            raise ValueError(
                f"gab_faq.support.contacts.{category}.mention must be Discord mentions like "
                f"<@123> or <@&456>, got {mention!r}"
            )
        contacts[category] = Contact(name, DEFAULT_CONTACTS[category].label, mention)
    return contacts


def check_route(name: str, value: str) -> str:
    value = str(value or "task_qc").strip()
    if value not in CATEGORIES:
        raise ValueError(f"gab_faq.support.{name} must be one of {CATEGORIES}, got {value!r}")
    return value


# --- Classifier: ordered rules, first match wins ---

PLAYGROUND_RE = re.compile(r"\bplay\s?-?ground\b", re.IGNORECASE)
ENV_RESET_RE = re.compile(
    r"\b(reset|resets|resetting|environment|env)\b|\bsign[\s-]?in\b|\bsignin\b|\bgoogle\s+log[\s-]?in\b",
    re.IGNORECASE,
)
THROTTLE_RE = re.compile(
    r"\bthrottl\w*|\b(task|pickup|pick[\s-]?up|hourly)\s+(limit|cap|quota)s?\b|\btasks?\s+per\s+hour\b"
    r"|\b(increase|raise|bump|extend|lift)\b.{0,30}\b(limit|cap|quota)\b",
    re.IGNORECASE,
)
TASK_PROBLEM_RE = re.compile(
    r"\btask\b.{0,60}\b(stuck|error|bug|broken|crash\w*|fail\w*|not (loading|working|opening|submitting)"
    r"|won'?t (load|open|submit)|can'?t (open|submit|load|see)|issue|problem|missing)\b"
    r"|\btask\s*id\b",
    re.IGNORECASE,
)


def classify(question: str, support: SupportSettings) -> str:
    """The category (and so the contact) for a question the FAQ couldn't fully answer."""
    from .search import is_payment_question  # local import: search imports nothing from here

    q = question or ""
    if is_payment_question(q):
        return "payment"
    if PLAYGROUND_RE.search(q):
        return "playground"
    if ENV_RESET_RE.search(q):
        return "environment_reset"
    if THROTTLE_RE.search(q):
        return support.throttle_route
    return support.default_route


def hint_for(question: str) -> str:
    """Which request form to point the asker to, if any: "throttle", "task_issue" or ""."""
    if THROTTLE_RE.search(question or ""):
        return "throttle"
    if TASK_PROBLEM_RE.search(question or ""):
        return "task_issue"
    return ""


HINTS = {
    "throttle": " To ask for a higher task limit, use /throttle-request.",
    "task_issue": " To report a problem with a specific task, use /task-issue (task ID, what happened, screenshots).",
}


def reply_line(
    category: str, support: SupportSettings, hint: str = "", with_mention: bool = False
) -> str:
    """The sentence the bot adds under an answer it couldn't fully give."""
    contact = support.contact(category)
    who = contact.name + (f" ({contact.mention})" if with_mention and contact.mention else "")
    return f"For {contact.label}, please contact {who}." + HINTS.get(hint, "")


def contact_names(support: SupportSettings) -> list[str]:
    """Every configured contact name, split on "/" ("Amtul / Adiba" -> Amtul, Adiba)."""
    names = set()
    for contact in support.contacts.values():
        names.update(n.strip() for n in contact.name.split("/") if n.strip())
    return sorted(names, key=len, reverse=True)
