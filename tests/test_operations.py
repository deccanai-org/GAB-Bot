"""Real HTTP health checks, worker exhaustion, deadlines, and restart ownership."""

import asyncio
import threading

import aiohttp
import pytest
from aiohttp import web

from gab_faq.operations import BoundedAnswers, Busy, HealthServer, Metrics, ProcessOwner, Throttled
from gab_faq.runtime_config import RuntimeSettings


def test_timeout_keeps_native_work_bounded_until_it_finishes():
    release = threading.Event()
    running = threading.Event()

    def slow():
        running.set()
        release.wait(5)
        return "done"

    async def run():
        executor = BoundedAnswers(workers=1, capacity=1, timeout=0.03)
        try:
            with pytest.raises(TimeoutError):
                await executor.answer(slow, user="u", conversation="c")
            assert running.is_set()
            with pytest.raises(Busy):
                await executor.answer(lambda: "extra", user="v", conversation="d")
            release.set()
            await executor.close()
            assert "gab_answers_active 0" in executor.metrics.render()
        finally:
            release.set()

    asyncio.run(run())


def test_expired_queued_job_never_runs():
    release = threading.Event()
    called = []

    async def run():
        executor = BoundedAnswers(workers=1, capacity=2, timeout=0.03, per_user=10)
        first = asyncio.create_task(
            executor.answer(lambda: release.wait(5), user="a", conversation="a")
        )
        try:
            await asyncio.sleep(0.005)
            with pytest.raises(TimeoutError):
                await executor.answer(lambda: called.append(True), user="b", conversation="b")
            await asyncio.gather(first, return_exceptions=True)
            release.set()
            await executor.close()
            assert called == []
        finally:
            release.set()

    asyncio.run(run())


def test_per_user_quota_and_draining_reject_new_work():
    async def run():
        executor = BoundedAnswers(workers=1, capacity=2, per_user=1)
        assert await executor.answer(lambda: "ok", user="u", conversation="c") == "ok"
        with pytest.raises(Throttled):
            await executor.answer(lambda: "extra", user="u", conversation="c")
        await executor.close()
        with pytest.raises(Busy):
            await executor.answer(lambda: "extra", user="v", conversation="c")

    asyncio.run(run())


def test_two_process_owners_cannot_share_the_same_data_directory(tmp_path):
    path = tmp_path / "owner.lock"
    owner = ProcessOwner(path)
    try:
        with pytest.raises(RuntimeError, match="Another bot process"):
            ProcessOwner(path)
    finally:
        owner.close()
    replacement = ProcessOwner(path)
    replacement.close()
    replacement.close()


def test_health_is_live_while_unready_and_tracks_gateway_and_draining():
    async def run():
        checks = {"gateway": False, "storage": True, "accepting": True}
        metrics = Metrics()
        metrics.add("gab_messages_received_total")
        runner = web.AppRunner(HealthServer(lambda: checks, metrics).application())
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with aiohttp.ClientSession() as client:
                base = f"http://127.0.0.1:{port}"
                async with client.get(base + "/health/live") as response:
                    assert response.status == 200
                async with client.get(base + "/health/ready") as response:
                    assert response.status == 503
                checks["gateway"] = True
                async with client.get(base + "/health/ready") as response:
                    assert response.status == 200
                checks["accepting"] = False
                async with client.get(base + "/health/ready") as response:
                    assert response.status == 503
                async with client.get(base + "/metrics") as response:
                    assert "gab_messages_received_total 1" in await response.text()
        finally:
            await runner.cleanup()

    asyncio.run(run())


@pytest.mark.parametrize(
    "values",
    [
        {"answer_workers": 0},
        {"answer_capacity": 1},
        {"export_max_bytes": 0},
        {"unknown_setting": 1},
    ],
)
def test_invalid_operating_limits_are_rejected(values):
    with pytest.raises(ValueError):
        RuntimeSettings.parse(values)
