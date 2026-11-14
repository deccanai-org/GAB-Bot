"""The free FAQ search (Layer 1). Most tests use a stand-in for the embedding model so they're fast
and need no download; the last ones use the real model if it's on disk (it is in the Docker image)."""

from collections import Counter
from functools import lru_cache
from pathlib import Path

import pytest

from gab_faq.config import load_settings
from gab_faq.knowledge import KnowledgeBase, parse_document
from gab_faq.search import (
    NOT_FOUND,
    PAYMENT_REPLY,
    UNSURE_INTRO,
    FaqSearch,
    KeywordIndex,
    SearchSettings,
    is_payment_question,
    is_small_talk,
    split_entries,
    with_thread_context,
    words,
)

from .conftest import ROOT

FAQ = """---
title: Test FAQ
audience: annotator
phase: 5
updated: x
---

Version note: ignored, it's before the first item.

## Models

A1. Which model is Product A?
Select Flash, then Model Locust.

A2. What are the steps?
1. Set up the account.
2. Record the screen.

## Recording

SR1. Can I use OBS?
No. Only the approved recorder.
"""

QM_FAQ = """---
title: QM notes
audience: qm
phase: 5
updated: x
---

QM1. How many tasks does a QM check?
1 out of every 5.
"""


@pytest.fixture
def faq_dir(tmp_path):
    (tmp_path / "a.md").write_text(FAQ)
    (tmp_path / "qm.md").write_text(QM_FAQ)
    return tmp_path


def test_split_entries(faq_dir):
    entries = split_entries(parse_document(faq_dir / "a.md"))
    assert [e.id for e in entries] == ["A1", "A2", "SR1"]
    assert entries[0].title == "Which model is Product A?"
    assert entries[0].body == "Select Flash, then Model Locust."
    assert entries[0].section == "Models" and entries[2].section == "Recording"
    assert "2. Record the screen." in entries[1].body  # numbered steps stay inside the entry
    assert all("Version note" not in e.text for e in entries)


def test_real_faq_entries_have_unique_ids():
    kb = KnowledgeBase(ROOT / "knowledge" / "current")
    ids = [e.id for d in kb.documents for e in split_entries(d)]
    assert {"A1", "A8", "EV1", "EV16", "IN35", "Q14", "PG11", "RR7h"} <= set(ids)
    assert not [i for i, n in Counter(ids).items() if n > 1], "two FAQ entries share an ID"


def test_words_and_keywords():
    assert words("Recording the models") == ["record", "model"]
    index = KeywordIndex(["Which model is Product A? Flash Locust", "Screen recording with OBS"])
    locust, obs = index.scores("product locust flash?")
    assert locust == 1.0 and obs == 0.0
    assert max(index.scores("capital of France")) == 0.0


def test_one_word_questions_get_a_damped_keyword_score():
    index = KeywordIndex(["Which model is Product A? Flash Locust", "Screen recording with OBS"])
    assert max(index.scores("locust")) < 0.5  # one word: weak evidence
    assert max(index.scores("product a locust flash")) == 1.0
    assert words("what is GAB in this project phase") == []  # project-wide words are ignored


def test_small_talk():
    assert is_small_talk("thanks a lot!") and is_small_talk("hi") and is_small_talk("ok cool")
    assert not is_small_talk("hi which model do I use?")


class FakeEmbedder:
    """Each FAQ entry gets its own direction; a question's direction is set per test."""

    def __init__(self):
        self.query_vector = None

    def passages(self, texts):
        return [[1.0 if i == j else 0.0 for j in range(len(texts))] for i in range(len(texts))]

    def query(self, text):
        return self.query_vector


def make_search(faq_dir, **overrides):
    embedder = FakeEmbedder()
    settings = SearchSettings(
        keyword_weight=0.0, **overrides
    )  # meaning score only, so tests control it
    return FaqSearch(KnowledgeBase(faq_dir), settings, embedder=embedder), embedder


def entry_vector(search, entry_id, strength):
    return [strength if e.id == entry_id else 0.0 for e in search.entries]


