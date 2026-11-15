import json
import ssl
from dataclasses import replace

import httpx
import pytest

from gab_faq.config import Settings, load_settings
from gab_faq.engine import build_engine
from gab_faq.knowledge import KnowledgeBase
from gab_faq.model_context import bounded_history, request_bytes
from gab_faq.model_limits import ModelLimits, answer_as_user
from gab_faq.qwen import ENDPOINT, MODEL, Qwen

from .conftest import ROOT


def fake_client(selection=None, *, finish="stop", status=200, extra_delta=None, raw=None):
    requests = []
    selection = selection if selection is not None else {"outcome": "answered", "sources": ["A1"]}
    text = json.dumps(selection)
    events = [
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]},
        {"choices": [{"index": 0, "delta": {"content": text[:15]}}]},
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": text[15:], **(extra_delta or {})},
                    "finish_reason": finish,
                }
            ]
        },
        {"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 25}},
    ]
    content = (
        raw
        if raw is not None
        else "\n\n".join("data: " + json.dumps(event) for event in events) + "\n\ndata: [DONE]\n\n"
    )

    def respond(request):
        requests.append(request)
        return httpx.Response(
            status,
            content=content,
            headers={"Content-Type": "text/event-stream", "Location": "https://untrusted.invalid"},
        )

    return httpx.Client(transport=httpx.MockTransport(respond)), requests


@pytest.fixture(autouse=True)
def synthetic_key(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "SYNTHETIC_ALIBABA_KEY")


def test_streamed_selection_publishes_only_approved_faq(knowledge):
    client, requests = fake_client()
    with client:
        answer = Qwen(knowledge, client=client).answer("Which model is Product A?", "annotator")
    assert answer.outcome == "answered" and answer.sources == ["A1"]
    assert "flash_dte_test_arm" in answer.text
    assert str(requests[0].url) == ENDPOINT
    payload = json.loads(requests[0].content)
    assert payload["model"] == MODEL
    assert payload["enable_thinking"] is False
    assert payload["modalities"] == ["text"] and payload["stream"] is True
    assert payload["max_tokens"] == 256
    assert "response_format" not in payload  # Omni Flash does not support structured output mode.
    assert not {"tools", "tool_choice", "functions", "function_call", "mcp_servers"} & set(payload)
    assert "SYNTHETIC_ALIBABA_KEY" not in requests[0].content.decode()
    assert len(requests[0].content) <= 8000


@pytest.mark.parametrize("status", [200, 503])
def test_default_client_verifies_tls_and_closes_after_request(knowledge, monkeypatch, status):
    client, requests = fake_client(status=status)

    def default_client(*, verify):
        assert isinstance(verify, ssl.SSLContext)
        assert verify.check_hostname
        assert verify.verify_mode == ssl.CERT_REQUIRED
        return client

    monkeypatch.setattr(httpx, "Client", default_client)
    answer = Qwen(knowledge).answer("Which model is Product A?", "annotator")
    assert client.is_closed and len(requests) == 1
    assert answer.outcome == ("answered" if status == 200 else "error")


def test_related_video_is_rendered_from_catalog(knowledge):
    client, requests = fake_client({"outcome": "answered", "sources": ["PG6"]})
    with client:
        answer = Qwen(knowledge, client=client).answer("Where is the reset playground video?")
    assert answer.outcome == "answered"
    assert "1BZoB5sg995F931r7RnxskYe81esTNuqf" in answer.text
    assert "Reset ID" in answer.text
    assert "1BZoB5sg995F931r7RnxskYe81esTNuqf" not in requests[0].content.decode()


@pytest.mark.parametrize(
    "selection",
    [
        {"outcome": "answered", "sources": ["FAKE99"]},
        {"outcome": "answered", "sources": [None]},
        {"outcome": "answered", "sources": []},
        {"outcome": "answered", "sources": "A1"},
        {"outcome": "answered", "sources": ["A1"] * 4},
        {
            "outcome": "answered",
            "sources": ["A1"],
            "answer": "I reset your account and approved payment.",
        },
        {"outcome": "limited", "sources": ["A1"]},
    ],
)
def test_invalid_or_invented_provider_content_is_not_published(knowledge, selection):
    client, requests = fake_client(selection)
    with client:
        answer = Qwen(knowledge, client=client).answer("Which model is Product A?")
    assert answer.needs_escalation and len(requests) == 1
    assert "approved payment" not in answer.text and "flash_dte_test_arm" not in answer.text


@pytest.mark.parametrize("outcome", ["not_in_faq", "needs_human"])
def test_provider_unknown_or_human_request_escalates(knowledge, outcome):
    client, _ = fake_client({"outcome": outcome, "sources": []})
    with client:
        answer = Qwen(knowledge, client=client).answer("My individual task is blocked")
    assert answer.outcome == outcome and answer.needs_escalation


