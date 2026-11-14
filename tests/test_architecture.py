"""Application-boundary regressions: privacy, storage, lifecycle, and moderation."""

import asyncio
import csv
import io
import json
import logging
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace as N
from unittest.mock import AsyncMock

import discord
import pytest

from gab_faq.contracts import Answer
from gab_faq.discord_bot.app import FaqBot
from gab_faq.discord_bot.exports import HistoryExporter
from gab_faq.discord_bot.moderation import ModerationService
from gab_faq.discord_bot.queries import QueryService
from gab_faq.discord_bot.settings import BotSettings
from gab_faq.discord_bot.views import ChatLogChannelSelectView, TimeFrameView
from gab_faq.replies import QuestionLog
from gab_faq.storage import SecretFilter, atomic_write, csv_bytes

from .conftest import ROOT


def settings(tmp_path):
    return replace(
        BotSettings.load(ROOT / "config.yaml"),
        output_dir=tmp_path,
        watched_names=frozenset({"private-staff", "general"}),
    )


class Channel:
    def __init__(self, ident, name, readable=True):
        self.id, self.name, self.readable = ident, name, readable
        self.category = None
        self.messages = []

    def permissions_for(self, member):
        return N(view_channel=self.readable, read_message_history=self.readable)

    async def history(self, **kwargs):
        for message in self.messages:
            yield message


def message(channel, content="which model? password: SYNTHETIC_ONLY", ident=101):
    result = N(
        id=ident,
        channel=channel,
        author=N(bot=False, id=42, name="sam", display_name="sam"),
        content=content,
        created_at=datetime.now(timezone.utc),
        attachments=[],
    )
    channel.messages.append(result)
    return result


def interaction(channels):
    return N(
        guild=N(text_channels=channels, news_channels=[], filesize_limit=10**7),
        user=N(id=42),
        response=N(defer=AsyncMock(), send_message=AsyncMock()),
        followup=N(send=AsyncMock()),
    )


@pytest.mark.parametrize("action", ["recent", "export", "chatlog"])
def test_private_channel_exports_are_ephemeral_and_redacted(tmp_path, action):
    service = QueryService(settings(tmp_path))
    visible, hidden = Channel(11, "private-staff"), Channel(12, "hidden", readable=False)
    message(visible)
    message(hidden, "how to see HIDDEN_ONLY?")
    request = interaction([visible, hidden])

    async def run():
        await TimeFrameView(HistoryExporter(service), action, ["__all__"])._handle(request, 1)

    try:
        asyncio.run(run())
        assert request.response.defer.await_args.kwargs["ephemeral"] is True
        for call in request.followup.send.await_args_list:
            assert call.kwargs["ephemeral"] is True
            assert call.kwargs["allowed_mentions"].everyone is False
            if file := call.kwargs.get("file"):
                text = file.fp.getvalue().decode("utf-8")
                assert "SYNTHETIC_ONLY" not in text and "HIDDEN_ONLY" not in text
                assert "[redacted]" in text
                file.close()
            if embed := call.kwargs.get("embed"):
                assert "SYNTHETIC_ONLY" not in embed.description
    finally:
        service.store.close()


def test_channel_picker_hides_unreadable_channel_names(tmp_path):
    service = QueryService(settings(tmp_path))
    request = interaction([Channel(11, "private-staff"), Channel(12, "HIDDEN_ONLY", False)])

    async def run():
        return ChatLogChannelSelectView(HistoryExporter(service), request.guild, request.user)

    try:
        view = asyncio.run(run())
        assert "HIDDEN_ONLY" not in repr([(o.label, o.value) for o in view.children[0].options])
    finally:
        service.store.close()


def test_collection_redacts_before_database_and_snapshot_persistence(tmp_path):
    service = QueryService(settings(tmp_path))
    query = message(Channel(11, "private-staff"))
    try:
        assert service.capture(query) is True
        assert service.capture(query) is False
        assert "SYNTHETIC_ONLY" not in json.dumps(service.store.records())
        service.store.snapshot()
        assert all(
            "SYNTHETIC_ONLY" not in (tmp_path / name).read_text(encoding="utf-8")
            for name in ("messages.json", "messages.csv")
        )
    finally:
        service.store.close()


def test_existing_json_is_migrated_and_scrubbed(tmp_path):
    old = [
        {
            "message_id": "1",
            "content": "how to reset? password: SYNTHETIC_ONLY",
            "category": "Other",
        }
    ]
    (tmp_path / "messages.json").write_text(json.dumps(old))
    first = QueryService(settings(tmp_path))
    assert len(first.store.records()) == 1
    first.store.close()
    second = QueryService(settings(tmp_path))
    try:
        assert len(second.store.records()) == 1
        assert "SYNTHETIC_ONLY" not in (tmp_path / "messages.json").read_text()
    finally:
        second.store.close()


def test_failed_snapshot_replace_preserves_previous_data(tmp_path, monkeypatch):
    path = tmp_path / "snapshot.json"
    path.write_text("previous")

    def fail(*args):
        raise OSError("synthetic disk error")

    monkeypatch.setattr("gab_faq.storage.os.replace", fail)
    with pytest.raises(OSError):
        atomic_write(path, "replacement")
    assert path.read_text() == "previous"


def test_csv_secrets_and_formulas_are_safe():
    rows = list(
        csv.DictReader(
            io.StringIO(
                csv_bytes(
                    [{"message": "=HYPERLINK(1)"}, {"message": "password: SYNTHETIC_ONLY"}],
                    ["message"],
                ).decode()
            )
        )
    )
    assert rows[0]["message"].startswith("'=")
    assert rows[1]["message"] == "[redacted]"


