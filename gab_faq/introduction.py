"""Code-owned bot identity and a project introduction from the current FAQ."""

from __future__ import annotations

import re

from .contracts import Answer
from .grounding import render_sources
from .search import split_entries

IDENTITY = (
    "I'm Gigi, the GAB FAQ assistant. I help with project guidelines, model selection, "
    "task steps and QC questions. If a question needs a person, I can direct you to the team."
)
IDENTITY_QUESTIONS = {
    "what are you",
    "who are you",
    "who is gigi",
    "what is gigi",
    "what is this bot",
    "what can you do",
    "what do you do",
    "who r u",
    "what r u",
}
PROJECT_QUESTIONS = {
    "what is gab",
    "whats gab",
    "what s gab",
    "what is project gab",
    "what is the gab project",
    "tell me about gab",
    "explain gab",
    "what is gab i need to understand the project",
}


def introduction(question, knowledge=None, role="unknown"):
    normalized = " ".join(re.findall(r"[a-z0-9]+", question.lower()))
    if normalized in IDENTITY_QUESTIONS:
        return Answer(IDENTITY, "small_talk", via="local: bot identity")
    if normalized not in PROJECT_QUESTIONS:
        return None
    overview = "GAB is the project covered by this FAQ. "
    if knowledge is not None:
        knowledge.reload_if_changed()
        entries = [e for d in knowledge.documents_for(role) for e in split_entries(d)]
        current = next((e for e in entries if e.id == "U1" and e.status == "current"), None)
        if current is not None:
            answer = render_sources(
                entries, [current.id], "answered", via="local: project overview"
            )
            answer.text = overview + "Here is the current task scope:\n\n" + answer.text
            return answer
    return Answer(
        overview + "I can help you find its current task instructions, model-selection guidance "
        "and QC rules. Which part would you like explained?",
        "clarification",
        via="local: project overview",
    )
