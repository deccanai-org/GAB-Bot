"""Durable model quotas and bounded prompt settings, independent of transport."""

from __future__ import annotations

import contextvars
import math
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, fields
from pathlib import Path

USER_KEY = contextvars.ContextVar("faq_model_user", default="local")
# Reply provenance for a question turned away before any provider request was sent.
PROVIDER_BUSY = "qwen: provider busy"


@dataclass(frozen=True)
class ModelLimits:
    questions_per_day: int = 20
    questions_per_minute: int = 3
    max_prompt_bytes: int = 8000
    max_output_tokens: int = 300
    max_input_tokens: int = 2000
    retrieval_candidates: int = 6
    provider_tokens_per_minute: int = 90000
    provider_queue_capacity: int = 16
    provider_max_wait_seconds: int = 3
    provider_max_retries: int = 2
    provider_backoff_seconds: int = 1
    max_answer_chars: int = 6000
    max_question_chars: int = 1500
    max_history_message_chars: int = 400
    # Whole-bot cap on provider requests per rolling minute. Alibaba limits the whole account
    # (60 requests/minute for Qwen3-Omni-Flash, Singapore), so stay below it unless it is raised.
    provider_requests_per_minute: int = 50
    # Every provider request one question may cause, across the targeted retrieval retry and
    # rate-limit retries together. Bounds the cost of a single question.
    provider_calls_per_question: int = 3

    def __post_init__(self):
        for item in fields(self):
            value = getattr(self, item.name)
            minimum = 0 if item.name == "provider_max_retries" else 1
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                raise ValueError(f"model_limits.{item.name} must be a positive integer")
        if not 4000 <= self.max_prompt_bytes <= 64000:
            raise ValueError("max_prompt_bytes must be between 4000 and 64000")
        if not 64 <= self.max_output_tokens <= 1024:
            raise ValueError("max_output_tokens must be between 64 and 1024")
        if not 1 <= self.provider_requests_per_minute <= 600:
            raise ValueError("provider_requests_per_minute must be between 1 and 600")
        if self.provider_max_retries > 3 or self.provider_max_wait_seconds > 10:
            raise ValueError("Provider retries/wait exceed the bounded request deadline")
        if not 1 <= self.provider_calls_per_question <= 6:
            raise ValueError("provider_calls_per_question must be between 1 and 6")

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
            columns = {row[1] for row in db.execute("PRAGMA table_info(model_attempts)")}
            if "reservation_id" not in columns:
                db.execute("ALTER TABLE model_attempts ADD COLUMN reservation_id TEXT")

    def reserve(self, user_key: str) -> str:
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
            reservation = uuid.uuid4().hex
            db.execute(
                "INSERT INTO model_attempts(user_key, started, reservation_id) VALUES (?, ?, ?)",
                (user_key, now, reservation),
            )
            return reservation

    def refund(self, user_key: str, reservation_id=None) -> None:
        """Give back this user's newest reservation. Only for a question turned away before any
        provider request was sent; a failed provider attempt still counts."""
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            if reservation_id is not None:
                db.execute(
                    "DELETE FROM model_attempts WHERE user_key = ? AND reservation_id = ?",
                    (user_key, reservation_id),
                )
                return
            db.execute(
                "DELETE FROM model_attempts WHERE rowid = ("
                "SELECT rowid FROM model_attempts WHERE user_key = ? "
                "ORDER BY started DESC LIMIT 1)",
                (user_key,),
            )


def answer_as_user(engine, user_key: str, question: str, role="unknown", history=None):
    """Bind identity inside the actual worker thread, without changing engine contracts."""
    token = USER_KEY.set(user_key)
    try:
        return engine.answer(question, role, history)
    finally:
        USER_KEY.reset(token)
