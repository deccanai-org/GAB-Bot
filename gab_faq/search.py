"""Layer 1: answers a question by finding the best matching entry in the FAQ files.

Free: no AI service, no API key, and nothing leaves the server.

How it works
  1. The FAQ files are split into entries: each numbered item (A1., Q14., F7., ...) with the text
     under it, up to the next numbered item or heading. 142 entries in Phase 5.
  2. Meaning: each entry is turned into a list of numbers that captures what it is about (an
     "embedding"), by a small model that runs inside the bot on the CPU (fastembed with
     BAAI/bge-small-en-v1.5, about 70 MB). A question gets the same treatment, and entries whose
     numbers are closest to the question's are about the same thing, even with different words.
  3. Keywords: a second score counts the question's important words that appear in the entry
     (rare words like "Locust" or "debug" count more than common ones), so exact terms matter too.
  4. Confident match: the bot posts that entry word for word. Weak match: it says the FAQ doesn't
     cover it and flags the question for the team.

Because it only ever posts FAQ text, it can't invent an answer or an old model name. It can pick the
wrong entry, which is why low-confidence matches go to the team instead.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .contracts import Answer
from .knowledge import FaqDocument, KnowledgeBase
from .storage import atomic_write

log = logging.getLogger(__name__)

ENTRY_RE = re.compile(r"^([A-Z]{1,3}\d+[a-z]?)\.\s+(.+)$")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$")
# "<!-- audience: qc -->" under a heading: the entries in that section are for that role only (used
# in files for everyone, e.g. the task flow, where annotators and QC reviewers have different limits).
AUDIENCE_RE = re.compile(r"^<!--\s*audience:\s*([a-z]+)\s*-->$", re.IGNORECASE)
# "<!-- summary: checklist, before submitting -->" under a heading: the entries in that section sum up
# many other entries (e.g. a checklist), so they touch almost every topic. They rank lower unless the
# question uses one of the listed words, so the detailed entry wins for specific questions.
SUMMARY_RE = re.compile(r"^<!--\s*summary:\s*(.+?)\s*-->$", re.IGNORECASE)
DIRECTIVE_RE = re.compile(r"^<!--.*-->$")
WORD_RE = re.compile(r"[a-z0-9]+")
# "Product A" / "Model B": the letter alone is dropped as too short, which made Product A and Product
# B look identical to the keyword score. Keep the word and add a joined token ("product producta").
AB_RE = re.compile(r"\b(product|model)\s*([ab])\b")  # "Model B" and "Product B" mean the same here

STOPWORDS = frozenset(
    """
a an the and or but if then so of to in on at by for with from into about as is are was were be been
being am do does did done have has had having i me my mine we our you your he she it its they them
their this that these those there here what which who whom whose when where why how can could should
would will shall may might must not no yes any some all each every just also only than too very
please hi hello hey thanks thank ok okay get got go going want need know tell let im ive dont cant
""".split()
) | frozenset(
    # Words used all over this project's FAQ: they don't help pick an entry, and on their own
    # ("what is gab") they made an unrelated entry look like a perfect keyword match.
    "gab project phase".split()
)

# Short messages made only of these words are small talk, not questions.
SMALL_TALK_WORDS = frozenset(
    """
hi hii hiii hello hey heya thanks thank you thx ty tysm ok okay k cool great nice good morning
afternoon evening night bye goodbye a lot so much very got it sure noted alright fine welcome gm
""".split()
)
THANKS_WORDS = frozenset({"thanks", "thank", "thx", "ty", "tysm"})
# Words that often come with a greeting or thanks ("good morning all", "thanks, that cleared it up",
# "ok got it, thanks bro"). Only used when the message also has a greeting/thanks word and no "?".
SMALL_TALK_FILLER = frozenset(
    """
all everyone guys bro bhai sir maam mam team folks that this it up cleared clears clear helped helps
helpful makes sense perfect awesome appreciated appreciate info answer for the again understood yes
yeah yep right clarifying
""".split()
)
SMALL_TALK_ANCHORS = THANKS_WORDS | frozenset(
    """