def test_confident_match_posts_the_entry(faq_dir):
    search, emb = make_search(faq_dir)
    emb.query_vector = entry_vector(search, "A1", 0.95)
    ans = search.answer("which model for product a", role="annotator")
    assert ans.outcome == "answered" and ans.sources == ["A1"]
    assert (
        ans.text
        == "From the GAB FAQ (A1. Which model is Product A?):\nSelect Flash, then Model Locust."
    )
    assert not ans.needs_escalation


def test_unsure_match_shows_closest_and_flags(faq_dir):
    search, emb = make_search(faq_dir)
    emb.query_vector = entry_vector(search, "SR1", 0.75)
    ans = search.answer("what recorder do I use", role="annotator")
    assert ans.outcome == "partial" and ans.needs_escalation
    assert ans.text.startswith(UNSURE_INTRO) and "SR1. Can I use OBS?" in ans.text
    assert "closest: SR1" in ans.escalation_reason


def test_no_match_flags_for_team(faq_dir):
    search, emb = make_search(faq_dir)
    emb.query_vector = entry_vector(search, "A2", 0.4)
    ans = search.answer("what's the weather", role="annotator")
    assert ans.outcome == "not_in_faq" and ans.text == NOT_FOUND and ans.needs_escalation


def test_close_second_entry_is_shown_too(faq_dir):
    search, emb = make_search(faq_dir)
    emb.query_vector = [
        0.95 if e.id == "A1" else 0.93 if e.id == "A2" else 0.0 for e in search.entries
    ]
    ans = search.answer("models and steps", role="annotator")
    assert ans.sources == ["A1", "A2"] and "A2. What are the steps?" in ans.text


def test_qm_entries_only_for_qms(faq_dir):
    search, emb = make_search(faq_dir)
    emb.query_vector = entry_vector(search, "QM1", 0.99)
    assert (
        search.answer("how many tasks does my QM check", role="annotator").outcome == "not_in_faq"
    )
    assert search.answer("how many tasks does my QM check", role="qm").sources == ["QM1"]


def test_payment_and_small_talk_never_search(faq_dir):
    search, emb = make_search(faq_dir)
    emb.query_vector = entry_vector(search, "A1", 0.99)
    pay = search.answer("when will I get paid for last week?")
    assert pay.outcome == "needs_human" and pay.text == PAYMENT_REPLY
    assert search.answer("thanks!").outcome == "small_talk"


def test_faq_edits_are_picked_up(faq_dir):
    search, emb = make_search(faq_dir)
    (faq_dir / "a.md").write_text(
        FAQ.replace("SR1. Can I use OBS?", "SR1. Can I use OBS or Loom?")
        + "\nSR2. New item\nNew.\n"
    )
    emb.query_vector = None  # vector size changes with the entry count; rebuilt below
    search._build()
    assert "SR2" in [e.id for e in search.entries]


def test_keyword_only_mode_still_answers(faq_dir):
    search = FaqSearch(KnowledgeBase(faq_dir), SearchSettings(), embedder=None)
    ans = search.answer("which model is product A, flash or locust?", role="annotator")
    assert ans.sources[0] == "A1"
    assert ans.outcome == "partial" and ans.needs_escalation


def test_precomputed_vectors_are_reused_and_invalidated_by_knowledge_changes(faq_dir, tmp_path):
    class CachedEmbedder(FakeEmbedder):
        fingerprint = "test-model-artifact"
        calls = 0

        def passages(self, texts):
            self.calls += 1
            return super().passages(texts)

    embedder = CachedEmbedder()
    settings = SearchSettings(cache_dir=tmp_path / "vectors")
    first = FaqSearch(KnowledgeBase(faq_dir), settings, embedder=embedder)
    assert embedder.calls == 1
    second = FaqSearch(KnowledgeBase(faq_dir), settings, embedder=embedder)
    assert not first.cache_loaded and second.cache_loaded
    assert embedder.calls == 1
    (faq_dir / "a.md").write_text(FAQ.replace("Model Locust", "Updated Model Locust"))
    FaqSearch(KnowledgeBase(faq_dir), settings, embedder=embedder)
    assert embedder.calls == 2


