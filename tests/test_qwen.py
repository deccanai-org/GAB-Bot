import json
import ssl
from dataclasses import replace

import httpx
import pytest

from gab_faq.config import Settings, load_settings
from gab_faq.contracts import Answer
from gab_faq.engine import build_engine
from gab_faq.knowledge import KnowledgeBase
from gab_faq.model_context import bounded_history, request_bytes
from gab_faq.model_limits import PROVIDER_BUSY, ModelLimits, answer_as_user
from gab_faq.qwen import ENDPOINT, MODEL, ProviderGate
from gab_faq.qwen import Qwen as BotQwen

from .conftest import ROOT


def Qwen(*args, **kwargs):
    """Protocol tests explicitly approve their synthetic requests and disable local shortcuts."""
    kwargs.setdefault("external_questions_approved", True)
    kwargs.setdefault("external_history_approved", True)
    kwargs.setdefault("local_answers", False)
    kwargs.setdefault("limits", replace(ModelLimits(), provider_max_retries=0))
    return BotQwen(*args, **kwargs)


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
    assert payload["max_tokens"] == 300
    assert payload["temperature"] == 0
    assert "[for annotators;" in payload["messages"][0]["content"]
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
    assert "Phase 6.2" in answer.text  # PG6 now says no Reset is needed in 6.2
    assert "1BZoB5sg995F931r7RnxskYe81esTNuqf" not in requests[0].content.decode()


@pytest.mark.parametrize(
    "selection",
    [
        {"outcome": "answered", "sources": ["FAKE99"]},
        {"outcome": "answered", "sources": [None]},
        {"outcome": "answered", "sources": []},
        {"outcome": "answered", "sources": "A1"},
        {"outcome": "limited", "sources": ["A1"]},
    ],
)
def test_invalid_or_invented_provider_content_is_not_published(knowledge, selection):
    client, requests = fake_client(selection)
    with client:
        answer = Qwen(knowledge, client=client).answer("Which model is Product A?")
    assert answer.needs_escalation and len(requests) == 1
    assert "flash_dte_test_arm" not in answer.text


def test_claimed_action_wording_is_dropped_for_the_approved_entry(knowledge):
    # Valid source, unacceptable wording: the wording is never published; the approved entry is.
    selection = {
        "outcome": "answered",
        "sources": ["A1"],
        "answer": "I reset your account and approved payment.",
    }
    client, requests = fake_client(selection)
    with client:
        answer = Qwen(knowledge, client=client).answer("Which model is Product A?")
    assert answer.outcome == "answered" and "explanation rejected" in answer.via
    assert "approved payment" not in answer.text and "flash_dte_test_arm" in answer.text


def test_extra_duplicate_and_unavailable_ids_reject_the_whole_selection(knowledge):
    question = "Which model is Product B?"
    _, entries = Qwen(knowledge).build_request(question, "annotator")
    supplied = [entry.id for entry in entries]
    # Qwen listed one entry twice, invented two IDs and gave five real ones: keep the first three.
    selection = [supplied[0], supplied[0], "FAKE99", None, *supplied[1:5]]
    client, requests = fake_client({"outcome": "answered", "sources": selection})
    with client:
        answer = Qwen(knowledge, client=client).answer(question, "annotator")
    assert answer.outcome == "error" and not answer.sources
    assert "FAKE99" not in answer.text and len(requests) == 1


@pytest.mark.parametrize(
    "selection,outcome,via",
    [
        # Seen live: Qwen omits "sources" on non-answers. Unambiguous, so it means no sources.
        ({"outcome": "needs_human"}, "needs_human", "qwen"),
        ({"outcome": "not_in_faq"}, "needs_human", "retrieval: unavailable"),
        # An explanation must still name its sources.
        ({"outcome": "answered", "answer": "Use the flash model."}, "error", "qwen"),
    ],
)
def test_missing_sources_key_only_allowed_for_non_answers(knowledge, selection, outcome, via):
    client, _ = fake_client(selection)
    with client:
        answer = Qwen(knowledge, client=client).answer("My individual GAB task is blocked")
    assert answer.outcome == outcome and answer.needs_escalation and answer.via == via