hi hii hiii hello hey heya morning afternoon evening gm bye goodbye ok okay noted understood got
""".split()
)
# The two roles whose FAQ entries differ; the role penalty applies only between these.
ROLES = frozenset({"annotator", "qc"})

# Payment questions always go to the team: the FAQ doesn't cover pay, and a wrong answer about money
# does real harm.
PAYMENT_WORDS = frozenset(
    """
paid payment payments payout payouts salary salaries invoice invoices stipend compensation earnings
remuneration bank refund pay paying money wage wages incentive incentives bonus rupees inr usd dollars
earn
""".split()
)
# Pay questions that use none of the words above ("how much do we get per task?").
PAYMENT_PHRASES = re.compile(
    r"\bhow much (do|will|would|can|does|did) (we|i|you|one|they|annotators?|reviewers?) "
    r"(get|earn|make|receive)\b"
    r"|\b(rate|price|amount) (per|for each|for a|for one) (task|hour)\b"
    r"|\bper (task|hour) (rate|price|amount)\b"
)
# "pay attention" is not about money.
NOT_PAYMENT = re.compile(r"\bpay(ing)? (close |more )?attention\b")
# A short reply in a thread that only makes sense with the earlier question ("and for product B?").
FOLLOWUP_RE = re.compile(
    r"^(and|also|what about|how about|same (for|with)|but|then|what if|ok and|so)\b", re.IGNORECASE
)

NOT_FOUND = (
    "I couldn't find this in the GAB FAQ, so I've flagged it for the team. "
    "A team member will follow up."
)
PAYMENT_REPLY = (
    "Payment questions are handled by the team, not the FAQ. I've flagged this so a team "
    "member can help you."
)
THANKS_REPLY = "You're welcome! Ask me anything else about the GAB project."
GREETING_REPLY = (
    "Hi! I answer questions from the GAB project FAQ: models, screen recording, debug JSON, "
    "turns, QC checks and so on. Just ask your question."
)


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    body: str
    section: str
    audience: str
    document: str
    # For summary entries (see SUMMARY_RE): words that show the question is about the summary itself.
    triggers: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}".strip()


def split_entries(doc: FaqDocument) -> list[Entry]:
    """The numbered items of one FAQ file. Text that is not inside a numbered item (e.g. a version
    note before the first item) is skipped, so every fact the bot should answer must sit inside an
    item: tests/test_search.py checks this for knowledge/current/."""
    entries: list[Entry] = []
    section = ""
    section_audience = None
    section_triggers: tuple[str, ...] = ()
    item_id = title = item_section = item_audience = None
    item_triggers: tuple[str, ...] = ()
    lines: list[str] = []

    def flush():
        if item_id:
            entries.append(
                Entry(
                    item_id,
                    title,
                    "\n".join(lines).strip(),
                    item_section,
                    item_audience or doc.audience,
                    doc.title,
                    item_triggers,
                )
            )

    for line in doc.body.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            flush()
            item_id, lines = None, []
            section = heading.group(1).strip()
            section_audience, section_triggers = None, ()
            continue
        stripped = line.strip()
        if DIRECTIVE_RE.match(stripped):
            audience, summary = AUDIENCE_RE.match(stripped), SUMMARY_RE.match(stripped)
            if audience:
                section_audience = audience.group(1).lower()
            if summary:
                section_triggers = tuple(
                    w.strip().lower() for w in summary.group(1).split(",") if w.strip()
                )
            continue  # directives are never part of an answer
        item = ENTRY_RE.match(line)
        if item:
            flush()
            item_id, title, item_section, lines = item.group(1), item.group(2).strip(), section, []
            item_audience, item_triggers = section_audience, section_triggers
            continue
        if item_id:
            lines.append(line)
    flush()
    return entries


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    for suffix in ("ing", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3 and not word.endswith("ss"):
            return word[: -len(suffix)]
    return word


def words(text: str) -> list[str]:
    """Lower-case words with common endings removed ("recording" -> "record") and filler words
    dropped, for the keyword score."""
    text = AB_RE.sub(r"\1 product\2", text.lower())
    return [_stem(w) for w in WORD_RE.findall(text) if w not in STOPWORDS and len(w) > 1]


def is_payment_question(question: str) -> bool:
    low = NOT_PAYMENT.sub(" ", question.lower())
    return bool(set(WORD_RE.findall(low)) & PAYMENT_WORDS or PAYMENT_PHRASES.search(low))


def with_thread_context(question: str, history: list[dict] | None) -> str:
    """A short follow-up in a thread ("and for product B?", "what about QC?") is searched together
    with the asker's previous question, so it finds the right entry."""
    if not history:
        return question
    previous = next(
        (
            m.get("content", "")
            for m in reversed(history)
            if m.get("role") == "user" and (m.get("content") or "").strip()
        ),
        "",
    )
    if previous and (FOLLOWUP_RE.match(question) or len(words(question)) <= 2):
        return f"{previous.strip()} {question}"
    return question


