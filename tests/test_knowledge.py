"""Checks on the FAQ files themselves. These catch the mistakes most likely to give freelancers a
wrong answer, e.g. an old phase's model name sneaking into the current FAQ."""

import pytest

from gab_faq.knowledge import KnowledgeBase, parse_document

from .conftest import ROOT

# Model names from earlier phases. If any of these appear in knowledge/current/, the bot could tell
# freelancers to use the wrong model. Add to this list whenever a phase is archived.
ARCHIVED_MODEL_NAMES = [
    "Model Locust",
    "Claude Sonnet 5.5",
    "ultra_carbon_dte_test_arm",
    "Gemini 3.6",
]

# Phrases that only appear in the internal QM documents.
QM_ONLY_PHRASES = ["1 out of every 5", "QM Audit template", "chat.google.com"]


def test_current_faq_loads(knowledge):
    names = {d.path.name for d in knowledge.documents}
    assert {
        "phase6-annotation.md",
        "phase6-qc.md",
        "phase6-recording.md",
        "phase6-methodology.md",
        "phase6-instructions.md",
        "phase6-evaluation.md",
        "playground-help.md",
        "rating-reference.md",
    } <= names


def test_qm_documents_hidden_from_everyone_but_qms(tmp_path):
    (tmp_path / "shared.md").write_text("---\naudience: all\n---\nA1. Shared\nShared text.")
    (tmp_path / "internal.md").write_text("---\naudience: qm\n---\nQM1. Internal\nQM_ONLY_TEST.")
    knowledge = KnowledgeBase(tmp_path)
    for role in ("annotator", "qc", "unknown"):
        text = knowledge.render(role)
        assert "qm-process" not in text and 'audience="qm"' not in text
        assert "Shared text" in text and "QM_ONLY_TEST" not in text
    assert 'audience="qm"' in knowledge.render("qm")
    assert "QM_ONLY_TEST" in knowledge.render("qm")


def test_qm_only_facts_live_only_in_qm_documents(knowledge):
    """If a QM-only fact gets copied into a shared file, annotators could see it."""
    shared = knowledge.render("annotator")
    for phrase in QM_ONLY_PHRASES:
        assert phrase not in shared, f"{phrase!r} leaked into a non-QM document"


def test_task_flow_covers_current_runs_and_stage4_scope(knowledge):
    text = knowledge.render("annotator")
    for stage in [
        "Product A",
        "Product B",
        "Reset ID",
        "Stage 4",
        "artefact check",
        "pre-filled",
        "SxS",
    ]:
        assert stage in text


def test_no_export_scripts_in_knowledge(knowledge):
    """The JavaScript export scripts are huge and useless to the bot; keep them out."""
    text = knowledge.render("qm")
    assert "async () =>" not in text and "querySelectorAll" not in text


def test_archive_is_not_loaded(knowledge):
    assert all("archive" not in str(d.path) for d in knowledge.documents)
    assert "ARCHIVED" not in knowledge.render()


@pytest.mark.parametrize("old_name", ARCHIVED_MODEL_NAMES)
def test_current_faq_has_no_archived_model_names(knowledge, old_name):
    assert old_name not in knowledge.render()


def test_current_faq_has_current_models(knowledge):
    text = knowledge.render()
    for name in ["GOAT-on-Thorin DTE (Gmail Fixes)", "flash_dte_test_arm", "GPT-5.6 Terra High"]:
        assert name in text


def test_old_recording_and_queue_requirements_are_not_active(knowledge):
    assert all(doc.phase == "6.1" for doc in knowledge.documents)
    assert "No screen recording is needed for Phase 6.1" in knowledge.render()
    assert "5 hours after you pick it up" not in knowledge.render()
    assert "1 out of every 5" not in knowledge.render("qm")


def test_every_document_has_valid_header(knowledge):
    for doc in knowledge.documents:
        assert doc.audience in {"annotator", "qc", "qm", "all"}
        assert doc.phase, f"{doc.path.name} is missing 'phase'"
        assert doc.updated, f"{doc.path.name} is missing 'updated'"


def test_render_is_stable(knowledge):
    assert knowledge.render() == knowledge.render()


def test_bad_audience_rejected(tmp_path):
    p = tmp_path / "bad.md"
    p.write_text("---\ntitle: x\naudience: managers\n---\nbody")
    with pytest.raises(ValueError):
        parse_document(p)


def test_broken_header_names_the_file(tmp_path):
    p = tmp_path / "broken.md"
    p.write_text('---\ntitle: x\nsource: "a.pdf" and more\n---\nbody')
    with pytest.raises(ValueError, match="broken.md"):
        parse_document(p)


def test_all_knowledge_files_parse():
    for p in (ROOT / "knowledge").rglob("*.md"):
        parse_document(p)


def test_reload_picks_up_edits(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("---\ntitle: A\naudience: all\nphase: 5\nupdated: x\n---\nfirst")
    kb = KnowledgeBase(tmp_path)
    assert "first" in kb.render()
    p.write_text("---\ntitle: A\naudience: all\nphase: 5\nupdated: x\n---\nsecond version")
    assert kb.reload_if_changed()
    assert "second version" in kb.render()


def test_empty_folder_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        KnowledgeBase(tmp_path)


def test_archive_folder_exists():
    assert (ROOT / "knowledge" / "archive").is_dir()