@pytest.mark.parametrize("status", [302, 401, 429, 503])
def test_error_and_redirect_are_not_retried(knowledge, status):
    client, requests = fake_client(status=status)
    with client:
        answer = Qwen(knowledge, client=client).answer("Which model is Product A?")
    assert answer.needs_escalation and len(requests) == 1
    assert str(requests[0].url) == ENDPOINT


@pytest.mark.parametrize(
    "finish,delta",
    [
        ("length", None),
        (None, None),
        ("stop", {"tool_calls": [{"id": "bad"}]}),
        ("stop", {"reasoning_content": "unexpected thinking"}),
        ("stop", {"audio": {"data": "bad"}}),
    ],
)
def test_incomplete_or_non_text_output_is_rejected(knowledge, finish, delta):
    client, requests = fake_client(finish=finish, extra_delta=delta)
    with client:
        answer = Qwen(knowledge, client=client).answer("Which model is Product A?")
    assert answer.needs_escalation and len(requests) == 1


def test_missing_key_never_reuses_another_provider_key(knowledge, monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "SYNTHETIC_OLD_PROVIDER")
    client, requests = fake_client()
    with client:
        answer = Qwen(knowledge, client=client).answer("Which model?")
    assert answer.needs_escalation and not requests
    assert "SYNTHETIC_" not in answer.text


def test_question_and_history_are_scrubbed_and_bounded(knowledge):
    history = [
        {"role": role, "content": "password: SYNTHETIC_HISTORY " + "x" * 1000}
        for role in ["user", "assistant"] * 10
    ]
    request, entries = Qwen(knowledge).build_request(
        "Which model? api_key: SYNTHETIC_QUESTION", history=history
    )
    serialized = request_bytes(request)
    assert b"SYNTHETIC_" not in serialized
    assert len(serialized) <= 8000 and len(request["messages"]) <= 6
    assert all(len(m["content"]) <= 400 for m in request["messages"][1:-1])
    assert entries


def test_adjacent_history_messages_do_not_bypass_length_cap():
    history = [{"role": "user", "content": "x" * 400}] * 3 + [
        {"role": "assistant", "content": "ok"}
    ]
    result = bounded_history(history, 4, ModelLimits())
    assert max(len(message["content"]) for message in result) <= 400


def test_long_question_stops_before_network(knowledge):
    client, requests = fake_client()
    with client:
        answer = Qwen(knowledge, client=client).answer("x" * 1501)
    assert answer.outcome == "limited" and not requests


def test_internal_faq_and_sections_are_excluded_for_public_role(tmp_path):
    (tmp_path / "public.md").write_text(
        "---\naudience: all\n---\n## Shared\nA1. Reset?\nPublic answer.\n## Internal\n<!-- audience: qm -->\nQM2. Reset?\nPRIVATE_SECTION_SENTINEL\n"
    )
    (tmp_path / "internal.md").write_text(
        "---\naudience: qm\n---\nQM1. Reset?\nPRIVATE_DOCUMENT_SENTINEL\n"
    )
    knowledge = KnowledgeBase(tmp_path)
    client, requests = fake_client({"outcome": "answered", "sources": ["QM1"]})
    with client:
        answer = Qwen(knowledge, client=client).answer("Reset?", "annotator")
    assert b"PRIVATE_" not in requests[0].content
    assert answer.needs_escalation and "PRIVATE_" not in answer.text
    request, _ = Qwen(knowledge).build_request("Reset?", "qm")
    assert b"PRIVATE_DOCUMENT_SENTINEL" in request_bytes(request)
    assert b"PRIVATE_SECTION_SENTINEL" in request_bytes(request)


def test_qwen_uses_persistent_user_quota_before_network(knowledge, tmp_path):
    client, requests = fake_client()
    settings = replace(
        load_settings(), log_dir=tmp_path, model_limits=replace(ModelLimits(), questions_per_day=1)
    )
    engine = build_engine(settings, knowledge)
    engine.inner.client = client
    with client:
        assert (
            answer_as_user(engine, "discord:42", "Which model is Product A?").outcome == "answered"
        )
        assert (
            answer_as_user(engine, "discord:42", "Which model is Product A?").outcome == "limited"
        )
    assert len(requests) == 1


def test_qwen_settings_do_not_store_api_key(monkeypatch):
    settings = load_settings(ROOT / "config.yaml")
    assert settings.engine == "qwen" and settings.dashscope_api_key_set
    assert "SYNTHETIC_ALIBABA_KEY" not in repr(settings)
    assert Settings().engine == "qwen"
    assert Settings().model == MODEL