class KeywordIndex:
    """Share of the question's important words found in each entry, weighted by how rare each word
    is across the FAQ (a word in every entry tells you nothing; "Locust" tells you a lot). A
    question full of words the FAQ never uses (e.g. about France) scores near 0 everywhere."""

    def __init__(self, texts: list[str]):
        self.docs = [set(words(t)) for t in texts]
        n = len(self.docs)
        df = Counter(w for d in self.docs for w in d)
        self.idf = {w: math.log(1 + n / c) for w, c in df.items()}
        self.unknown_idf = math.log(1 + n / 0.5)

    def scores(self, question: str) -> list[float]:
        q = set(words(question))
        if not q:
            return [0.0] * len(self.docs)
        weights = {w: self.idf.get(w, self.unknown_idf) for w in q}
        total = sum(weights.values())
        # A one- or two-word question matching an entry says little: scale the score down so a
        # single shared word can't produce a confident answer by itself.
        certainty = min(1.0, len(q) / 3)
        return [
            certainty * sum(wt for w, wt in weights.items() if w in d) / total for d in self.docs
        ]


class Embedder(Protocol):
    def passages(self, texts: list[str]) -> list[list[float]]: ...
    def query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """Runs the embedding model locally (CPU). The model files are downloaded once into cache_dir
    (at Docker build time in production) and then work offline."""

    def __init__(self, model_name: str, cache_dir: Path):
        import onnxruntime
        from fastembed import TextEmbedding  # imported here so tests don't need the model

        onnxruntime.disable_telemetry_events()
        self.model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir), threads=1)
        artifact = self.model.model._model_dir / self.model.model.model_description.model_file
        with artifact.open("rb") as handle:
            self.fingerprint = hashlib.file_digest(handle, "sha256").hexdigest()

    @staticmethod
    def _unit(vec) -> list[float]:
        norm = math.sqrt(sum(float(x) * float(x) for x in vec)) or 1.0
        return [float(x) / norm for x in vec]

    def passages(self, texts: list[str]) -> list[list[float]]:
        # Small batches: one big batch of all entries makes the model briefly use ~3 GB of memory.
        return [self._unit(v) for v in self.model.passage_embed(texts, batch_size=4)]

    def query(self, text: str) -> list[float]:
        return self._unit(next(iter(self.model.query_embed(text))))


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@dataclass(frozen=True)
class SearchSettings:
    model: str = "BAAI/bge-small-en-v1.5"
    cache_dir: Path = Path("models")
    # Final score = meaning score (0-1) + keyword_weight x keyword score (0-1).
    keyword_weight: float = 0.3
    # Three zones (tuned on tests/eval/questions.yaml plus questions the FAQ doesn't cover):
    #   score >= confident_score: post the entry.
    #   min_score <= score < confident_score: post the closest entry marked "not sure", and flag
    #     the question for the team.
    #   score < min_score: "not in the FAQ", and flag it.
    confident_score: float = 0.88
    min_score: float = 0.63
    # Also show the second-best entry if it scores at least this close to the best.
    related_margin: float = 0.03
    # Entries written for the other role (annotator vs QC reviewer) lose this much score, so a QC
    # reviewer asking "how many tasks can I pick up?" gets the QC limit, not the annotator one.
    role_penalty: float = 0.1
    # Summary entries (checklists) lose this much unless the question names them (see SUMMARY_RE).
    summary_penalty: float = 0.15