def test_corrupt_vector_cache_is_recomputed(faq_dir, tmp_path):
    class CachedEmbedder(FakeEmbedder):
        fingerprint = "test-model-artifact"

    settings = SearchSettings(cache_dir=tmp_path / "vectors")
    original = FaqSearch(KnowledgeBase(faq_dir), settings, embedder=CachedEmbedder())
    (settings.cache_dir / "faq-index.json").write_text('{"vectors": null}')
    replacement = FaqSearch(KnowledgeBase(faq_dir), settings, embedder=CachedEmbedder())
    assert replacement._vectors == original._vectors


# --- With the real model (skipped if it hasn't been downloaded) ---


def _real_search():
    settings = load_settings(ROOT / "config.yaml").search
    if not any(Path(settings.cache_dir).glob("**/*.onnx")):
        pytest.skip("embedding model not downloaded (run the bot or scripts/run_eval.py once)")
    return _load_real_search()


@lru_cache(maxsize=1)
def _load_real_search():
    settings = load_settings(ROOT / "config.yaml").search
    return FaqSearch(KnowledgeBase(ROOT / "knowledge" / "current"), settings)


@pytest.mark.parametrize(
    "question,role,expected",
    [
        ("which model do i pick for product A?", "annotator", "A1"),
        ("debug json shows null for model A, should I reject?", "qc", {"Q14", "F5"}),
        ("When should I score each product?", "annotator", "F3"),
        ("Should model memory be on or off?", "annotator", "IN9"),
    ],
)
def test_real_model_finds_the_right_entry(question, role, expected):
    ans = _real_search().answer(question, role=role)
    expected_ids = {expected} if isinstance(expected, str) else expected
    assert ans.outcome == "answered" and ans.sources[0] in expected_ids


def test_real_model_does_not_invent_answers_for_off_topic():
    assert _real_search().answer("What's the capital of France?").outcome == "not_in_faq"


@pytest.mark.parametrize(
    "question", ["what is gab", "what is gab i need to understand the project"]
)
def test_real_model_no_confident_answer_from_one_shared_word(question):
    """The FAQ has no "what is GAB" entry. Seen live: "what is gab" got a confident, wrong answer
    because "gab" appears in an unrelated entry."""
    assert _real_search().answer(question, role="qc").outcome in ("not_in_faq", "partial")


@pytest.mark.parametrize(
    "question,role,expected",
    [
        ("What is the Stage 4 human evaluation workflow?", "qc", "EV1"),
        ("Which ratings can I correct in Stage 4?", "qc", "EV2"),
        ("How do I run the ChatGPT export script?", "annotator", "IN35"),
        ("Which model is Product B?", "annotator", "A2"),
        # Checklists used to be outside any numbered entry, so the bot could not find them.
        ("what's on the pre-submission checklist?", "annotator", "A15"),
        ("is there a checklist I should run before approving a task?", "qc", "Q19"),
        ("why do we even need a screen recording?", "annotator", "SR0"),
    ],
)
def test_real_model_role_and_checklist_entries(question, role, expected):
    assert _real_search().answer(question, role=role).sources[0] == expected


def test_real_model_follow_up_in_a_thread_uses_the_earlier_question():
    history = [
        {"role": "user", "content": "which model do I pick for product A?"},
        {"role": "assistant", "content": "From the GAB FAQ (A1. Which model is Product A?): ..."},
    ]
    ans = _real_search().answer("and for product B?", role="annotator", history=history)
    assert ans.outcome == "answered" and "GPT-5.6 Terra High" in ans.text


# --- Coverage: every guideline in knowledge/current/ must be inside a numbered entry ---


def test_every_line_of_the_current_faq_is_searchable():
    """Text outside a numbered entry is never indexed, so the bot can't answer from it. This once
    hid both checklists, the tutorial video list and why screen recordings are needed."""
    kb = KnowledgeBase(ROOT / "knowledge" / "current")
    dropped = []
    for doc in kb.documents:
        inside = set()
        for e in split_entries(doc):
            inside.update(line.strip() for line in f"{e.id}. {e.title}\n{e.body}".splitlines())
        for line in doc.body.splitlines():
            s = line.strip()
            if (
                s
                and not s.startswith("#")
                and not (s.startswith("<!--") and s.endswith("-->"))
                and s not in inside
            ):
                dropped.append(f"{doc.path.name}: {s[:70]}")
    assert not dropped, (
        "FAQ text outside any numbered entry (add an ID like 'A16.'):\n" + "\n".join(dropped)
    )


