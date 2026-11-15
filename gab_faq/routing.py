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

Staff IDs are stored as strings (config.yaml: user_ids: ["1533459501393379488"]) and the Discord
mention text is built here, in code. Nothing a model writes can become a mention: a model may only
SUGGEST one of the fixed category names below, and resolve_route() validates that suggestion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CATEGORIES = ("task_qc", "playground", "payment", "environment_reset")
# Request subtypes a model may suggest. "throttle" is a distinct request (a task-limit increase), but it
# is routed to SupportSettings.throttle_route (task_qc by default) and points the asker to the form.
REQUEST_SUBTYPES = ("throttle",)
SUGGESTIBLE = CATEGORIES + REQUEST_SUBTYPES
# Specific categories outrank the task_qc catch-all, in this order.
SPECIFIC_PRECEDENCE = ("payment", "playground", "environment_reset")

# A mention in config.yaml must be one or more Discord user/role mentions: "<@123>", "<@&456>".
# Anything else (e.g. "@everyone", a name, a channel) is rejected so a typo can never mass-ping.
MENTION_TOKEN_RE = re.compile(r"<@(!?|&)(\d{5,25})>")
MENTIONS_ONLY_RE = re.compile(r"^\s*(<@(!?|&)\d{5,25}>\s*)*$")
ID_RE = re.compile(r"^\d{5,25}$")


@dataclass(frozen=True)
class Contact:
    name: str  # shown to freelancers, e.g. "Amtul / Adiba"
    label: str  # what they handle, e.g. "task queries and QC"
    user_ids: tuple[str, ...] = ()  # Discord user IDs, as strings; empty = no ping
    role_ids: tuple[str, ...] = ()  # Discord role IDs, as strings

    @property
    def mention(self) -> str:
        """The Discord mention text, built from the stored IDs (never from config or model text)."""
        users, roles = self.mention_ids()
        return " ".join([f"<@{ident}>" for ident in users] + [f"<@&{ident}>" for ident in roles])

    def mention_ids(self) -> tuple[list[int], list[int]]:
        """(user IDs, role IDs), each once, for an AllowedMentions that pings only them."""
        return (
            [int(i) for i in dict.fromkeys(self.user_ids)],
            [int(i) for i in dict.fromkeys(self.role_ids)],
        )


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


def _id_list(category: str, key: str, value) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"gab_faq.support.contacts.{category}.{key} must be a list of ID strings")
    ids = []
    for item in value:
        # Quoted strings only: a bare YAML integer is accepted by Python but silently loses precision
        # in tools that read the file as JSON numbers (Discord IDs exceed 2^53).
        if not isinstance(item, str) or not ID_RE.match(item.strip()):
            raise ValueError(
                f"gab_faq.support.contacts.{category}.{key} entries must be quoted digit strings "
                f'like "1533459501393379488", got {item!r}'
            )
        ids.append(item.strip())
    return tuple(dict.fromkeys(ids))


def parse_contacts(section: dict | None) -> dict:
    """config.yaml contacts -> {category: Contact}. Unknown categories or malformed IDs raise
    ValueError, so a broken routing table stops the FAQ part at startup instead of misrouting.

    Preferred form: {name: "Amtul", user_ids: ["1533459501393379488"]}. The older
    {mention: "<@123> <@&456>"} form is still read, but only its numeric IDs are kept."""
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
        users = _id_list(category, "user_ids", value.get("user_ids"))
        roles = _id_list(category, "role_ids", value.get("role_ids"))
        if mention:
            if users or roles:
                raise ValueError(
                    f"gab_faq.support.contacts.{category}: use user_ids/role_ids or mention, not both"
                )
            if not MENTIONS_ONLY_RE.match(mention):
                raise ValueError(
                    f"gab_faq.support.contacts.{category}.mention must be Discord mentions like "
                    f"<@123> or <@&456>, got {mention!r}"
                )
            tokens = MENTION_TOKEN_RE.findall(mention)
            users = tuple(dict.fromkeys(i for kind, i in tokens if kind != "&"))
            roles = tuple(dict.fromkeys(i for kind, i in tokens if kind == "&"))
        contacts[category] = Contact(name, DEFAULT_CONTACTS[category].label, users, roles)
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
    from .policy import is_payment_matter  # local import: policy imports nothing from here

    q = question or ""
    # The asker's own pay, not any mention of payment (a persona's "payment reminder", seen live).
    if is_payment_matter(q):
        return "payment"
    if PLAYGROUND_RE.search(q):
        return "playground"
    if ENV_RESET_RE.search(q):
        return "environment_reset"
    if THROTTLE_RE.search(q):
        return support.throttle_route
    return support.default_route


def resolve_route(question: str, support: SupportSettings, suggestion: str = "") -> tuple[str, str]:
    """(category, request hint) for a question a person must handle. Decided by code.

    The keyword classifier picks a specific category (payment, playground, environment reset) over
    the task_qc catch-all. A model's suggestion is only consulted when the classifier found nothing
    specific, and only if it is one of the fixed names in SUGGESTIBLE; anything else is ignored. A
    throttle suggestion stays a distinct request: it routes to throttle_route with the form hint."""
    category = classify(question, support)
    hint = hint_for(question)
    suggestion = (suggestion or "").strip().lower() if isinstance(suggestion, str) else ""
    # Code already recognised a specific case (a category, a throttle request, or a problem with a
    # specific task, e.g. "task 4471 won't submit", seen live): the model cannot override it.
    if category in SPECIFIC_PRECEDENCE or hint or suggestion not in SUGGESTIBLE:
        return category, hint
    if suggestion == "throttle":
        return support.throttle_route, "throttle"
    if suggestion in SPECIFIC_PRECEDENCE:
        return suggestion, hint
    return category, hint


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
