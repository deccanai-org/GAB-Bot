"""Discord lifecycle and dependency wiring; imports have no runtime effects."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..config import CONFIG_PATH, load_environment
from ..discord_answers import setup_faq_answers
from ..discord_common import channel_keys, find_text_channel
from ..operations import HealthServer, Metrics, ProcessOwner
from ..storage import configure_logging
from .exports import HistoryExporter
from .moderation import ModerationService
from .queries import QueryService
from .settings import BotSettings
from .views import FAQPanelView, PanelManager, TimeFrameView, WhatElseView

log = logging.getLogger(__name__)


class FaqBot(commands.Bot):
    def __init__(self, settings: BotSettings, config_path: Path):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings, self.config_path = settings, config_path
        self.metrics = Metrics()
        self.moderation = ModerationService(settings.moderation)
        self._owner = ProcessOwner(settings.output_dir / "bot.owner.lock")
        try:
            self.queries = QueryService(settings)
        except Exception:
            self._owner.close()
            raise
        self.draining = False
        self._commands_ok = False
        self._storage_ok = True
        self._routes_ok = not settings.production
        self._initialized = False
        self._handlers = set()
        self._close_lock = asyncio.Lock()
        self.exports = HistoryExporter(self.queries)
        self.panels = PanelManager(self.exports)
        self.faq_answers = None
        self._ready_once = self._store_closed = False
        self._register_commands()

    def _register_commands(self):
        @app_commands.command(
            name="export", description="Privately export queries as CSV (FAQ channel only)."
        )
        @app_commands.guild_only()
        @app_commands.describe(days="Days of history to scan (1–365).")
        async def export(interaction: discord.Interaction, days: app_commands.Range[int, 1, 365]):
            own, parent = channel_keys(interaction.channel)
            if self.settings.faq_channel.casefold() not in {key.casefold() for key in own + parent}:
                await interaction.response.send_message(
                    f"Use /export in #{self.settings.faq_channel}.", ephemeral=True
                )
                return
            await interaction.response.defer(thinking=True, ephemeral=True)
            await TimeFrameView(self.exports, "export").show_queries(
                interaction,
                int(days),
                datetime.now(timezone.utc) - timedelta(days=int(days)),
                download=True,
            )

        self.tree.add_command(export)

    async def setup_hook(self):
        self.add_view(FAQPanelView(self.exports))
        self.add_view(WhatElseView(self.exports))
        self.faq_answers = await asyncio.to_thread(setup_faq_answers, self, self.config_path)
        if self.settings.faq_required and self.faq_answers is None:
            raise RuntimeError("FAQ answering is required but failed to initialize")
        if self.faq_answers:
            await self.faq_answers.start()
            inner = self.faq_answers.brain.inner
            search = getattr(inner, "search", inner)
            if self.settings.production and hasattr(search, "embedder") and search.embedder is None:
                raise RuntimeError(
                    "Production requires the embedding model; keyword-only fallback is degraded"
                )
        self._initialized = True
        try:
            await self.tree.sync()
            self._commands_ok = True
        except discord.HTTPException:
            log.exception("Could not synchronize Discord application commands")
        self.snapshot_loop.start()
        if self.moderation.enabled and self.moderation.audit_enabled:
            self.audit_loop.change_interval(minutes=max(1, self.moderation.audit_interval))
            self.audit_loop.start()

    async def on_ready(self):
        log.info("Bot online as %s", self.user)
        self._routes_ok = self.validate_routes()
        if self._ready_once:
            return
        self._ready_once = True
        for guild in self.guilds:
            if self.settings.auto_backfill and self.settings.history_limit:
                for channel in self.queries.watched_channels(guild):
                    try:
                        async for message in channel.history(
                            limit=self.settings.history_limit, oldest_first=False
                        ):
                            await asyncio.to_thread(self.queries.capture, message)
                    except discord.HTTPException:
                        log.warning("Backfill unavailable for channel %s", channel.id)
            try:
                await self.panels.ensure(guild)
            except discord.HTTPException:
                log.exception("Could not update FAQ panel for guild %s", guild.id)
        if self.faq_answers and self.faq_answers.updates:
            try:  # the button panel in the staff updates channel (never stops the bot starting)
                await self.faq_answers.updates.ensure_panels(self.guilds)
            except Exception:
                log.exception("Could not post the updates panel")

    async def on_message(self, message):
        if self.draining:
            return
        task = asyncio.current_task()
        self._handlers.add(task)
        self.metrics.add("gab_messages_received_total")
        try:
            await self._handle_message(message)
        except Exception:
            self.metrics.add("gab_message_errors_total")
            log.exception("Unhandled message processing failure for %s", message.id)
        finally:
            self._handlers.discard(task)

    async def _handle_message(self, message):
        if message.author.bot:
            return
        if self.moderation.enabled and message.guild and message.content:
            alert = self.moderation.find_alert_channel(message.guild)
            if await self.moderation.moderate(message, alert):
                return
        try:
            await asyncio.to_thread(self.queries.capture, message)
        except Exception:
            log.exception("Could not collect query message %s", message.id)
        if self.faq_answers:
            await self.faq_answers.handle(message)
        await self.process_commands(message)

    @tasks.loop(seconds=30)
    async def snapshot_loop(self):
        try:
            await asyncio.to_thread(self.queries.store.snapshot)
            self._storage_ok = await asyncio.to_thread(self.queries.store.health)
            if self.faq_answers:
                self._storage_ok = self._storage_ok and await asyncio.to_thread(
                    self.faq_answers.followup.tickets.health
                )
            self.metrics.set(
                "gab_storage_free_bytes", shutil.disk_usage(self.settings.output_dir).free
            )
        except Exception:
            self._storage_ok = False
            self.metrics.add("gab_storage_errors_total")
            log.exception("Could not update snapshots; committed queries remain in SQLite")
        if self.is_ready() and not self.draining:
            self._routes_ok = self.validate_routes()
            if not self._commands_ok:
                try:
                    await self.tree.sync()
                    self._commands_ok = True
                except discord.HTTPException:
                    self.metrics.add("gab_command_sync_failures_total")

    @tasks.loop(minutes=30)
    async def audit_loop(self):
        try:
            await self.moderation.audit(self)
        except Exception:
            log.exception("Moderation audit failed; it will retry next interval")

    @audit_loop.before_loop
    async def before_audit(self):
        await self.wait_until_ready()

    def readiness(self):
        return {
            "gateway": self.is_ready(),
            "initialized": self._initialized,
            "commands": self._commands_ok,
            "storage": self._storage_ok,
            "routes": self._routes_ok,
            "accepting": not self.draining,
        }

    def validate_routes(self):
        if not self.settings.production:
            return True
        if len(self.guilds) != 1:
            log.error("Production is configured for exactly one Discord guild")
            return False
        if not self.faq_answers:
            return not self.settings.faq_required
        platform = self.faq_answers.settings.discord
        guild = self.guilds[0]
        targets = [
            channel
            for channel in guild.text_channels
            if platform.is_answer_channel(*channel_keys(channel)[0])
        ]
        keys = [key for channel in targets for key in channel_keys(channel)[0]]
        missing = platform.unmatched_answer_channels(keys)
        if missing:
            log.error("Configured answer channels match nothing in the guild: %s", missing)
            return False
        staff = find_text_channel(guild, platform.unanswered_channel)
        if staff is None or guild.me is None:
            log.error("Staff destination or bot guild member is unavailable")
            return False
        if staff.permissions_for(guild.default_role).view_channel:
            log.error("Staff destination must deny View Channel to @everyone")
            return False
        targets.append(staff)
        requests = self.faq_answers.settings.support.requests_channel
        if requests:
            request_channel = find_text_channel(guild, requests)
            if (
                request_channel is None
                or request_channel.permissions_for(guild.default_role).view_channel
            ):
                log.error("Support request destination is missing or public")
                return False
            targets.append(request_channel)
        for channel in targets:
            permissions = channel.permissions_for(guild.me)
            if not all(
                getattr(permissions, name)
                for name in (
                    "view_channel",
                    "read_message_history",
                    "send_messages",
                    "embed_links",
                    "attach_files",
                )
            ):
                log.error("Bot lacks required permissions in channel %s", channel.id)
                return False
        return True

    async def on_disconnect(self):
        self.metrics.add("gab_gateway_disconnects_total")

    async def close(self):
        async with self._close_lock:
            if self._store_closed:
                await super().close()
                return
            self.draining = True
            started = time.monotonic()
            for job in (self.snapshot_loop, self.audit_loop):
                job.cancel()
                task = job.get_task()
                if task and task is not asyncio.current_task():
                    await asyncio.gather(task, return_exceptions=True)
            if self.faq_answers:
                await self.faq_answers.followup.close()
                await self.faq_answers.executor.close(self.settings.runtime.shutdown_grace)
            handlers = self._handlers - {asyncio.current_task()}
            if handlers:
                remaining = max(
                    0, self.settings.runtime.shutdown_grace - (time.monotonic() - started)
                )
                _, pending = await asyncio.wait(handlers, timeout=remaining)
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            try:
                await asyncio.to_thread(self.queries.store.close)
            except Exception:
                log.exception("Final snapshot failed; committed SQLite data retained")
            finally:
                self._store_closed = True
                self._owner.close()
                await super().close()


def create_bot(config_path: Path = CONFIG_PATH) -> FaqBot:
    """Build independent services without connecting to Discord or loading AI models."""
    return FaqBot(BotSettings.load(config_path), Path(config_path))


def main() -> None:
    load_environment()
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_TOKEN is not set. Add it to .env or mounted secrets.")
    configure_logging(Path(os.environ["BOT_LOG_FILE"]) if os.environ.get("BOT_LOG_FILE") else None)
    asyncio.run(serve(create_bot(), token))


async def serve(app: FaqBot, token: str):
    """SIGTERM drains handlers before closing storage and the gateway."""
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed = []
    previous = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stopping.set)
            installed.append(signum)
        except NotImplementedError:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, lambda *_: loop.call_soon_threadsafe(stopping.set))
    health = HealthServer(app.readiness, app.metrics)
    gateway = stop = None
    try:
        async with app:
            await health.start(app.settings.runtime.health_host, app.settings.runtime.health_port)
            gateway = asyncio.create_task(app.start(token))
            stop = asyncio.create_task(stopping.wait())
            done, _ = await asyncio.wait({gateway, stop}, return_when=asyncio.FIRST_COMPLETED)
            if gateway in done:
                await gateway  # startup/auth failures must fail the process
            else:
                app.draining = True
                await app.close()
    finally:
        for task in (gateway, stop):
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await health.close()
        for signum in installed:
            loop.remove_signal_handler(signum)
        for signum, handler in previous.items():
            signal.signal(signum, handler)