# --- Roles, summaries, Product A/B, payment, small talk, follow-ups ---

ROLE_FAQ = """---
title: Flow
audience: all
phase: 5
updated: x
---

## For annotators
<!-- audience: annotator -->

F7. How many tasks can I pick up?
2 per hour.

## For QC reviewers
<!-- audience: qc -->

F13. How many QC tasks can I pick up?
20 per hour.

## Checklist
<!-- summary: checklist -->

C1. What is on the checklist?
- 2 per hour for annotators, 20 for QC.
"""


@pytest.fixture
def role_dir(tmp_path):
    (tmp_path / "flow.md").write_text(ROLE_FAQ)
    return tmp_path


def test_section_markers_set_audience_and_summary(role_dir):
    entries = {e.id: e for e in split_entries(parse_document(role_dir / "flow.md"))}
    assert entries["F7"].audience == "annotator" and entries["F13"].audience == "qc"
    assert entries["C1"].audience == "all" and entries["C1"].triggers == ("checklist",)
    assert all("<!--" not in e.text for e in entries.values())


def test_role_decides_between_equally_good_entries(role_dir):
    search, emb = make_search(role_dir)
    emb.query_vector = [0.95 if e.id in ("F7", "F13") else 0.0 for e in search.entries]
    assert search.answer("how many tasks per hour", role="qc").sources[0] == "F13"
    assert search.answer("how many tasks per hour", role="annotator").sources[0] == "F7"


def test_summary_entries_only_win_when_asked_for(role_dir):
    search, emb = make_search(role_dir)
    # The checklist matches slightly better on meaning, as checklists mention every topic.
    emb.query_vector = [
        0.96 if e.id == "C1" else 0.95 if e.id == "F7" else 0.0 for e in search.entries
    ]
    assert search.answer("how many tasks per hour", role="annotator").sources[0] == "F7"
    assert search.answer("what is on the checklist", role="annotator").sources[0] == "C1"


def test_product_a_and_b_stay_distinct_for_keywords():
    assert "producta" in words("Which model is Product A?") and "productb" in words(
        "Model B settings"
    )
    assert "productb" not in words("product A") and "product" in words("product A")


@pytest.mark.parametrize(
    "question,is_pay",
    [
        ("when will I get paid?", True),
        ("how much do we get per task?", True),
        ("whats the rate per task for annotation?", True),
        ("when does the money for finished tasks come through?", True),
        ("what should I pay attention to in the recording?", False),
        ("how do I rate the outcome quality dimension?", False),
    ],
)
def test_payment_questions_without_payment_words(question, is_pay):
    assert is_payment_question(question) is is_pay


def test_small_talk_with_fillers():
    assert is_small_talk("good morning all!") and is_small_talk("thanks, that cleared it up")
    assert is_small_talk("ok got it, thanks bro")
    assert not is_small_talk("thanks, which model for product A?")
    assert not is_small_talk("ok so what about the debug json")


def test_thread_context_only_for_short_follow_ups():
    history = [
        {"role": "user", "content": "which model for product A?"},
        {"role": "assistant", "content": "A1"},
    ]
    assert (
        with_thread_context("and for product B?", history)
        == "which model for product B? and for product B?"
    )
    assert with_thread_context("what about QC?", history).startswith("which model")
    assert with_thread_context("how do I reset the environment after model A?", history).startswith(
        "how do I reset"
    )
    assert with_thread_context("and for product B?", None) == "and for product B?"
    assert (
        with_thread_context(
            "and for Model A?", [{"role": "user", "content": "Which model for Model B?"}]
        )
        == "Which model for model A? and for Model A?"
    )
    both = [{"role": "user", "content": "How do Product A and Product B differ?"}]
    assert with_thread_context("and for Product B?", both).startswith(
        "How do Product A and Product B differ?"
    )
