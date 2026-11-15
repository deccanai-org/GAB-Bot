"""Select complete approved FAQ entries within the provider request byte budget."""

from __future__ import annotations

import json
import math

from .conversation import normalize_history
from .redact import clean_untrusted, scrub_mentions
from .retrieval import LocalRetriever
from .sources import prompt_text


class PromptTooLong(ValueError):
    pass


class NoEvidence(ValueError):
    pass


class EvidenceConflict(ValueError):
    pass


def estimated_input_tokens(request):
    # Planning estimate for English text; not a Qwen tokenizer or a hard token count.
    return (
        sum(math.ceil(len(m["content"].encode("utf-8")) / 3) + 8 for m in request["messages"]) + 8
    )


def request_bytes(request: dict) -> bytes:
    return json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def bounded_history(history, count, limits):
    count = min(count, 4)
    clipped = (
        [
            {
                "role": message.get("role"),
                "content": clean_untrusted(scrub_mentions(str(message.get("content") or "")))[
                    : min(limits.max_history_message_chars, 400)
                ],
            }
            for message in (history or [])[-count:]
        ]
        if count > 0
        else []
    )
    # Normalize again after merging, so adjacent same-role messages cannot exceed the cap.
    merged = normalize_history(clipped, count, keep_last_user=True)
    for message in merged:
        message["content"] = message["content"][: min(limits.max_history_message_chars, 400)]
    return merged


ESSENTIAL_TOO_LONG = (
    "The relevant FAQ and its essential exceptions exceed the context budget. "
    "Please ask about one part, or contact the team."
)


def fits(request, limits) -> bool:
    return (
        len(request_bytes(request)) <= limits.max_prompt_bytes
        and estimated_input_tokens(request) <= limits.max_input_tokens
    )


def pack_entries(
    knowledge,
    role,
    question,
    history,
    limits,
    make_request,
    retrieval_query=None,
    *,
    sent_history=None,
    allow_empty=False,
):
    """(request, entries) within the byte and token budget.

    Priority, highest first: the rules prompt and the question (never cut), the best-matching entry
    together with every entry it requires (all or nothing: an exception is never dropped to fit),
    then earlier conversation messages (oldest dropped first), then further matching entries.
    Nothing is silently truncated: if the essential part cannot fit, PromptTooLong says so.
    `make_request(entries, history_messages)` builds the provider request.
    """
    if len(question) > limits.max_question_chars:
        raise PromptTooLong(
            f"Please keep your question under {limits.max_question_chars} characters."
        )
    evidence = LocalRetriever(knowledge).retrieve(
        retrieval_query or question, role, history, limits.retrieval_candidates
    )
    if evidence.problem:
        raise EvidenceConflict(evidence.problem)
    if not evidence.candidates and not allow_empty:
        raise NoEvidence("No relevant approved current FAQ evidence")
    index = {candidate.entry.id: candidate.entry for candidate in evidence.candidates}

    def bundle(entry, collected):
        if entry.id in collected:
            return
        collected[entry.id] = entry
        for ident in entry.requires:
            if ident not in index:
                raise EvidenceConflict("Required current exception unavailable")
            bundle(index[ident], collected)

    bundles = []
    for candidate in evidence.candidates:
        proposed = {}
        bundle(candidate.entry, proposed)
        bundles.append(proposed)
    first = bundles[0] if bundles else {}
    sent_history = list(sent_history or [])
    # Drop the oldest user/assistant pair first; history always restarts on a user message.
    options = [sent_history[i:] for i in range(0, len(sent_history), 2)] + [[]]
    kept = next((h for h in options if fits(make_request(list(first.values()), h), limits)), None)
    if kept is None:
        raise PromptTooLong(ESSENTIAL_TOO_LONG)
    selected = dict(first)
    for extra in bundles[1:]:
        proposed = {**selected, **extra}
        if fits(make_request(list(proposed.values()), kept), limits):
            selected = proposed
    entries = list(selected.values())
    return make_request(entries, kept), entries


AUDIENCE_LABELS = {"annotator": "annotators", "qc": "QC reviewers", "qm": "queue managers"}


def entry_context(entries):
    """Each entry carries its audience, so the model can respect the asker's role."""
    return "\n\n".join(
        f"{entry.id}. {entry.title} [for {AUDIENCE_LABELS.get(entry.audience, 'everyone')}; version={entry.version}; status={entry.status}; requires={','.join(entry.requires) or 'none'}]"
        f"\n{prompt_text(entry.body)}"
        for entry in entries
    )
