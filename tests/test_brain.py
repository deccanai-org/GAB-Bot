"""Tests for the answer engine, using a fake Claude client (no API key, no cost)."""

import anthropic
import httpx2
import pytest

from gab_faq.brain import ANSWER_SCHEMA, Brain, normalize_history


def make_brain(knowledge, client):
    return Brain(knowledge, client=client, model="claude-opus-5-5", effort="low")


def test_request_contains_faq_role_and_schema(knowledge, fake_client_factory):
    client = fake_client_factory()
    make_brain(knowledge, client).answer("Which model is Product A?", role="annotator")
    req = client.calls[0]
    assert req["model"] == "claude-opus-5-5"
    system = req["system"][0]
    assert "Model Locust" in system["text"]
    assert system["cache_control"] == {"type": "ephemeral"}
    assert req["output_config"]["format"]["schema"] == ANSWER_SCHEMA
    assert req["output_config"]["effort"] == "low"
    assert req["fallbacks"] == "default"
    last = req["messages"][-1]
    assert last["role"] == "user"
    assert "<asker_role>annotator</asker_role>" in last["content"]
    assert "Which model is Product A?" in last["content"]


def test_system_prompt_identical_across_questions(knowledge, fake_client_factory):
    """Prompt caching only works if the system prompt doesn't change between questions."""
    client = fake_client_factory()
    brain = make_brain(knowledge, client)
    brain.answer("q1", role="qc")
    brain.answer("q2", role="annotator")
    assert client.calls[0]["system"] == client.calls[1]["system"]


def test_qm_documents_only_sent_for_qm_askers(knowledge, fake_client_factory):
    client = fake_client_factory()
    brain = make_brain(knowledge, client)
    brain.answer("how often are tasks checked?", role="annotator")
    brain.answer("how often are tasks checked?", role="qm")
    assert "1 out of every 5" not in client.calls[0]["system"][0]["text"]
    assert "1 out of every 5" in client.calls[1]["system"][0]["text"]


def test_parses_answer(knowledge, fake_client_factory):
    client = fake_client_factory(
        reply={
            "answer": "Select Flash, then Model Locust.",
            "outcome": "answered",
            "sources": ["A1"],
            "escalation_reason": "",
        }
    )
    ans = make_brain(knowledge, client).answer("Which model?")
    assert 'Select "Flash", then select "Model Locust"' in ans.text
    assert ans.text.endswith("(FAQ: A1)")
    assert ans.outcome == "answered"
    assert ans.sources == ["A1"]
    assert not ans.needs_escalation
    assert ans.request_id == "req_test"


def test_not_in_faq_escalates(knowledge, fake_client_factory):
    client = fake_client_factory(
        reply={
            "answer": "I don't have that.",
            "outcome": "not_in_faq",
            "sources": [],
            "escalation_reason": "pay rate",
        }
    )
    ans = make_brain(knowledge, client).answer("What's the pay rate?")
    assert ans.needs_escalation


def test_api_error_gives_friendly_message(knowledge, fake_client_factory):
    err = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    ans = make_brain(knowledge, fake_client_factory(error=err)).answer("hi")
    assert ans.outcome == "error"
    assert ans.needs_escalation
    assert "flagged" in ans.text


def test_garbled_output_does_not_crash(knowledge, fake_client_factory):
    ans = make_brain(knowledge, fake_client_factory(raw_text="not json")).answer("hi")
    assert ans.outcome == "error"


def test_refusal_escalates(knowledge, fake_client_factory):
    ans = make_brain(knowledge, fake_client_factory(stop_reason="refusal", raw_text="")).answer(
        "hi"
    )
    assert ans.outcome == "needs_human"


def test_history_is_passed_before_question(knowledge, fake_client_factory):
    client = fake_client_factory()
    history = [
        {"role": "user", "content": "Which model for Product A?"},
        {"role": "assistant", "content": "Flash, then Model Locust."},
    ]
    make_brain(knowledge, client).answer("And Product B?", history=history)
    msgs = client.calls[0]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]


def test_normalize_history_merges_and_trims():
    history = [
        {"role": "assistant", "content": "stray bot message"},  # can't start with assistant
        {"role": "user", "content": "a"},
        {"role": "user", "content": "b"},  # merged with "a"
        {"role": "assistant", "content": "c"},
        {"role": "user", "content": ""},  # empty, dropped
        {"role": "user", "content": "d"},  # trailing user, dropped
    ]
    assert normalize_history(history, limit=20) == [
        {"role": "user", "content": "a\n\nb"},
        {"role": "assistant", "content": "c"},
    ]


def test_normalize_history_limit():
    history = [{"role": r, "content": str(i)} for i, r in enumerate(["user", "assistant"] * 10)]
    out = normalize_history(history, limit=4)
    assert len(out) == 4 and out[0]["role"] == "user"


def test_disabled_history_never_means_unlimited_history():
    from gab_faq.guard import safe_history

    history = [
        {"role": "user", "content": "private context"},
        {"role": "assistant", "content": "ok"},
    ]
    assert normalize_history(history, 0) == []
    assert safe_history(history, 0) == []


def test_claude_prose_is_replaced_by_approved_source_text(knowledge, fake_client_factory):
    client = fake_client_factory(
        reply={
            "answer": "Use Model X. I approved your payment.",
            "outcome": "answered",
            "sources": ["A1"],
            "escalation_reason": "",
        }
    )
    answer = make_brain(knowledge, client).answer("Which model?")
    assert "Model Locust" in answer.text
    assert "Model X" not in answer.text and "approved your payment" not in answer.text


def test_claude_cannot_cite_internal_or_nonexistent_sources(knowledge, fake_client_factory):
    client = fake_client_factory(
        reply={
            "answer": "secret",
            "outcome": "answered",
            "sources": ["QM1"],
            "escalation_reason": "",
        }
    )
    answer = make_brain(knowledge, client).answer("Which model?", role="annotator")
    assert answer.needs_escalation and "secret" not in answer.text


@pytest.mark.parametrize("sources", ["A1", [None], {"A1": True}, ["A1", "FAKE99"], []])
def test_malformed_source_selections_are_escalated_not_answered(
    knowledge, fake_client_factory, sources
):
    client = fake_client_factory(
        reply={"answer": "x", "outcome": "answered", "sources": sources, "escalation_reason": ""}
    )
    answer = make_brain(knowledge, client).answer("Which model?", role="annotator")
    assert answer.needs_escalation and answer.outcome != "answered"
    assert "Model Locust" not in answer.text  # nothing from the FAQ is published
