"""Discord query-explorer views. Every result and navigation response is private."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import discord

from ..discord_common import allowed_mentions, find_text_channel, readable_channels
from ..redact import redact_secrets
from ..storage import read_json, write_json
from .exports import ExportError, HistoryExporter, private_send
from .queries import all_text_channels, top_unique_recent_queries


def build_queries_embed(records, days, cutoff, title_prefix="") -> discord.Embed:
    lines = []
    for index, record in enumerate(records, 1):
        body = redact_secrets(record.get("content", "")).replace("\n", " ")[:220]
        lines.append(
            f"**{index}.** `#{record.get('channel_name', '?')}` · **{record.get('category', '?')}**\n{body}"
        )
    description = "\n\n".join(lines) or "No queries matched your filters."
    return discord.Embed(
        title=f"{title_prefix}{len(records)} unique recent queries",
        description=description[:4000],
        color=discord.Color.blurple(),
    ).set_footer(text=f"Last {days} day(s) · since {cutoff:%Y-%m-%d %H:%M UTC} · private results")


class ExplorerView(discord.ui.View):
    def __init__(self, exporter: HistoryExporter, timeout=None):
        super().__init__(timeout=timeout)
        self.exporter = exporter

    async def open(self, interaction, action: str):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Use the query explorer in a server.", ephemeral=True
            )
            return
        view = (
            ChatLogChannelSelectView(self.exporter, interaction.guild, interaction.user)
            if action == "chatlog"
            else TimeFrameView(self.exporter, action)
        )
        await interaction.response.send_message(
            "Choose channels:" if action == "chatlog" else "Choose a time frame:",
            view=view,
            ephemeral=True,
            allowed_mentions=allowed_mentions(),
        )


class FAQPanelView(ExplorerView):
    @discord.ui.button(
        label="Browse by Category", style=discord.ButtonStyle.primary, custom_id="faq_v1_browse"
    )
    async def browse_categories(self, interaction, button):
        await self.open(interaction, "category")

    @discord.ui.button(
        label="View Recent Queries", style=discord.ButtonStyle.primary, custom_id="faq_v1_recent"
    )
    async def view_recent(self, interaction, button):
        await self.open(interaction, "recent")

    @discord.ui.button(
        label="Export Queries", style=discord.ButtonStyle.success, custom_id="faq_v1_export"
    )
    async def export_queries(self, interaction, button):
        await self.open(interaction, "export")

    @discord.ui.button(
        label="Export Chat Logs",
        style=discord.ButtonStyle.secondary,
        custom_id="faq_v1_chatlog",
        row=1,
    )
    async def export_chat_logs(self, interaction, button):
        await self.open(interaction, "chatlog")


class WhatElseView(ExplorerView):
    @discord.ui.button(
        label="Browse Categories", style=discord.ButtonStyle.primary, custom_id="whatelse:browse"
    )
    async def browse(self, interaction, button):
        await self.open(interaction, "category")

    @discord.ui.button(
        label="Recent Queries", style=discord.ButtonStyle.primary, custom_id="whatelse:recent"
    )
    async def recent(self, interaction, button):
        await self.open(interaction, "recent")

    @discord.ui.button(
        label="Export CSV", style=discord.ButtonStyle.success, custom_id="whatelse:export"
    )
    async def export(self, interaction, button):
        await self.open(interaction, "export")

    @discord.ui.button(
        label="Export Chat Logs",
        style=discord.ButtonStyle.secondary,
        custom_id="whatelse:chatlog",
        row=1,
    )
    async def chatlog(self, interaction, button):
        await self.open(interaction, "chatlog")

    @discord.ui.button(
        label="Main Menu",
        style=discord.ButtonStyle.secondary,
        custom_id="whatelse:main_menu",
        row=1,
    )
    async def main_menu(self, interaction, button):
        await interaction.response.send_message(
            "Choose an action:", view=FAQPanelView(self.exporter), ephemeral=True
        )


class TimeFrameView(ExplorerView):
    def __init__(self, exporter, action: str, selection=()):
        super().__init__(exporter, timeout=300)
        self.action, self.selection = action, list(selection)

    async def _handle(self, interaction, days: int):
        if interaction.guild is None:
            await interaction.response.send_message("Server only.", ephemeral=True)
            return
        if self.action == "category":
            await interaction.response.send_message(
                "Choose a category:", view=CategorySelectView(self.exporter, days), ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        if self.action == "chatlog":
            try:
                channels, rows = await self.exporter.chat_log_rows(
                    interaction.guild, self.selection, cutoff, interaction.user
                )
            except ExportError as error:
                await private_send(interaction, str(error))
                return
            if not channels:
                await private_send(interaction, "No readable channels matched your selection.")
                return
            await private_send(
                interaction,
                f"Chat log export: {len(rows)} message(s), last {days} day(s). Timestamps are UTC.",
                view=WhatElseView(self.exporter),
            )
            if rows:
                await self.exporter.send_csv(
                    interaction, rows, chatlog=True, filename=f"chatlog_{days}d.csv"
                )
            return
        await self.show_queries(interaction, days, cutoff, download=self.action == "export")

    async def show_queries(self, interaction, days, cutoff, *, category=None, download=False):
        try:
            records = await self.exporter.query_records(
                interaction.guild, cutoff, category, interaction.user
            )
        except ExportError as error:
            await private_send(interaction, str(error))
            return
        top = top_unique_recent_queries(records, self.exporter.queries.settings.export_top_n)
        await private_send(
            interaction,
            embed=build_queries_embed(top, days, cutoff),
            view=WhatElseView(self.exporter),
        )
        if download and records:
            await self.exporter.send_csv(
                interaction, records, chatlog=False, filename=f"queries_{days}d.csv"
            )

    @discord.ui.button(label="Last 1 day", style=discord.ButtonStyle.secondary)
    async def btn_1d(self, interaction, button):
        await self._handle(interaction, 1)

    @discord.ui.button(label="Last 7 days", style=discord.ButtonStyle.secondary)
    async def btn_7d(self, interaction, button):
        await self._handle(interaction, 7)

    @discord.ui.button(label="Last 30 days", style=discord.ButtonStyle.secondary)
    async def btn_30d(self, interaction, button):
        await self._handle(interaction, 30)

    @discord.ui.button(label="Last 90 days", style=discord.ButtonStyle.secondary)
    async def btn_90d(self, interaction, button):
        await self._handle(interaction, 90)


class ChatLogChannelSelectView(ExplorerView):
    def __init__(self, exporter, guild, member):
        super().__init__(exporter, timeout=300)
        options = [
            discord.SelectOption(label="All watched channels", value="__watched__"),
            discord.SelectOption(label="All readable text channels", value="__all__"),
        ]
        channels = sorted(
            readable_channels(member, all_text_channels(guild)),
            key=lambda channel: (not exporter.queries.is_watched(channel), channel.name.casefold()),
        )
        options += [
            discord.SelectOption(label=f"#{channel.name}"[:100], value=str(channel.id))
            for channel in channels[:23]
        ]
        select = discord.ui.Select(
            placeholder="Select channels", options=options, min_values=1, max_values=len(options)
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction):
        await interaction.response.send_message(
            "Choose a time frame:",
            ephemeral=True,
            view=TimeFrameView(self.exporter, "chatlog", interaction.data.get("values", [])),
        )


class CategorySelectView(ExplorerView):
    def __init__(self, exporter, days: int):
        super().__init__(exporter, timeout=300)
        self.days = days
        options = [
            discord.SelectOption(label=item["name"][:100], value=item["name"][:100])
            for item in exporter.queries.settings.categories[:25]
        ]
        select = discord.ui.Select(placeholder="Choose a category", options=options)
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days)
        await TimeFrameView(self.exporter, "category").show_queries(
            interaction, self.days, cutoff, category=interaction.data["values"][0]
        )


class PanelManager:
    def __init__(self, exporter):
        self.exporter = exporter
        self.path = exporter.queries.settings.output_dir / "faq_panel_id.json"

    async def ensure(self, guild):
        channel = find_text_channel(guild, self.exporter.queries.settings.faq_channel)
        if channel is None:
            return
        ids = await asyncio.to_thread(read_json, self.path, {})
        embed = discord.Embed(
            title="Query Explorer",
            color=discord.Color.blurple(),
            description=(
                "Browse categories, view recent questions, or download query and chat CSVs. "
                "Results are private and include only channels you can read."
            ),
        )
        view = FAQPanelView(self.exporter)
        if existing := ids.get(str(guild.id)):
            try:
                message = await channel.fetch_message(int(existing))
                await message.edit(embed=embed, view=view)
                return
            except discord.HTTPException:
                pass
        message = await channel.send(embed=embed, view=view, allowed_mentions=allowed_mentions())
        ids[str(guild.id)] = str(message.id)
        await asyncio.to_thread(write_json, self.path, ids)
