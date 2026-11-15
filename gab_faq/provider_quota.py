"""Atomic provider-wide RPM/TPM reservations, bounded waiting and numeric usage accounting."""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path


class SharedProviderQuota:
    def __init__(self, limits, path=None, *, clock=time.time, sleep=time.sleep):
        self.limits, self.clock, self.sleep = limits, clock, sleep
        self.path = Path(
            path or os.environ.get("GAB_PROVIDER_USAGE_PATH", "output/provider_usage.sqlite3")
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS provider_attempts (id TEXT PRIMARY KEY, started REAL, reserved INTEGER, input_tokens INTEGER, output_tokens INTEGER, status TEXT)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS provider_time ON provider_attempts(started)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS provider_waiters (id TEXT PRIMARY KEY, expires REAL)"
            )

    def reserve(self, tokens, max_wait=None):
        if tokens > self.limits.provider_tokens_per_minute:
            return None
        wait_limit = self.limits.provider_max_wait_seconds if max_wait is None else max_wait
        deadline = self.clock() + wait_limit
        ident = uuid.uuid4().hex
        queued = False
        try:
            while True:
                now = self.clock()
                with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("DELETE FROM provider_waiters WHERE expires <= ?", (now,))
                    count, used = db.execute(
                        "SELECT COUNT(*), COALESCE(SUM(reserved), 0) FROM provider_attempts WHERE started > ?",
                        (now - 60,),
                    ).fetchone()
                    if (
                        count < self.limits.provider_requests_per_minute
                        and used + tokens <= self.limits.provider_tokens_per_minute
                    ):
                        db.execute(
                            "INSERT INTO provider_attempts VALUES (?, ?, ?, NULL, NULL, 'reserved')",
                            (ident, now, tokens),
                        )
                        return ident
                    if now >= deadline:
                        return None
                    if not queued:
                        waiting = db.execute("SELECT COUNT(*) FROM provider_waiters").fetchone()[0]
                        if waiting >= self.limits.provider_queue_capacity:
                            return None
                        db.execute("INSERT INTO provider_waiters VALUES (?, ?)", (ident, deadline))
                        queued = True
                self.sleep(min(0.25, max(0, deadline - now)))
        finally:
            if queued:
                with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
                    db.execute("DELETE FROM provider_waiters WHERE id = ?", (ident,))

    def finish(self, ident, usage=None, status="unknown"):
        valid = isinstance(usage, dict) and all(
            type(usage.get(k)) is int and usage[k] >= 0
            for k in ("prompt_tokens", "completion_tokens")
        )
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            if valid:
                # Retain the larger reservation: malformed low counts cannot increase capacity.
                db.execute(
                    "UPDATE provider_attempts SET input_tokens=?, output_tokens=?, reserved=MAX(reserved, ?), status=? WHERE id=?",
                    (
                        usage["prompt_tokens"],
                        usage["completion_tokens"],
                        usage["prompt_tokens"] + usage["completion_tokens"],
                        str(status),
                        ident,
                    ),
                )
            else:
                db.execute("UPDATE provider_attempts SET status=? WHERE id=?", (str(status), ident))

    def acquire(self, max_wait=None):
        return bool(self.reserve(0, max_wait))
