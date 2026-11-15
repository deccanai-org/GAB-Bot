"""Whole-approved-corpus BM25 retrieval with local synonyms and explicit evidence policy."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .search import split_entries, with_thread_context, words

# Curated vocabulary mappings, not extra project facts. Expand both documents and queries.
SYNONYMS = (
    (
        "record recording recorded video screencast screencap footage obs clipchamp capture capturing captured",
        "record screen",
    ),
    ("artifact artifacts artefact artefacts deliverable deliverables output outputs", "artefact"),
    ("nudge nudges remind reminders retry retries attempts", "nudge"),
    ("refresh refreshed reload reloaded reopen reopened", "reload"),
    ("lag latency slow delays delay wait waiting", "latency wait"),
    ("1st first initial", "first"),
    ("2nd second", "second"),
    ("picker dropdown selection choose pick", "select model"),
    ("followup followups follow-up follow-ups", "follow prompt"),
    ("seed opening", "seed"),
    ("persona login email credential credentials", "account persona"),
    ("upload attach attachment submit submission", "upload submit"),
    ("score scores scoring rating ratings rate", "rating score"),
    ("link links url urls share sharing", "share link"),
    # "link chatgpt to my drive" means connecting it to Workspace, not sharing a chat link.
    (
        "connect connected connection plugin plugins workspace link linking linked drive",
        "connect workspace",
    ),
    ("erase remove delete deleted deleting wipe wiping wiped", "delete"),
    ("turn turns message messages", "turn"),
    # Found live: "an earlier chat" never matched "old conversation", "bad" never "unacceptable".
    ("chat chats", "conversation"),
    ("earlier previous prior past older", "old"),
    ("bad poor weak wrong rejected", "unacceptable"),
)


# Words too generic to steer the retry search on their own ("what's a GOOD pasta recipe").
GENERIC_TERMS = frozenset(
    words(
        "good best great nice bad make made need needed get got thing things stuff way help know "
        "use using used want like tell give take try see look today now able sure really already"
    )
)


def terms(text):
    result = words(text)
    raw = set(re.findall(r"[a-z0-9]+(?:-[a-z]+)?", text.lower()))
    for variants, canonical in SYNONYMS:
        if raw.intersection(variants.split()):
            result.extend(words(canonical))
    return result


def targeted_query(question, history=None):
    return " ".join(dict.fromkeys(terms(with_thread_context(question, history))))[:180]


# Terms that on their own show a question is about the GAB project.
GAB_TERMS_RE = re.compile(
    r"\b(?:gab|gigi|annotat\w*|qc|qm|task\w*|persona|debug|arte?facts?|turns?|rubrics?|seed|sxs"
    r"|gemini|chatgpt|reset|expiry|queue|cosmo|playground|throttl\w*)\b"
    r"|\bproduct\s*[ab]\b|\bphase\s*6",
    re.IGNORECASE,
)
# Evaluation and writing vocabulary: relevant to GAB work, but common elsewhere too ("score").
EVALUATION_TERMS_RE = re.compile(
    r"\b(?:justif\w*|ratings?|scor\w*|criteri\w*|dimensions?|evaluat\w*|preferences?|intent"
    r"|key\s+turn|nudg\w*|follow[\s-]?ups?|l[12]|taxonomy|screen|record\w*"
    r"|conversation\s+(?:json|context))\b",
    re.IGNORECASE,
)


def is_gab_question(question, history=None, *, broad=False):
    """Whether a question is about GAB work. A generic shared word such as "model" is not enough.

    broad=True also accepts evaluation and writing vocabulary: enough to let the model decide
    (it may still say "unrelated"), not enough to hand a question to staff on its own."""
    text = with_thread_context(question, history)
    return bool(GAB_TERMS_RE.search(text) or (broad and EVALUATION_TERMS_RE.search(text)))


@dataclass(frozen=True)
class Candidate:
    entry: object
    score: float
    coverage: float


@dataclass
class Evidence:
    candidates: list[Candidate]
    required_ids: set[str]
    problem: str = ""
    clarification: str = ""
    exact: bool = False


class LocalRetriever:
    def __init__(self, knowledge):
        self.knowledge = knowledge

    def targeted_query(self, question, role="unknown", history=None):
        """The one local retry after a miss: only the question's terms (and their curated
        synonyms) that occur in approved FAQ entry TITLES for this role, falling back to entry
        text. Incidental words ("still", "capture") otherwise dilute coverage and hide the entry
        whose title is about the actual subject ("screen recording")."""
        self.knowledge.reload_if_changed()
        entries = [
            entry
            for document in self.knowledge.documents_for(role)
            for entry in split_entries(document)
            if entry.audience != "qm" or role == "qm"
        ]
        wanted = [
            term
            for term in dict.fromkeys(terms(with_thread_context(question, history)))
            if term not in GENERIC_TERMS
        ]
        for field in ("title", "text"):
            vocabulary = {term for entry in entries for term in terms(getattr(entry, field))}
            kept = [term for term in wanted if term in vocabulary]
            if kept:
                return " ".join(kept)[:180]
        return ""

    def retrieve(self, question, role="unknown", history=None, limit=6):
        # Reload failure is deliberately propagated: stale evidence must not look current.
        self.knowledge.reload_if_changed()
        all_entries = [
            e
            for d in self.knowledge.documents_for(role)
            for e in split_entries(d)
            if e.audience != "qm" or role == "qm"
        ]
        # Instruction-override attempts are refused before retrieval (policy.py); text here is data.
        ids = [entry.id for entry in all_entries]
        if len(ids) != len(set(ids)):
            return Evidence([], set(), "Duplicate FAQ IDs require source review")
        entries = [e for e in all_entries if e.status in {"current", "conflicting"}]
        index = {e.id: e for e in entries}
        superseded = {old for e in entries for old in e.supersedes}
        entries = [e for e in entries if e.id not in superseded]
        query = with_thread_context(question, history)
        q = Counter(terms(query))
        if not q or not entries:
            return Evidence([], set())
        docs = [Counter(terms(e.text)) for e in entries]
        df = Counter(t for doc in docs for t in doc)
        n = len(docs)
        avg = sum(sum(doc.values()) for doc in docs) / max(1, n)
        idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in q}
        total = sum(idf.values())
        ranked = []

        def normalize(text):
            return " ".join(re.findall(r"[a-z0-9]+", text.lower()))

        exact_ids = {e.id for e in entries if normalize(e.title) == normalize(question)}
        for e, doc in zip(entries, docs):
            length = sum(doc.values())
            score = sum(
                idf[t] * doc[t] * 2.2 / (doc[t] + 1.2 * (0.25 + 0.75 * length / avg))
                for t in q
                if doc[t]
            )
            coverage = sum(idf[t] for t in q if doc[t]) / total if total else 0
            title_overlap = len(set(terms(e.title)) & set(q)) / max(1, len(set(q)))
            score *= 1 + 0.6 * title_overlap
            if (
                e.audience in {"annotator", "qc"}
                and role in {"annotator", "qc"}
                and e.audience != role
            ):
                score *= 0.75
            if e.triggers and not any(t in query.lower() for t in e.triggers):
                score *= 0.5
            if e.id in exact_ids:
                score += 100
                coverage = 1
            # An unknown question cannot be made relevant by filling unused prompt space.
            if score > 0 and coverage >= 0.18:
                ranked.append(Candidate(e, score, coverage))
        ranked.sort(key=lambda c: (-c.score, c.entry.id))
        if not ranked or (ranked[0].coverage < 0.32 and not exact_ids):
            return Evidence([], set())
        best = ranked[0].score
        selected = [c for c in ranked if c.score >= best * 0.30][:limit]
        required = set()
        visiting = set()

        def include(entry):
            if entry.id in visiting:
                raise ValueError("Cyclic required FAQ evidence")
            visiting.add(entry.id)
            for ident in entry.requires:
                if ident not in index or ident in superseded:
                    raise ValueError("Required current FAQ evidence is unavailable")
                if ident not in required:
                    required.add(ident)
                    include(index[ident])
            visiting.remove(entry.id)

        try:
            for candidate in list(selected):
                include(candidate.entry)
        except ValueError as error:
            return Evidence([], set(), str(error))
        present = {c.entry.id for c in selected}
        selected.extend(Candidate(index[ident], best, 1) for ident in sorted(required - present))
        claims = {}
        for candidate in selected:
            for key, value in candidate.entry.claims:
                claims.setdefault(key, set()).add(value)
        conflicts = sorted(key for key, values in claims.items() if len(values) > 1)
        for entry in entries:
            for key, value in entry.claims:
                if key in claims:
                    claims[key].add(value)
        conflicts = sorted(key for key, values in claims.items() if len(values) > 1)
        if conflicts or any(c.entry.status == "conflicting" for c in selected):
            return Evidence(
                [], set(), "Unresolved current-source conflict: " + ", ".join(conflicts)
            )
        return Evidence(selected, required, exact=bool(exact_ids))
