"""Shared helpers for turning an Answer into a chat message, and for logging every question."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .contracts import Answer
from .routing import SupportSettings, reply_line
from .storage import JsonLines

# What the asker can do next, by outcome: carry on with the bot's answer, or ask again in their own
# words. Outcomes not listed (greetings, limits, refusals) get no such line.
CARRY_ON = {
    "answered": "If this doesn't fully answer your question, ask again with a bit more detail.",
    "general": "If this doesn't fully answer your question, ask again with a bit more detail.",
    "partial": (
        "If this covers your question, you can carry on with it. If not, rephrase your question "
        "with more detail and ask me again; a team member will also follow up."
    ),
    "not_in_faq": "You can also rephrase your question with more detail and ask me again.",
    "needs_human": "You can also rephrase your question with more detail and ask me again.",
    "error": "You can also try asking again in a minute.",
}
# Every reply except a greeting or a limit message ends by pointing to the announcements.
NO_ANNOUNCEMENT_LINE = frozenset({"small_talk", "limited"})
DEFAULT_ANNOUNCEMENTS = "the announcements channel"
# Answer.via for a reply produced by the repeat limit (repeats.py): no "ask again" line under it.
REPEAT_VIA = "repeat limit"


def footer_lines(answer: Answer, announcements: str = DEFAULT_ANNOUNCEMENTS) -> str:
    """The closing lines under a reply: what to do next, and the announcements reminder."""
    lines = []
    # Rephrasing can't change a reply decided by a rule: payment questions, action requests
    # ("reset my environment") and the repeat limit. Those get no "ask again" line.
    decided_by_rule = (
        answer.via == REPEAT_VIA or answer.via.startswith("guard:") or answer.route == "payment"
    )
    if answer.outcome in CARRY_ON and not decided_by_rule:
        lines.append(CARRY_ON[answer.outcome])
    if answer.outcome not in NO_ANNOUNCEMENT_LINE:
        lines.append(
            f"📢 Please keep checking {announcements or DEFAULT_ANNOUNCEMENTS} for the latest "
            "updates."
        )
    return "\n".join(lines)


def format_reply(
    answer: Answer,
    escalation_mention: str = "",
    environment: str = "production",
    support: SupportSettings | None = None,
    mentions_allowed: bool = False,
    announcements: str = DEFAULT_ANNOUNCEMENTS,
) -> str:
    """The chat message for an answer. When a person is needed, the contact line chosen by
    routing.py (code, not the AI) is added; it points to the project admin, never to a named
    person. Contact mentions are added only if `mentions_allowed` (Discord, with
    mention_contacts_in_replies on). Every reply then ends with footer_lines()."""
    text = answer.text
    if answer.needs_escalation and support is not None and answer.route:
        text += "\n\n" + reply_line(
            answer.route,
            support,
            answer.route_hint,
            with_mention=mentions_allowed and support.mention_in_reply,
        )
    if answer.needs_escalation and escalation_mention:
        text += f"\n\n{escalation_mention} could you help with this one?"
    footer = footer_lines(answer, announcements)
    if footer:
        text += "\n\n" + footer
    if environment == "staging":
        text = "[TEST BOT] " + text
    return text


def split_message(text: str, limit: int) -> list[str]:
    """Split a long message into chunks under `limit` characters (Discord allows 2000), preferring
    to break at line ends."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:  # a single very long line
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return [c.rstrip("\n") for c in chunks if c.strip()]


class QuestionLog:
    """Appends every question and the bot's answer to output/faq_questions.jsonl, and the ones a
    human must handle to output/faq_unanswered.jsonl (one JSON object per line).

    No database: in Kubernetes these files last until the bot restarts (unless the output folder is
    a persistent volume). Nothing important is lost on a restart: the questions and answers are
    still in Discord/Slack history, and on Discord every unanswered question is also posted to the
    unanswered-questions channel."""

    QUESTIONS_FILE = "faq_questions.jsonl"
    UNANSWERED_FILE = "faq_unanswered.jsonl"
    REQUESTS_FILE = "support_requests.jsonl"  # /throttle-request and /task-issue

    def __init__(self, log_dir: Path, *, environment: str = "staging"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.environment = environment
        self._writer = JsonLines(self.log_dir)

    def record(
        self, *, platform: str, channel: str, user: str, role: str, question: str, answer: Answer
    ) -> dict:
        entry = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "environment": self.environment,
            "platform": platform,
            "channel": channel,
            "user": user,
            "role": role,
            "question": question,
            "answer": answer.text,
            "outcome": answer.outcome,
            "escalated": answer.needs_escalation,
            "sources": answer.sources,
            "escalation_reason": answer.escalation_reason,
            "request_id": answer.request_id,
            "route": answer.route,
        }
        entry = self._writer.append(self.QUESTIONS_FILE, entry)
        if answer.needs_escalation:
            self._writer.append(self.UNANSWERED_FILE, entry)
        return entry

    def record_request(
        self,
        *,
        kind: str,
        channel: str,
        user: str,
        role: str,
        route: str,
        fields: dict,
        attachments: list[str],
    ) -> dict:
        """A /throttle-request or /task-issue. Attachments are logged by file name only."""
        entry = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "environment": self.environment,
            "kind": kind,
            "channel": channel,
            "user": user,
            "role": role,
            "route": route,
            "fields": fields,
            "attachments": attachments,
        }
        return self._writer.append(self.REQUESTS_FILE, entry)
