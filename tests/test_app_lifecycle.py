"""Application failure/recovery scenarios with external Discord operations replaced."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace as N
from unittest.mock import AsyncMock

import discord
import pytest

from gab_faq.discord_bot import app as application
from gab_faq.discord_bot.app import FaqBot

from .conftest import ROOT
from .test_architecture import Channel, message, settings


def fake_faq():
    return N(
        start=AsyncMock(),
        handle=AsyncMock(return_value=True),
        brain=N(inner=N(embedder=object())),
        followup=N(close=AsyncMock(), tickets=N(health=lambda: True)),
        executor=N(close=AsyncMock()),
    )


def test_failed_required_faq_initialization_prevents_startup(tmp_path, monkeypatch):
    app = FaqBot(settings(tmp_path), ROOT / "config.yaml")
    monkeypatch.setattr(application, "setup_faq_answers", lambda *_: None)

    async def run():
        try:
            with pytest.raises(RuntimeError, match="required"):
                await app.setup_hook()
            assert not app.readiness()["initialized"]
        finally:
            await app.close()

    asyncio.run(run())


def test_command_sync_and_storage_can_recover_without_restarting(tmp_path, monkeypatch):
    app = FaqBot(settings(tmp_path), ROOT / "config.yaml")
    faq = fake_faq()
    monkeypatch.setattr(application, "setup_faq_answers", lambda *_: faq)
    failure = discord.Forbidden(N(status=403, reason="Forbidden"), "synthetic failure")
    app.tree.sync = AsyncMock(side_effect=[failure, []])
    monkeypatch.setattr(app.snapshot_loop, "start", lambda: None)
    monkeypatch.setattr(app.audit_loop, "start", lambda: None)
    monkeypatch.setattr(app, "is_ready", lambda: True)

    async def run():
        try:
            await app.setup_hook()
            assert not app.readiness()["commands"]
            await app.snapshot_loop()
            assert all(app.readiness().values())
            monkeypatch.setattr(app.queries.store, "health", lambda: False)
            await app.snapshot_loop()
            assert not app.readiness()["storage"]
            monkeypatch.setattr(app.queries.store, "health", lambda: True)
            await app.snapshot_loop()
            assert all(app.readiness().values())
        finally:
            await app.close()
            assert not app.readiness()["accepting"]

    asyncio.run(run())
    faq.start.assert_awaited_once()
    faq.followup.close.assert_awaited_once()


def test_deleted_messages_never_reach_collection_or_answering(tmp_path):
    app = FaqBot(settings(tmp_path), ROOT / "config.yaml")
    faq = fake_faq()
    app.faq_answers = faq
    app.moderation.enabled = True
    app.moderation.find_alert_channel = lambda guild: None
    app.moderation.moderate = AsyncMock(return_value=True)
    query = message(Channel(11, "private-staff"))
    query.guild = N()

    async def run():
        try:
            await app.on_message(query)
            assert app.queries.store.records() == []
            faq.handle.assert_not_awaited()
        finally:
            await app.close()

    asyncio.run(run())


def test_collection_failure_does_not_stop_faq_answers(tmp_path):
    app = FaqBot(settings(tmp_path), ROOT / "config.yaml")
    faq = fake_faq()
    app.faq_answers = faq
    app.moderation.enabled = False
    app.process_commands = AsyncMock()

    def fail(_):
        raise OSError("synthetic storage failure")

    app.queries.capture = fail
    query = message(Channel(11, "private-staff"))
    query.guild = N()

    async def run():
        try:
            await app.on_message(query)
            faq.handle.assert_awaited_once_with(query)
            await app.on_disconnect()
            assert "gab_gateway_disconnects_total 1" in app.metrics.render()
        finally:
            await app.close()

    asyncio.run(run())


def test_readiness_rejects_degraded_embeddings_in_production(tmp_path, monkeypatch):
    app = FaqBot(replace(settings(tmp_path), production=True), ROOT / "config.yaml")
    faq = fake_faq()
    faq.brain.inner.embedder = None
    monkeypatch.setattr(application, "setup_faq_answers", lambda *_: faq)

    async def run():
        try:
            with pytest.raises(RuntimeError, match="embedding model"):
                await app.setup_hook()
            assert not app.readiness()["initialized"]
        finally:
            await app.close()

    asyncio.run(run())
