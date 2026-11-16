import socket
from dataclasses import replace

import pytest

from gab_faq.backups import backup, restore
from gab_faq.config import load_settings
from gab_faq.contracts import Answer
from gab_faq.engine import build_engine
from gab_faq.guard import GuardedEngine
from gab_faq.knowledge import KnowledgeBase
from gab_faq.model_limits import ModelLimits, ModelQuota, QuotaExceeded, answer_as_user
from gab_faq.routing import SupportSettings
from gab_faq.search import FaqSearch


def test_real_faq_lookup_runs_with_network_disabled(tmp_path, monkeypatch):
    settings = replace(load_settings(), engine="search", log_dir=tmp_path)
    if not any(settings.search.cache_dir.glob("**/*.onnx")):
        pytest.skip("local embedding weights not cached")

    def denied(*args, **kwargs):
        raise AssertionError("FAQ answering attempted a network connection")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    engine = build_engine(settings, KnowledgeBase(settings.knowledge_dir))
    assert isinstance(engine.inner, FaqSearch) and engine.inner.embedder is not None
    answer = answer_as_user(
        engine, "discord:offline-test", "Which model is Product A?", "annotator"
    )
    assert answer.outcome == "answered" and "flash_1p_old_test_arm" in answer.text
    unknown = answer_as_user(engine, "discord:offline-test", "What is the capital of France?")
    assert unknown.needs_escalation


def test_history_and_predefined_reply_size_are_bounded():
    class Recorder:
        def answer(self, question, role, history):
            assert len(history) <= 4
            assert all(len(m["content"]) <= 400 for m in history)
            assert "SYNTHETIC" not in str(history)
            return Answer("x" * 6001, "answered", ["A1"])

    guard = GuardedEngine(Recorder(), SupportSettings())
    history = [
        {"role": r, "content": "password: SYNTHETIC " + "x" * 2000}
        for r in ["user", "assistant"] * 10
    ]
    answer = guard.answer("Which model?", history=history)
    assert answer.needs_escalation and len(answer.text) < 6000
    assert "xxx" not in answer.text
    assert guard.answer("x" * 1501).outcome == "limited"


def test_quota_survives_backup_restore(tmp_path):
    limits = replace(ModelLimits(), questions_per_day=1)
    source = tmp_path / "source"
    quota = ModelQuota(source / "model_usage.sqlite3", limits)
    quota.reserve("discord:1")
    snapshot = backup(source, tmp_path / "snapshot")
    destination = tmp_path / "restored"
    restore(snapshot, destination)
    restored = ModelQuota(destination / "model_usage.sqlite3", limits)
    with pytest.raises(QuotaExceeded):
        restored.reserve("discord:1")
