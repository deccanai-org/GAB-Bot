"""Regression coverage for thinking streams and the reported introductory questions."""

import json
from dataclasses import replace

import pytest

from gab_faq.config import Settings, load_settings
from gab_faq.engine import build_engine
from gab_faq.guard import GuardedEngine
from gab_faq.model_limits import ModelLimits, ModelQuota
from gab_faq.qwen import MAX_REASONING_BYTES, Qwen
from gab_faq.routing import SupportSettings

from .conftest import ROOT
from .test_qwen import fake_client


@pytest.mark.parametrize("reasoning", ["", "Private reasoning: inspect the supplied sources."])
def test_thinking_stream_publishes_only_final_answer(knowledge, monkeypatch, caplog, reasoning):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "SYNTHETIC_ALIBABA_KEY")
    monkeypatch.setenv("GAB_LOG_MODEL_OUTPUT", "1")
    client, requests = fake_client(extra_delta={"reasoning_content": reasoning})
    with client:
        answer = Qwen(
            knowledge,
            client=client,
            enable_thinking=True,
            external_questions_approved=True,
            local_answers=False,
        ).answer("Which model is Product A?", "annotator")
    assert answer.outcome == "answered" and answer.sources == ["A1"]
    assert json.loads(requests[0].content)["enable_thinking"] is True
    if reasoning:
        assert reasoning not in answer.text and reasoning not in caplog.text


def test_reasoning_only_stream_is_not_an_answer(knowledge, monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "SYNTHETIC_ALIBABA_KEY")
    events = [
        {"choices": [{"delta": {"reasoning_content": "Private reasoning"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    ]
    raw = "\n\n".join("data: " + json.dumps(e) for e in events) + "\n\ndata: [DONE]\n\n"
    client, _ = fake_client(raw=raw)
    with client:
        answer = Qwen(
            knowledge,
            client=client,
            enable_thinking=True,
            external_questions_approved=True,
            local_answers=False,
        ).answer("Which model is Product A?", "annotator")
    assert answer.outcome == "error" and "Private reasoning" not in answer.text


@pytest.mark.parametrize("reasoning", [123, {"content": "bad"}, "x" * (MAX_REASONING_BYTES + 1)])
def test_invalid_or_unbounded_reasoning_is_rejected(knowledge, monkeypatch, reasoning):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "SYNTHETIC_ALIBABA_KEY")
    client, _ = fake_client(extra_delta={"reasoning_content": reasoning})
    with client:
        answer = Qwen(
            knowledge,
            client=client,
            enable_thinking=True,
            external_questions_approved=True,
            local_answers=False,
        ).answer("Which model is Product A?", "annotator")
    assert answer.outcome == "error"


def test_project_config_enables_thinking_in_engine(knowledge, tmp_path):
    settings = replace(load_settings(ROOT / "config.yaml"), log_dir=tmp_path)
    engine = build_engine(settings, knowledge)
    request, _ = engine.inner.build_request("Which model is Product A?", "annotator")
    assert settings.enable_thinking and request["enable_thinking"] is True
    assert request["max_tokens"] == 1024


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_thinking_config_must_be_boolean(value):
    with pytest.raises(ValueError, match="enable_thinking"):
        Settings(enable_thinking=value)


@pytest.mark.parametrize("question", ["what are you", "who are you?", "what can you do?"])
def test_bot_identity_is_local_even_when_user_quota_is_full(knowledge, tmp_path, question):
    limits = replace(ModelLimits(), questions_per_day=1, questions_per_minute=1)
    quota = ModelQuota(tmp_path / "quota.sqlite3", limits)
    quota.reserve("local")
    engine = GuardedEngine(Qwen(knowledge), SupportSettings(), quota=quota, limits=limits)
    answer = engine.answer(question)
    assert answer.outcome == "small_talk" and "Gigi" in answer.text
    assert not answer.needs_escalation and not answer.route


@pytest.mark.parametrize("question", ["what is gab", "What's GAB?", "what is project GAB?"])
def test_project_intro_uses_current_approved_faq_without_provider(knowledge, monkeypatch, question):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    answer = Qwen(knowledge).answer(question, "annotator")
    assert answer.outcome == "answered" and answer.sources == ["U1"]
    assert "Conversation Generation" in answer.text and "flash_1p_old_test_arm" in answer.text
    assert not answer.needs_escalation


def test_broader_questions_are_not_swallowed_by_intro(knowledge):
    from gab_faq.introduction import introduction

    assert introduction("What is GAB's payment policy?", knowledge) is None
    assert introduction("What are you going to do about my reset?", knowledge) is None