@dataclass(frozen=True)
class Hit:
    entry: Entry
    score: float
    meaning: float
    keywords: float


def is_small_talk(question: str) -> bool:
    tokens = WORD_RE.findall(question.lower())
    if 0 < len(tokens) <= 6 and all(t in SMALL_TALK_WORDS for t in tokens):
        return True
    return (
        "?" not in question
        and 0 < len(tokens) <= 8
        and any(t in SMALL_TALK_ANCHORS for t in tokens)
        and all(t in SMALL_TALK_WORDS or t in SMALL_TALK_FILLER for t in tokens)
    )


UNSURE_INTRO = "I'm not sure the FAQ covers this exactly. The closest entry is below, and I've flagged your question for the team."


def _entry_block(entry: Entry) -> str:
    text = f"From the GAB FAQ ({entry.id}. {entry.title}):"
    return f"{text}\n{entry.body}" if entry.body else text


def format_entry_answer(best: Entry, related: Entry | None = None, unsure: bool = False) -> str:
    text = _entry_block(best)
    if related is not None:
        text += "\n\n" + _entry_block(related)
    return f"{UNSURE_INTRO}\n\n{text}" if unsure else text


class FaqSearch:
    """Same interface as the Claude Brain: answer(question, role, history) -> Answer."""

    def __init__(
        self,
        knowledge: KnowledgeBase,
        settings: SearchSettings = SearchSettings(),
        embedder: Embedder | None | str = "auto",
    ):
        self.knowledge = knowledge
        self.settings = settings
        if embedder == "auto":
            embedder = self._load_embedder()
        self.embedder: Embedder | None = embedder
        self._lock = threading.Lock()
        self._built_for: tuple | None = None
        self.entries: list[Entry] = []
        self._vectors: list[list[float]] = []
        self._keywords: KeywordIndex | None = None
        self.cache_loaded = False
        self._build()

    def _load_embedder(self) -> Embedder | None:
        try:
            return FastEmbedder(self.settings.model, self.settings.cache_dir)
        except Exception:
            log.exception(
                "Could not load the embedding model %s; using keyword search only "
                "(answers will be less accurate)",
                self.settings.model,
            )
            return None

    def _build(self) -> None:
        """(Re)build the index when the FAQ files change. Called before every question; cheap when
        nothing changed."""
        try:
            self.knowledge.reload_if_changed()
        except Exception:
            log.exception("FAQ reload failed; using the previously loaded FAQ")
        signature = self.knowledge._signature
        if signature == self._built_for and self.entries:
            return
        entries = [e for doc in self.knowledge.documents for e in split_entries(doc)]
        if not entries:
            raise ValueError(
                f"No numbered FAQ entries (like 'A1. Question') found in {self.knowledge.directory}"
            )
        texts = [f"{e.section}: {e.text}" if e.section else e.text for e in entries]
        vectors = self._cached_vectors(texts) if self.embedder else []
        self.entries, self._vectors, self._keywords = entries, vectors, KeywordIndex(texts)
        self._built_for = signature
        log.info(
            "FAQ search index built: %d entries%s",
            len(entries),
            "" if self.embedder else " (keyword search only)",
        )

    def _cached_vectors(self, texts: list[str]) -> list[list[float]]:
        self.cache_loaded = False
        fingerprint = getattr(self.embedder, "fingerprint", None)
        if not fingerprint:
            return self.embedder.passages(texts)
        key = hashlib.sha256(
            json.dumps([fingerprint, texts], ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        path = self.settings.cache_dir / "faq-index.json"
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            vectors = cached["vectors"]
            if (
                cached.get("version") == 1
                and cached.get("key") == key
                and len(vectors) == len(texts)
            ):
                dimension = len(vectors[0]) if vectors else 0
                if dimension and all(
                    len(vector) == dimension
                    and all(
                        isinstance(value, (int, float)) and math.isfinite(value) for value in vector
                    )
                    for vector in vectors
                ):
                    log.info("Loaded precomputed FAQ embeddings")
                    self.cache_loaded = True
                    return vectors
        except (OSError, ValueError, KeyError, TypeError):
            pass
        vectors = self.embedder.passages(texts)
        try:
            atomic_write(path, json.dumps({"version": 1, "key": key, "vectors": vectors}))
        except OSError:
            log.warning(
                "FAQ index cache is read-only; current embeddings remain available in memory"
            )
        return vectors

    def search(self, question: str, role: str = "unknown", limit: int = 3) -> list[Hit]:
        lowered = question.lower()
        with self._lock:
            self._build()
            keyword_scores = self._keywords.scores(question)
            if self.embedder:
                q = self.embedder.query(question)
                meaning = [_dot(q, v) for v in self._vectors]
            else:
                meaning = [0.0] * len(self.entries)
            hits = []
            for entry, m, k in zip(self.entries, meaning, keyword_scores):
                if entry.audience == "qm" and role != "qm":
                    continue  # QM-only documents are never shown to anyone else
                score = m + self.settings.keyword_weight * k if self.embedder else k
                scale = 1.0 if self.embedder else 0.5
                if role in ROLES and entry.audience in ROLES and entry.audience != role:
                    score -= self.settings.role_penalty * scale
                if entry.triggers and not any(t in lowered for t in entry.triggers):
                    score -= self.settings.summary_penalty * scale
                hits.append(Hit(entry, score, m, k))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def answer(
        self, question: str, role: str = "unknown", history: list[dict] | None = None
    ) -> Answer:
        question = question.strip()
        lowered = set(WORD_RE.findall(question.lower()))
        if is_small_talk(question):
            reply = THANKS_REPLY if lowered & THANKS_WORDS else GREETING_REPLY
            return Answer(reply, "small_talk")
        if is_payment_question(question):
            return Answer(PAYMENT_REPLY, "needs_human", escalation_reason="payment question")

        hits = self.search(with_thread_context(question, history), role)
        best = hits[0] if hits else None
        # Keyword-only scores (no embedding model) run on a lower scale.
        scale = 1.0 if self.embedder else 0.5
        confident, minimum = self.settings.confident_score * scale, self.settings.min_score * scale
        if best is None or best.score < minimum:
            reason = "no FAQ entry matches"
            if best is not None:
                reason += f" (closest: {best.entry.id}, score {best.score:.2f})"
            return Answer(NOT_FOUND, "not_in_faq", escalation_reason=reason)

        # Keyword overlap has no calibrated semantic confidence. Degraded mode must
        # not confidently turn unrelated shared words into project instructions.
        unsure = self.embedder is None or best.score < confident
        related = None
        if (
            not unsure
            and len(hits) > 1
            and best.score - hits[1].score <= self.settings.related_margin
        ):
            related = hits[1].entry
        sources = [best.entry.id] + ([related.id] if related else [])
        if unsure:
            return Answer(
                format_entry_answer(best.entry, unsure=True),
                "partial",
                sources=sources,
                escalation_reason=f"not sure the FAQ answers this (closest: {best.entry.id}, "
                f"score {best.score:.2f})",
            )
        return Answer(format_entry_answer(best.entry, related), "answered", sources=sources)
