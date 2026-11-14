"""Durable model quotas and bounded prompt settings, independent of transport."""

from __future__ import annotations

import contextvars
import math
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, fields
from pathlib import Path

USER_KEY = contextvars.ContextVar("faq_model_user", default="local")


@dataclass(frozen=True)
class ModelLimits:
    questions_per_day: int = 20
    questions_per_minute: int = 3
    max_answer_chars: int = 6000
    max_question_chars: int = 1500
    max_history_message_chars: int = 400

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"model_limits.{item.name} must be a positive integer")

    @classmethod
    def parse(cls, values=None):
        values = {} if values is None else values
        if not isinstance(values, dict):
            raise ValueError("model_limits must be a mapping")
        unknown = set(values) - {item.name for item in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown model_limits settings: {sorted(unknown)}")
        return cls(**values)


class QuotaExceeded(Exception):
    pass


class ModelQuota:
    """Reserve attempts atomically across threads, channels, workers and restarts.

    Failed provider attempts count too, so repeatedly retrying an error cannot
    bypass the cap. No message content, credentials or names are stored here.
    """

    def __init__(self, path: Path, limits: ModelLimits, clock=time.time):
        self.path, self.limits, self.clock = Path(path), limits, clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS model_attempts "
                "(user_key TEXT NOT NULL, started REAL NOT NULL)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS model_attempts_user_time "
                "ON model_attempts(user_key, started)"
            )

    def reserve(self, user_key: str) -> None:
        now = self.clock()
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM model_attempts WHERE started <= ?", (now - 86400,))
            times = [
                row[0]
                for row in db.execute(
                    "SELECT started FROM model_attempts WHERE user_key = ? ORDER BY started",
                    (user_key,),
                )
            ]
            if len(times) >= self.limits.questions_per_day:
                hours = max(1, math.ceil((times[0] + 86400 - now) / 3600))
                raise QuotaExceeded(
                    f"You've reached the {self.limits.questions_per_day}-question FAQ limit "
                    f"for 24 hours. Try again in about {hours} hour(s), or contact the team."
                )
            recent = [stamp for stamp in times if stamp > now - 60]
            if len(recent) >= self.limits.questions_per_minute:
                seconds = max(1, math.ceil(recent[0] + 60 - now))
                raise QuotaExceeded(f"Please wait {seconds} second(s) before another FAQ question.")
            db.execute("INSERT INTO model_attempts VALUES (?, ?)", (user_key, now))


def answer_as_user(engine, user_key: str, question: str, role="unknown", history=None):
    """Bind identity inside the actual worker thread, without changing engine contracts."""
    token = USER_KEY.set(user_key)
    try:
        return engine.answer(question, role, history)
    finally:
        USER_KEY.reset(token)
