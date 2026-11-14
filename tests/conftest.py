import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gab_faq.knowledge import KnowledgeBase  # noqa: E402


class FakeMessages:
    """Stands in for client.beta.messages so unit tests never call the real API."""

    def __init__(self, reply=None, error=None, stop_reason="end_turn", raw_text=None):
        self.reply = reply or {
            "answer": "ok",
            "outcome": "answered",
            "sources": [],
            "escalation_reason": "",
        }
        self.error = error
        self.stop_reason = stop_reason
        self.raw_text = raw_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        text = self.raw_text if self.raw_text is not None else json.dumps(self.reply)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=text),
            ],
            _request_id="req_test",
        )


class FakeClient:
    def __init__(self, **kwargs):
        self.beta = SimpleNamespace(messages=FakeMessages(**kwargs))

    @property
    def calls(self):
        return self.beta.messages.calls


@pytest.fixture
def knowledge():
    return KnowledgeBase(ROOT / "knowledge" / "current")


@pytest.fixture
def fake_client_factory():
    return FakeClient
