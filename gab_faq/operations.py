"""Bounded inference, process ownership, health endpoints, and low-cardinality metrics."""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from weakref import WeakValueDictionary

from aiohttp import web


class Metrics:
    def __init__(self):
        self._values = Counter(
            {
                name: 0
                for name in (
                    "gab_answer_duration_seconds_count",
                    "gab_answer_duration_seconds_sum",
                    "gab_answers_active",
                    "gab_answers_busy_total",
                    "gab_answers_completed_total",
                    "gab_answers_failed_total",
                    "gab_answers_pending",
                    "gab_answers_throttled_total",
                    "gab_answers_timeout_total",
                    "gab_command_sync_failures_total",
                    "gab_faq",
                    "gab_gateway_disconnects_total",
                    "gab_message_errors_total",
                    "gab_messages_received_total",
                    "gab_ready",
                    "gab_reminder_failures_total",
                    "gab_reminders_sent_total",
                    "gab_shutdown_abandoned_jobs_total",
                    "gab_storage_errors_total",
                    "gab_storage_free_bytes",
                    "gab_ticket_check_failures_total",
                    "gab_ticket_missing_total",
                    "gab_ticket_scan_failures_total",
                    "gab_tickets_pending",
                    "gab_tickets_resolved_total",
                )
            }
        )
        self._lock = threading.Lock()

    def add(self, name: str, value: float = 1):
        if not re.fullmatch(r"gab_[a-z_]+", name):
            raise ValueError("Metric names must be static gab_* identifiers")
        with self._lock:
            self._values[name] += value

    def set(self, name: str, value: float):
        with self._lock:
            self._values[name] = value

    def render(self) -> str:
        with self._lock:
            return "".join(f"{key} {value}\n" for key, value in sorted(self._values.items()))


class Busy(RuntimeError):
    pass


class Throttled(Busy):
    pass


class BoundedAnswers:
    """A deadline never releases a native worker that is still executing.

    Caller cancellation/timeout leaves the tracked task holding its slot until
    the synchronous call finishes. This prevents unbounded abandoned threads.
    """

    def __init__(self, *, workers=4, capacity=16, timeout=45, per_user=6, metrics=None):
        if workers < 1 or capacity < workers or timeout <= 0 or per_user < 1:
            raise ValueError("Invalid answer worker limits")
        self.metrics = metrics or Metrics()
        self.timeout, self.capacity, self.per_user = timeout, capacity, per_user
        self.accepting = True
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="faq-answer")
        self._slots = asyncio.Semaphore(workers)
        self._locks = WeakValueDictionary()
        self._tasks: set[asyncio.Task] = set()
        self._started: set[asyncio.Task] = set()
        self._users: dict[str, deque] = {}

    async def answer(self, function, *, user: str, conversation: str):
        if not self.accepting or len(self._tasks) >= self.capacity:
            self.metrics.add("gab_answers_busy_total")
            raise Busy("The bot is busy; please retry shortly")
        now = time.monotonic()
        recent = self._users.setdefault(user, deque())
        while recent and now - recent[0] >= 60:
            recent.popleft()
        if len(recent) >= self.per_user:
            self.metrics.add("gab_answers_throttled_total")
            raise Throttled("Please wait before asking another question")
        recent.append(now)
        if len(self._users) > 10_000:
            self._users = {
                key: times for key, times in self._users.items() if times and now - times[-1] < 60
            }
        task = asyncio.create_task(self._run(function, conversation))
        self._tasks.add(task)
        task.add_done_callback(self._finished)
        self.metrics.set("gab_answers_pending", len(self._tasks))
        try:
            return await asyncio.wait_for(asyncio.shield(task), self.timeout)
        except TimeoutError:
            self.metrics.add("gab_answers_timeout_total")
            if task not in self._started:
                task.cancel()
            raise

    def _finished(self, task):
        self._tasks.discard(task)
        self._started.discard(task)
        self.metrics.set("gab_answers_pending", len(self._tasks))
        if not task.cancelled():
            task.exception()  # retrieve errors even when the caller already timed out

    async def _run(self, function, conversation):
        lock = self._locks.setdefault(conversation, asyncio.Lock())
        async with lock, self._slots:
            self._started.add(asyncio.current_task())
            started = time.monotonic()
            self.metrics.add("gab_answers_active", 1)
            try:
                result = await asyncio.get_running_loop().run_in_executor(self._pool, function)
                self.metrics.add("gab_answers_completed_total")
                return result
            except Exception:
                self.metrics.add("gab_answers_failed_total")
                raise
            finally:
                self.metrics.add("gab_answers_active", -1)
                self.metrics.add("gab_answer_duration_seconds_sum", time.monotonic() - started)
                self.metrics.add("gab_answer_duration_seconds_count")

    async def close(self, grace=30):
        self.accepting = False
        if self._tasks:
            _, pending = await asyncio.wait(self._tasks, timeout=grace)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
                self.metrics.add("gab_shutdown_abandoned_jobs_total", len(pending))
        self._pool.shutdown(wait=False, cancel_futures=True)


class ProcessOwner:
    """OS-backed advisory lock; released by the OS even after a crashed process."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a+b")
        if self._handle.seek(0, os.SEEK_END) == 0:
            self._handle.write(b"0")
            self._handle.flush()
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._handle.close()
            raise RuntimeError("Another bot process owns this output directory") from error

    def close(self):
        if self._handle.closed:
            return
        if os.name == "nt":
            import msvcrt

            self._handle.seek(0)
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle, fcntl.LOCK_UN)
        self._handle.close()


class HealthServer:
    def __init__(self, readiness, metrics: Metrics):
        self.readiness, self.metrics = readiness, metrics
        self._runner = None

    def application(self):
        app = web.Application()

        async def live(request):
            return web.json_response({"alive": True})

        async def ready(request):
            checks = self.readiness()
            return web.json_response(
                {"ready": all(checks.values()), "checks": checks},
                status=200 if all(checks.values()) else 503,
            )

        async def metrics(request):
            self.metrics.set("gab_ready", int(all(self.readiness().values())))
            return web.Response(text=self.metrics.render(), content_type="text/plain")

        app.router.add_get("/health/live", live)
        app.router.add_get("/health/ready", ready)
        app.router.add_get("/metrics", metrics)
        return app

    async def start(self, host="127.0.0.1", port=8080):
        self._runner = web.AppRunner(self.application(), access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, host, port).start()

    async def close(self):
        if self._runner:
            await self._runner.cleanup()


def json_log(record: dict) -> str:
    return json.dumps(record, separators=(",", ":"), default=str)
