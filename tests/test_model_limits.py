from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from gab_faq.contracts import Answer
from gab_faq.guard import GuardedEngine
from gab_faq.model_limits import USER_KEY, ModelLimits, ModelQuota, QuotaExceeded, answer_as_user
from gab_faq.routing import SupportSettings


class CountingEngine:
    def __init__(self):
        self.calls = []

    def answer(self, question, role="unknown", history=None):
        self.calls.append(USER_KEY.get())
        return Answer("Approved FAQ text", "answered", ["A1"])


def test_daily_cap_persists_and_is_independent_per_user(tmp_path):
    now = [100000.0]
    limits = replace(ModelLimits(), questions_per_day=2, questions_per_minute=10)
    path = tmp_path / "usage.sqlite3"
    quota = ModelQuota(path, limits, clock=lambda: now[0])
    quota.reserve("discord:1")
    quota.reserve("discord:1")
    restarted = ModelQuota(path, limits, clock=lambda: now[0])
    with pytest.raises(QuotaExceeded, match="24 hours"):
        restarted.reserve("discord:1")
    restarted.reserve("discord:2")
    now[0] += 86400
    restarted.reserve("discord:1")


def test_minute_window_does_not_reset_the_daily_cap(tmp_path):
    now = [100000.0]
    limits = replace(ModelLimits(), questions_per_day=2, questions_per_minute=1)
    quota = ModelQuota(tmp_path / "usage.sqlite3", limits, clock=lambda: now[0])
    quota.reserve("user")
    with pytest.raises(QuotaExceeded, match="second"):
        quota.reserve("user")
    now[0] += 60
    quota.reserve("user")
    now[0] += 60
    with pytest.raises(QuotaExceeded, match="24 hours"):
        quota.reserve("user")


def test_concurrent_workers_cannot_exceed_user_quota(tmp_path):
    limits = replace(ModelLimits(), questions_per_day=3, questions_per_minute=3)
    path = tmp_path / "usage.sqlite3"
    first, second = ModelQuota(path, limits), ModelQuota(path, limits)

    def attempt(number):
        try:
            (first if number % 2 else second).reserve("same-user")
            return True
        except QuotaExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(20))) == 3


def test_quota_rejects_before_model_and_does_not_escalate(tmp_path):
    limits = replace(ModelLimits(), questions_per_day=1)
    engine = CountingEngine()
    guard = GuardedEngine(engine, SupportSettings(), quota=ModelQuota(tmp_path / "q.db", limits))
    assert answer_as_user(guard, "discord:1", "Which model?").outcome == "answered"
    blocked = answer_as_user(guard, "discord:1", "Which model?")
    assert blocked.outcome == "limited" and not blocked.needs_escalation
    assert engine.calls == ["discord:1"]
    assert USER_KEY.get() == "local"


def test_greetings_actions_and_payments_use_no_model_quota(tmp_path):
    engine = CountingEngine()
    guard = GuardedEngine(
        engine, SupportSettings(), quota=ModelQuota(tmp_path / "q.db", ModelLimits())
    )
    assert answer_as_user(guard, "u", "hello").outcome == "small_talk"
    assert answer_as_user(guard, "u", "please reset my environment").needs_escalation
    assert answer_as_user(guard, "u", "when is my payment?").needs_escalation
    assert not engine.calls


def test_failed_attempts_cannot_be_retried_past_cap(tmp_path):
    class Failing:
        def answer(self, *args):
            raise RuntimeError("synthetic failure")

    quota = ModelQuota(tmp_path / "q.db", replace(ModelLimits(), questions_per_day=1))
    guard = GuardedEngine(Failing(), SupportSettings(), quota=quota)
    with pytest.raises(RuntimeError):
        answer_as_user(guard, "user", "Which model?")
    assert USER_KEY.get() == "local"
    assert answer_as_user(guard, "user", "Which model?").outcome == "limited"


@pytest.mark.parametrize(
    "values",
    [
        {"questions_per_day": 0},
        {"questions_per_day": True},
        {"max_prompt_bytes": 10},
        {"max_output_tokens": 10000},
        {"provider_requests_per_minute": 0},
        {"provider_requests_per_minute": 601},
        {"unknown": 1},
    ],
)
def test_invalid_model_limits_rejected(values):
    with pytest.raises(ValueError):
        ModelLimits.parse(values)
