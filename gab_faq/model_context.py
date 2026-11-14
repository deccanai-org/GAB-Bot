"""Select complete approved FAQ entries within the provider request byte budget."""

from __future__ import annotations

import json
import logging

from .conversation import normalize_history
from .redact import clean_untrusted
from .search import KeywordIndex, split_entries, with_thread_context

log = logging.getLogger(__name__)


class PromptTooLong(ValueError):
    pass


def request_bytes(request: dict) -> bytes:
    return json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def bounded_history(history, count, limits):
    count = min(count, 4)
    clipped = (
        [
            {
                "role": message.get("role"),
                "content": clean_untrusted(str(message.get("content") or ""))[
                    : min(limits.max_history_message_chars, 400)
                ],
            }
            for message in (history or [])[-count:]
        ]
        if count > 0
        else []
    )
    # Normalize again after merging, so adjacent same-role messages cannot exceed the cap.
    merged = normalize_history(clipped, count)
    for message in merged:
        message["content"] = message["content"][: min(limits.max_history_message_chars, 400)]
    return merged


def pack_entries(knowledge, role, question, history, limits, make_request):
    if len(question) > limits.max_question_chars:
        raise PromptTooLong(
            f"Please keep your question under {limits.max_question_chars} characters."
        )
    try:
        knowledge.reload_if_changed()
    except Exception:
        log.exception("FAQ reload failed; using the last approved copy")
    entries = [
        entry
        for doc in knowledge.documents_for(role)
        for entry in split_entries(doc)
        if entry.audience != "qm" or role == "qm"
    ]
    query = with_thread_context(question, history)
    scores = KeywordIndex([entry.text for entry in entries]).scores(query)
    ranked = []
    for index, (entry, score) in enumerate(zip(entries, scores)):
        if (
            role in {"annotator", "qc"}
            and entry.audience in {"annotator", "qc"}
            and entry.audience != role
        ):
            score -= 0.1
        if entry.triggers and not any(trigger in query.lower() for trigger in entry.triggers):
            score -= 0.2
        ranked.append((index, score))
    ranked.sort(key=lambda item: item[1], reverse=True)
    selected = []
    request = make_request([])
    if len(request_bytes(request)) > limits.max_prompt_bytes:
        raise PromptTooLong(
            "Please shorten your question or start a new thread; the context is too long."
        )
    for index, _ in ranked:
        candidate = sorted([*selected, index])
        proposed = make_request([entries[i] for i in candidate])
        if len(request_bytes(proposed)) <= limits.max_prompt_bytes:
            selected, request = candidate, proposed
    if not selected:
        raise PromptTooLong(
            "There isn't room for the FAQ evidence. Please shorten your question or start a new thread."
        )
    return request, [entries[index] for index in selected]


def entry_context(entries):
    return "\n\n".join(f"{entry.id}. {entry.title}\n{entry.body}" for entry in entries)