@pytest.mark.parametrize("outcome", ["not_in_faq", "needs_human"])
def test_provider_unknown_or_human_request_escalates(knowledge, outcome):
    client, _ = fake_client({"outcome": outcome, "sources": []})
    with client:
        answer = Qwen(knowledge, client=client).answer("My individual task is blocked")
    assert answer.outcome == "needs_human" and answer.needs_escalation


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
        "Which model is Product A? api_key: SYNTHETIC_QUESTION", history=history
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
        "---\naudience: all\nexternal_processing_approved: true\n---\n## Shared\nA1. Reset?\nPublic answer.\n## Internal\n<!-- audience: qm -->\nQM2. Reset?\nPRIVATE_SECTION_SENTINEL\n"
    )
    (tmp_path / "internal.md").write_text(
        "---\naudience: qm\nexternal_processing_approved: true\n---\nQM1. Reset?\nPRIVATE_DOCUMENT_SENTINEL\n"
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
    engine.inner.local_answers = False
    engine.inner.external_questions_approved = True
    engine.inner.client = client
    with client:
        assert (
            answer_as_user(engine, "discord:42", "Which model is Product A?").outcome == "answered"
        )
        assert (
            answer_as_user(engine, "discord:42", "Which model is Product A?").outcome == "limited"
        )
    assert len(requests) == 1


class StubSearch:
    """Stands in for FaqSearch: a fixed local result, and a call counter."""

    def __init__(self, outcome="answered", embedder=object()):
        self.outcome, self.embedder, self.calls = outcome, embedder, 0

    def answer(self, question, role="unknown", history=None):
        self.calls += 1
        return Answer("LOCAL FAQ TEXT", self.outcome, ["A1"], via="search")


@pytest.mark.parametrize("declined", [{"outcome": "not_in_faq", "sources": []}, None])
def test_declined_or_failed_selection_cannot_be_overridden_by_an_unrelated_backstop(
    knowledge, declined
):
    # None: the provider fails (503) instead of declining.
    client, requests = fake_client(declined, status=200 if declined else 503)
    search = StubSearch("answered")
    with client:
        answer = Qwen(knowledge, client=client, backstop=search).answer(
            "Which model should I use for the GAB task?", "annotator"
        )
    assert answer.outcome in {"needs_human", "error"} and answer.text != "LOCAL FAQ TEXT"
    assert search.calls == 0 and len(requests) == (2 if declined else 1)


@pytest.mark.parametrize(
    "selection,local",
    [
        (
            {"outcome": "not_in_faq", "sources": []},
            "partial",
        ),  # unsure local match: keep escalation
        ({"outcome": "not_in_faq", "sources": []}, "not_in_faq"),
        (
            {"outcome": "needs_human", "sources": []},
            "answered",
        ),  # a person is needed: never replaced
        ({"outcome": "answered", "sources": ["A1"]}, "answered"),  # Qwen's own answer stands
    ],
)
def test_local_backstop_only_replaces_a_confident_match_for_a_decline(knowledge, selection, local):
    client, _ = fake_client(selection)
    search = StubSearch(local)
    with client:
        answer = Qwen(knowledge, client=client, backstop=search).answer(
            "Which model should I use for the GAB task?", "annotator"
        )
    assert answer.text != "LOCAL FAQ TEXT"
    assert search.calls == 0


def test_local_backstop_needs_its_embedding_model(knowledge):
    client, _ = fake_client({"outcome": "not_in_faq", "sources": []})
    search = StubSearch("answered", embedder=None)  # keyword-only scores are not calibrated
    with client:
        answer = Qwen(knowledge, client=client, backstop=search).answer(
            "Which model should I use for the GAB task?", "annotator"
        )
    assert answer.outcome == "needs_human" and search.calls == 0


def test_local_backstop_failure_keeps_the_qwen_result(knowledge):
    class Broken(StubSearch):
        def answer(self, *args, **kwargs):
            raise RuntimeError("index unavailable")

    client, _ = fake_client({"outcome": "not_in_faq", "sources": []})
    with client:
        answer = Qwen(knowledge, client=client, backstop=Broken()).answer(
            "Which model should I use for the GAB task?"
        )
    assert answer.outcome == "needs_human"


def test_qwen_does_not_load_an_embedding_backstop(knowledge, tmp_path):
    settings = replace(load_settings(), log_dir=tmp_path)
    assert build_engine(settings, knowledge).inner.search is None
    off = replace(settings, local_backstop=False)
    assert build_engine(off, knowledge).inner.search is None


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_provider_gate_caps_requests_per_rolling_minute():
    clock = FakeClock()
    gate = ProviderGate(2, clock=clock, sleep=clock.sleep)
    assert gate.acquire(0) and gate.acquire(0)
    assert not gate.acquire(5) and clock.now == 0  # next slot is 60 s away: no waiting
    clock.now = 59.9
    assert not gate.acquire(0)
    clock.now = 60.0
    assert gate.acquire(0)


def test_provider_gate_waits_for_a_slot_inside_the_bound():
    clock = FakeClock()
    gate = ProviderGate(1, clock=clock, sleep=clock.sleep)
    assert gate.acquire(0)
    clock.now = 55
    assert gate.acquire(10) and clock.now == 60  # the slot frees at 60: waited 5 s
    assert not gate.acquire(10)  # the next one is a full minute away


def test_full_provider_gate_turns_the_question_away_without_a_request(knowledge):
    clock = FakeClock()
    gate = ProviderGate(1, clock=clock, sleep=clock.sleep)
    assert gate.acquire(0)
    client, requests = fake_client()
    with client:
        answer = Qwen(knowledge, client=client, gate=gate).answer(
            "Which model is Product A?", "annotator"
        )
    assert answer.outcome == "limited" and answer.via == PROVIDER_BUSY
    assert not answer.needs_escalation and not requests


def test_provider_busy_does_not_use_up_the_users_daily_allowance(knowledge, tmp_path):
    clock = FakeClock()
    gate = ProviderGate(1, clock=clock, sleep=clock.sleep)
    assert gate.acquire(0)  # other traffic holds the only slot
    client, requests = fake_client()
    settings = replace(
        load_settings(), log_dir=tmp_path, model_limits=replace(ModelLimits(), questions_per_day=1)
    )
    engine = build_engine(settings, knowledge)
    engine.inner.local_answers = False
    engine.inner.external_questions_approved = True
    engine.inner.client, engine.inner.gate = client, gate
    with client:
        busy = answer_as_user(engine, "discord:42", "Which model is Product A?")
        assert busy.outcome == "limited" and busy.via == PROVIDER_BUSY and not requests
        clock.now = 61  # the slot frees up
        retry = answer_as_user(engine, "discord:42", "Which model is Product A?")
    assert retry.outcome == "answered" and len(requests) == 1


def test_qwen_settings_do_not_store_api_key(monkeypatch):
    settings = load_settings(ROOT / "config.yaml")
    assert settings.engine == "qwen" and settings.dashscope_api_key_set
    assert "SYNTHETIC_ALIBABA_KEY" not in repr(settings)
    assert Settings().engine == "qwen"
    assert Settings().model == MODEL
