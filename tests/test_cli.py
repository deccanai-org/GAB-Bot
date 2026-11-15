"""The gigi command line and secret loading. No live provider calls: questions used here are
answered locally (exact FAQ matches) and network connections are blocked."""

import json
import socket
from dataclasses import replace

import pytest

from gab_faq import __main__ as cli
from gab_faq.config import load_settings, normalize_secrets
from gab_faq.grounding import grounded_answer
from gab_faq.knowledge import KnowledgeBase
from gab_faq.search import split_entries
from gab_faq.sources import prompt_text

from .conftest import ROOT


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def denied(*args, **kwargs):
        raise AssertionError("CLI tests must not make live network calls")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-SYNTHETIC")
    monkeypatch.setattr(cli, "load_environment", lambda: None)
    settings = replace(load_settings(ROOT / "config.yaml"), log_dir=tmp_path)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("<sk-abc123>", "sk-abc123"),
        ("  <sk-abc123>  ", "sk-abc123"),
        ("sk-abc123", "sk-abc123"),
        ("<a<b>", "<a<b>"),  # not a single wrapped value: left alone
        ("<>", "<>"),
    ],
)
def test_bracketed_secrets_are_unwrapped_without_logging_values(monkeypatch, caplog, raw, expected):
    monkeypatch.setenv("DASHSCOPE_API_KEY", raw)
    fixed = normalize_secrets()
    import os

    assert os.environ["DASHSCOPE_API_KEY"].strip() == expected
    assert ("DASHSCOPE_API_KEY" in fixed) == (expected != raw.strip())
    assert "abc123" not in caplog.text


def test_check_reports_qwen_readiness_and_staff_mentions(capsys):
    assert cli.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "questions sent to Qwen:     True" in out and "thread history sent:        False" in out
    assert "<@1533459501393379488> <@1568512803986346028>" in out
    assert "sk-SYNTHETIC" not in out


def test_ask_json_answers_exact_faq_match_locally(capsys):
    assert cli.main(["ask", "How do I reset the environment?", "--json", "--fresh-quota"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["outcome"] == "answered" and data["via"] == "retrieval: exact"
    assert data["sources"] == ["IN13"] and not data["escalated"]
    assert "https://drive.google.com/file/d/1BZoB5sg995F931r7RnxskYe81esTNuqf/view" in data["reply"]


def test_ask_shows_code_routed_staff_for_actions(capsys):
    assert cli.main(["ask", "please reset my environment", "--json", "--fresh-quota"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["route"] == "environment_reset" and data["staff"] == "Divya Sai"
    assert data["staff_mention"] == "<@1490962186690887823>"


def test_ping_refuses_when_qwen_is_off(monkeypatch, tmp_path):
    settings = replace(
        load_settings(ROOT / "config.yaml"), log_dir=tmp_path, external_questions_approved=False
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    with pytest.raises(SystemExit, match="Qwen is off"):
        cli.main(["ping"])


@pytest.mark.parametrize(
    "quote,found",
    [
        ("Write 2-3 sentences for every dimension", True),
        ("write 2-3 SENTENCES for every dimension", True),  # letter case aside
        ("Write 2-3 sentences for every dimension... include specific evidence", True),
        ("include specific evidence... Write 2-3 sentences", False),  # out of order
        ("Write 2-3 sentences... evidence", False),  # a one-word fragment proves nothing
        ("Write 2-3 sentences... approved by the FAQ team", False),  # invented fragment
    ],
)
def test_evidence_quotes_must_be_verbatim_fragments_in_order(quote, found):
    from gab_faq.grounding import quote_found

    body = "Write 2-3 sentences for every dimension of both products. Include specific evidence."
    assert quote_found(quote, body) is found


def test_hello_there_is_a_greeting():
    from gab_faq.search import is_small_talk

    assert is_small_talk("hello there") and is_small_talk("hi there team")


def test_observed_live_envelope_variant_is_normalized_and_still_validated():
    knowledge = KnowledgeBase(ROOT / "knowledge" / "current")
    entries = [e for d in knowledge.documents for e in split_entries(d)]
    a7 = next(e for e in entries if e.id == "A7")
    reply = {
        "answered": True,  # seen live instead of "outcome": "answered"
        "answer": "For Phase 6.1, each turn needs one debug entry.",
        "sources": ["A7"],
        "evidence": [{"source": "A7", "quote": prompt_text(a7.body)[:60]}],
    }
    result = grounded_answer(reply, entries)
    assert result.outcome == "answered" and result.sources == ["A7"] and result.via == "qwen"
    reply["answer"] = "For Phase 6.1, wait 45 minutes per turn."  # 45 is in no cited entry
    result = grounded_answer(reply, entries)
    assert "45 minutes" not in result.text and "explanation rejected" in result.via
    with pytest.raises(ValueError):
        grounded_answer({"answered": True, "general": True, "sources": []}, entries)


@pytest.mark.parametrize(
    "text,ok",
    [
        ("Debug Info is not in the three-dot menu.", True),  # live: "three" is not a quantity
        ("The video is the one labelled Production.", True),
        ("Safety is L1 dimension 4 with L2 concepts 4.1 to 4.3.", True),  # parent of 4.1
        ("Wait three days before exporting.", False),  # a spelled-out quantity
        ("Use 7 nudges at most.", False),
    ],
)
def test_number_check_targets_quantities_not_words(text, ok):
    from gab_faq.grounding import unsupported_numbers

    facts = "Safety: L2 concepts 4.1 to 4.3. Open the menu and pick Debug Info. Phase 6.1"
    assert (not unsupported_numbers(text, facts)) is ok


@pytest.mark.parametrize(
    "text,flagged",
    [
        ("No, you do not need to record your screen for Phase 6.1.", False),  # live false positive
        ("You don't need to record anything.", False),
        ("You must record your screen and upload the video.", True),
        ("Recording is mandatory for this phase.", True),
    ],
)
def test_recording_contradiction_understands_negation(text, flagged):
    from gab_faq.grounding import _requires_recording

    assert _requires_recording(text) is flagged
