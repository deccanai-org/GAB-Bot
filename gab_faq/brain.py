"""Claude source selection from approved FAQ documents; source text is rendered by code."""

from __future__ import annotations

import json
import logging

import anthropic

from .contracts import Answer, Role
from .conversation import ToolUseForbidden as ToolUseForbidden
from .conversation import assert_no_tools, normalize_history
from .grounding import SOURCE_SELECTION_RULES, render_sources
from .knowledge import KnowledgeBase

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"

RULES = SOURCE_SELECTION_RULES

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {
            "type": "string",
            "enum": ["answered", "not_in_faq", "needs_human", "small_talk"],
        },
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["outcome", "sources"],
    "additionalProperties": False,
}

ERROR_MESSAGE = (
    "Sorry, I couldn't process that right now. I've flagged it so a team member can help you."
)


class Brain:
    def __init__(
        self,
        knowledge: KnowledgeBase,
        client: anthropic.Anthropic | None = None,
        model: str = "claude-opus-5-5",
        effort: str = "low",
        max_history_messages: int = 10,
    ):
        self.knowledge = knowledge
        self.client = client or anthropic.Anthropic(timeout=15.0, max_retries=1)
        self.model = model
        self.effort = effort
        self.max_history_messages = max_history_messages

    def build_request(self, question: str, role: Role, history: list[dict] | None) -> dict:
        try:
            self.knowledge.reload_if_changed()
        except (
            Exception
        ):  # a half-saved FAQ file must not take the bot down; keep the last good copy
            log.exception("FAQ reload failed; using the previously loaded FAQ")
        system_text = f"{RULES}\n<faq>\n{self.knowledge.render(role)}\n</faq>"
        messages = normalize_history(history, self.max_history_messages)
        messages.append(
            {
                "role": "user",
                "content": f"<asker_role>{role}</asker_role>\n<question>\n{question.strip()}\n</question>",
            }
        )
        request = {
            "model": self.model,
            "max_tokens": 1024,
            # The rules + FAQ are identical on every request, so they are cached: cheaper and faster.
            "system": [
                {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": messages,
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": ANSWER_SCHEMA},
            },
            # If the main model declines a request, the API retries it on a fallback model.
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }
        return assert_no_tools(request)  # the model only writes text: it gets no tools to act with

    def answer(
        self, question: str, role: Role = "unknown", history: list[dict] | None = None
    ) -> Answer:
        request = self.build_request(question, role, history)
        try:
            response = self.client.beta.messages.create(**request)
        except anthropic.RateLimitError:
            log.warning("Claude API rate limit hit")
            return Answer(ERROR_MESSAGE, "error", escalation_reason="Claude API rate limited")
        except anthropic.AuthenticationError:
            log.error("Claude API key is missing or invalid")
            return Answer(ERROR_MESSAGE, "error", escalation_reason="Claude API key invalid")
        except anthropic.APIStatusError as e:
            log.error("Claude API error %s: %s", e.status_code, e.message)
            return Answer(
                ERROR_MESSAGE, "error", escalation_reason=f"Claude API error {e.status_code}"
            )
        except anthropic.APIConnectionError:
            log.error("Could not reach the Claude API")
            return Answer(ERROR_MESSAGE, "error", escalation_reason="Claude API unreachable")

        request_id = getattr(response, "_request_id", None)
        if response.stop_reason == "refusal":
            return Answer(
                "I can't help with that one here. I've flagged it for a team member.",
                "needs_human",
                escalation_reason="model declined the question",
                request_id=request_id,
            )
        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        try:
            data = json.loads(text)
            from .search import GREETING_REPLY, NOT_FOUND, is_small_talk, split_entries

            outcome = data["outcome"]
            if outcome == "small_talk" and is_small_talk(question):
                return Answer(GREETING_REPLY, "small_talk", request_id=request_id, via="claude")
            if outcome == "not_in_faq":
                return Answer(
                    NOT_FOUND,
                    "not_in_faq",
                    escalation_reason="No FAQ source selected",
                    request_id=request_id,
                    via="claude",
                )
            if outcome == "needs_human" and not data.get("sources"):
                return Answer(
                    "A team member can help with this question.",
                    "needs_human",
                    escalation_reason="Human assistance requested",
                    request_id=request_id,
                    via="claude",
                )
            entries = [
                entry
                for doc in self.knowledge.documents_for(role)
                for entry in split_entries(doc)
                if entry.audience != "qm" or role == "qm"
            ]
            return render_sources(
                entries,
                data.get("sources"),
                outcome,
                via="claude",
                request_id=request_id,
                escalation_reason="Human assistance requested" if outcome == "needs_human" else "",
            )
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError, ValueError):
            log.error(
                "Unreadable model output (stop_reason=%s, request_id=%s)",
                response.stop_reason,
                request_id,
            )
            return Answer(
                ERROR_MESSAGE,
                "error",
                escalation_reason="unreadable model output",
                request_id=request_id,
            )