def test_question_logs_scrub_nested_fields_at_the_storage_boundary(tmp_path):
    logs = QuestionLog(tmp_path)
    logs.record(
        platform="discord",
        channel="1",
        user="2",
        role="qc",
        question="password: SYNTHETIC_ONLY",
        answer=Answer("token: SYNTHETIC_ONLY", "error"),
    )
    logs.record_request(
        kind="task",
        channel="1",
        user="2",
        role="qc",
        route="task_qc",
        fields={"nested": {"text": "password: SYNTHETIC_ONLY"}},
        attachments=[],
    )
    assert all("SYNTHETIC_ONLY" not in path.read_text() for path in tmp_path.glob("*.jsonl"))


def test_logging_filter_redacts_interpolated_values_and_exception_text():
    try:
        raise ValueError("password: SYNTHETIC_ONLY")
    except ValueError:
        record = logging.LogRecord(
            "test", logging.ERROR, "", 1, "token: %s", ("SYNTHETIC_ONLY",), sys.exc_info()
        )
    assert SecretFilter().filter(record)
    assert "SYNTHETIC_ONLY" not in logging.Formatter().format(record)


def test_importing_entry_point_has_no_filesystem_or_model_side_effects(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import bot, sys; assert callable(bot.create_bot); assert 'fastembed' not in sys.modules; assert 'anthropic' not in sys.modules",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_independent_app_instances_have_independent_services(tmp_path):
    first = FaqBot(settings(tmp_path / "first"), ROOT / "config.yaml")
    second = FaqBot(settings(tmp_path / "second"), ROOT / "config.yaml")
    try:
        assert first.faq_answers is None and second.faq_answers is None
        assert first.queries.capture(message(Channel(11, "private-staff")))
        assert second.queries.store.records() == []
        assert first.tree.get_command("export").guild_only
    finally:
        asyncio.run(first.close())
        asyncio.run(second.close())


def test_shutdown_releases_ownership_even_when_final_snapshot_fails(tmp_path):
    app = FaqBot(settings(tmp_path), ROOT / "config.yaml")
    assert app.queries.capture(message(Channel(11, "private-staff")))

    def unavailable():
        raise OSError("synthetic snapshot failure")

    app.queries.store.snapshot = unavailable
    asyncio.run(app.close())
    replacement = FaqBot(settings(tmp_path), ROOT / "config.yaml")
    try:
        assert len(replacement.queries.store.records()) == 1
    finally:
        asyncio.run(replacement.close())


def test_production_readiness_rejects_public_staff_channels_and_missing_permissions(
    tmp_path, monkeypatch
):
    from gab_faq.config import Settings, _platform

    app = FaqBot(replace(settings(tmp_path), production=True), ROOT / "config.yaml")
    everyone, bot_member = object(), object()
    permissions = N(
        view_channel=True,
        read_message_history=True,
        send_messages=True,
        embed_links=True,
        attach_files=True,
    )
    answer = N(id=1, name="ask", category=None, permissions_for=lambda member: permissions)
    private = [True]
    staff = N(
        id=2,
        name="staff",
        category=None,
        permissions_for=lambda member: (
            N(view_channel=not private[0]) if member is everyone else permissions
        ),
    )
    guild = N(text_channels=[answer, staff], default_role=everyone, me=bot_member)
    guilds = [guild]
    monkeypatch.setattr(FaqBot, "guilds", property(lambda self: guilds))
    app.faq_answers = N(
        settings=Settings(
            discord=_platform({"answer_channels": ["ask"], "unanswered_channel": "staff"})
        )
    )
    try:
        assert app.validate_routes()
        private[0] = False
        assert not app.validate_routes()
        private[0] = True
        permissions.send_messages = False
        assert not app.validate_routes()
        permissions.send_messages = True
        guilds.append(guild)
        assert not app.validate_routes()
    finally:
        app.faq_answers = None
        asyncio.run(app.close())


def test_moderation_preserves_configured_delete_policy_and_scrubs_staff_cards():
    service = ModerationService(BotSettings.load(ROOT / "config.yaml").moderation)
    score, reasons = service.check("fuck")
    assert score >= 3 and service.should_delete("fuck", score, reasons)[0]
    query = message(Channel(11, "general"), "fuck password: SYNTHETIC_ONLY")
    query.author.mention = "<@42>"
    query.guild = N(id=1)
    embed = service._build_mod_alert_embed(query, score, reasons, 1)
    assert "SYNTHETIC_ONLY" not in json.dumps(embed.to_dict())


def test_moderation_deletion_succeeds_even_when_staff_notice_fails():
    service = ModerationService(BotSettings.load(ROOT / "config.yaml").moderation)
    query = message(Channel(11, "general"), "fuck")
    query.author.mention = "<@42>"
    query.delete = AsyncMock()
    staff = N(
        send=AsyncMock(
            side_effect=discord.Forbidden(N(status=403, reason="Forbidden"), "synthetic failure")
        )
    )
    assert asyncio.run(service.moderate(query, staff)) is True
    query.delete.assert_awaited_once()


def test_live_moderation_and_audit_do_not_repeat_actions():
    service = ModerationService(BotSettings.load(ROOT / "config.yaml").moderation)
    channel = Channel(11, "general")
    query = message(channel, "fuck")
    query.author.mention = "<@42>"
    query.delete = AsyncMock()
    staff = N(id=12, name="mod-alerts", send=AsyncMock())
    guild = N(text_channels=[channel, staff])

    async def run():
        await service.moderate(query, staff)
        await service.audit(N(guilds=[guild]))

    asyncio.run(run())
    query.delete.assert_awaited_once()
    staff.send.assert_awaited_once()
