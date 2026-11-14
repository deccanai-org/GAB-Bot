"""Permission-scoped history retrieval and private export delivery."""

from __future__ import annotations

import asyncio
import io
import json
import logging
from contextlib import asynccontextmanager
from datetime import timezone

import discord

from ..discord_common import allowed_mentions, readable_channels
from ..storage import csv_bytes
from .queries import CSV_FIELDS, QueryService, all_text_channels

log = logging.getLogger(__name__)
CHATLOG_CSV_FIELDS = ["date", "time", "username", "message"]
MAX_CSV_BYTES = 25 * 1024 * 1024 - 512


class ExportError(RuntimeError):
    pass


class ExportBudget:
    def __init__(self, limits):
        self.limits = limits
        self.scanned = self.rows = self.bytes = 0

    def scan(self):
        self.scanned += 1
        if self.scanned > self.limits.export_max_scanned:
            raise ExportError(
                "Too much history to scan. Choose fewer channels or a shorter date range."
            )

    def include(self, record):
        self.rows += 1
        self.bytes += len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        if self.rows > self.limits.export_max_rows or self.bytes > self.limits.export_max_bytes:
            raise ExportError(
                "Export exceeds the size limit. Choose fewer channels or a shorter date range."
            )


class HistoryExporter:
    def __init__(self, queries: QueryService):
        self.queries = queries
        self.limits = queries.settings.runtime
        self._active = set()

    @asynccontextmanager
    async def operation(self, member):
        key = getattr(member, "id", None)
        if key is None or key in self._active or len(self._active) >= self.limits.export_workers:
            raise ExportError("An export is already running. Please wait and retry.")
        self._active.add(key)
        try:
            async with asyncio.timeout(self.limits.export_timeout):
                yield ExportBudget(self.limits)
        except TimeoutError as error:
            raise ExportError(
                "Export timed out. Choose fewer channels or a shorter date range."
            ) from error
        finally:
            self._active.discard(key)

    def selected_channels(self, guild, selection: list[str], member) -> list:
        visible = readable_channels(member, all_text_channels(guild))
        if "__all__" in selection:
            return visible
        if "__watched__" in selection:
            return [channel for channel in visible if self.queries.is_watched(channel)]
        return [channel for channel in visible if str(channel.id) in selection]

    async def query_records(self, guild, cutoff, category=None, member=None) -> list[dict]:
        async with self.operation(member) as budget:
            return await self._query_records(guild, cutoff, category, member, budget)

    async def _query_records(self, guild, cutoff, category, member, budget):
        result = []
        for channel in readable_channels(member, self.queries.watched_channels(guild)):
            try:
                async for message in channel.history(
                    limit=self.queries.settings.export_limit, after=cutoff, oldest_first=True
                ):
                    budget.scan()
                    record = self.queries.record(message)
                    if (
                        record
                        and self.queries.is_query(record["content"])
                        and (category is None or record["category"] == category)
                    ):
                        budget.include(record)
                        result.append(record)
            except discord.HTTPException:
                log.warning("History unavailable for channel %s", channel.id)
        return sorted(result, key=lambda record: record["timestamp"])

    async def chat_log_rows(self, guild, selection, cutoff, member) -> tuple[list, list[dict]]:
        async with self.operation(member) as budget:
            return await self._chat_log_rows(guild, selection, cutoff, member, budget)

    async def _chat_log_rows(self, guild, selection, cutoff, member, budget):
        channels = self.selected_channels(guild, selection, member)
        rows = []
        for channel in channels:
            try:
                async for message in channel.history(
                    limit=self.queries.settings.export_limit, after=cutoff, oldest_first=True
                ):
                    budget.scan()
                    timestamp = message.created_at
                    timestamp = (
                        timestamp.replace(tzinfo=timezone.utc)
                        if timestamp.tzinfo is None
                        else timestamp.astimezone(timezone.utc)
                    )
                    content = message.content or " ".join(a.url for a in message.attachments)
                    record = {
                        "date": timestamp.strftime("%Y-%m-%d"),
                        "time": timestamp.strftime("%H:%M:%S"),
                        "username": getattr(message.author, "display_name", None)
                        or getattr(message.author, "name", "unknown"),
                        "message": content,
                    }
                    budget.include(record)
                    rows.append(record)
            except discord.HTTPException:
                log.warning("History unavailable for channel %s", channel.id)
        return channels, rows

    async def send_csv(
        self, interaction, records: list[dict], *, chatlog: bool, filename: str
    ) -> None:
        data = await asyncio.to_thread(
            csv_bytes, records, CHATLOG_CSV_FIELDS if chatlog else CSV_FIELDS
        )
        size_limit = min(
            MAX_CSV_BYTES,
            self.limits.export_max_bytes,
            getattr(interaction.guild, "filesize_limit", MAX_CSV_BYTES),
        )
        if len(data) > size_limit:
            await private_send(
                interaction, "CSV too large. Try fewer channels or a shorter date range."
            )
            return
        await private_send(
            interaction,
            f"Full CSV — {len(records)} row(s)",
            file=discord.File(io.BytesIO(data), filename=filename),
        )


async def private_send(interaction, content=None, **kwargs):
    """All query results use this boundary, including errors, previews, and downloads."""
    return await interaction.followup.send(
        content, ephemeral=True, allowed_mentions=allowed_mentions(), **kwargs
    )
