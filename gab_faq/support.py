"""Support requests on Discord: /throttle-request and /task-issue.

    /throttle-request   ask for a higher task limit (throttle): reason, requested limit, stage
    /task-issue         report a problem with one task: task ID, what happened, error message,
                        up to 3 screenshots

Each request becomes a card in the staff requests channel (gab_faq.support.requests_channel, or the
unanswered-questions channel), tagged with the contact chosen by routing.py. The asker gets a private
(ephemeral) confirmation.

Least privilege, enforced here in code:
  - Only in a server, only in the channels the FAQ bot works in (gab_faq.discord.only_in).
  - Nothing here calls an answering engine or AI: the details and screenshots go only to the staff
    card and the request log. The bot can't change a limit or a task itself; a person does.
  - The card pings only the routed contact; user text in it can't ping anyone.
  - One request per person per command every request_cooldown_seconds; inputs are length-limited,
    task IDs and attachments are checked (images or text files, size-limited), secrets are redacted.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import time
from typing import Optional

import discord
from discord import app_commands

from .config import Settings
from .discord_common import allowed_mentions, channel_keys, find_text_channel
from .redact import redact_secrets, scrub_mentions
from .replies import QuestionLog

log = logging.getLogger(__name__)

TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,99}$")
ALLOWED_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt", ".log")
FIELD_LIMIT = 1024

STAGES = [
    app_commands.Choice(name="Annotation", value="annotation"),
    app_commands.Choice(name="Quality Check (QC)", value="qc"),
    app_commands.Choice(name="Re-Annotation", value="re-annotation"),
]


def _clean(text: str | None, limit: int) -> str:
    """User text for a staff card: secrets redacted, mentions made harmless, length-capped."""
    text = scrub_mentions(redact_secrets((text or "").strip()))
    return text if len(text) <= limit else text[: limit - 3] + "..."


class SupportDesk:
    def __init__(self, bot, settings: Settings, question_log: QuestionLog, clock=time.monotonic):
        self.bot = bot
        self.settings = settings
        self.support = settings.support
        self.question_log = question_log
        self.clock = clock
        self._last_request: dict[tuple[str, int], float] = {}
        self._inflight: set[tuple[str, int]] = set()

    # --- registration (called once from discord_answers.setup) ---

    def register(self, tree: app_commands.CommandTree) -> None:
        desk = self

        @app_commands.command(
            name="throttle-request", description="Ask the team for a higher task limit (throttle)."
        )
        @app_commands.guild_only()
        @app_commands.describe(
            reason="Why you need a higher limit",
            requested_limit="The limit you're asking for, e.g. 4 tasks per hour",
            stage="Which stage you work in",
        )
        @app_commands.choices(stage=STAGES)
        async def throttle_request(
            interaction: discord.Interaction,
            reason: app_commands.Range[str, 5, 1000],
            requested_limit: Optional[app_commands.Range[str, 1, 100]] = None,
            stage: Optional[app_commands.Choice[str]] = None,
        ):
            await desk.handle_throttle(
                interaction, reason, requested_limit, stage.value if stage else None
            )

        @app_commands.command(
            name="task-issue",
            description="Report a problem with a task (task ID, what happened, screenshots).",
        )
        @app_commands.guild_only()
        @app_commands.describe(
            task_id="The task ID from the tasking platform",
            description="What happened and what you were doing",
            error_message="The exact error text, if there was one",
            screenshot="Screenshot of the problem",
            screenshot_2="Another screenshot (optional)",
            screenshot_3="Another screenshot (optional)",
        )
        async def task_issue(
            interaction: discord.Interaction,
            task_id: app_commands.Range[str, 1, 100],
            description: app_commands.Range[str, 5, 1000],
            error_message: Optional[app_commands.Range[str, 1, 1000]] = None,
            screenshot: Optional[discord.Attachment] = None,
            screenshot_2: Optional[discord.Attachment] = None,
            screenshot_3: Optional[discord.Attachment] = None,
        ):
            files = [a for a in (screenshot, screenshot_2, screenshot_3) if a is not None]
            await desk.handle_task_issue(interaction, task_id, description, error_message, files)

        tree.add_command(throttle_request)
        tree.add_command(task_issue)
        log.info("[FAQ] Support commands registered: /throttle-request, /task-issue")

    # --- handlers (plain methods so they can be tested without Discord) ---

    async def _request(self, interaction, kind, function, *args):
        key = (kind, interaction.user.id)
        if key in self._inflight or len(self._inflight) >= self.settings.runtime.export_workers:
            await self._private(
                interaction, "A support request is already being processed. Please wait and retry."
            )
            return
        self._inflight.add(key)
        try:
            await function(interaction, *args)
        finally:
            self._inflight.discard(key)

    async def handle_throttle(self, interaction, reason, requested_limit, stage):
        await self._request(
            interaction, "throttle", self._handle_throttle, reason, requested_limit, stage
        )

    async def handle_task_issue(
        self, interaction, task_id, description, error_message, attachments
    ):
        await self._request(
            interaction,
            "task_issue",
            self._handle_task_issue,
            task_id,
            description,
            error_message,
            attachments,
        )

    async def _handle_throttle(
        self, interaction, reason: str, requested_limit: str | None, stage: str | None
    ) -> None:
        if not await self._allowed(interaction, "throttle"):
            return
        fields = {"Reason": _clean(reason, FIELD_LIMIT)}
        if requested_limit:
            fields["Requested limit"] = _clean(requested_limit, 100)
        if stage:
            fields["Stage"] = stage
        await self._submit(
            interaction,
            "throttle",
            "Throttle increase request",
            self.support.throttle_route,
            fields,
            [],
        )

    async def _handle_task_issue(
        self,
        interaction,
        task_id: str,
        description: str,
        error_message: str | None,
        attachments: list,
    ) -> None:
        if not await self._allowed(interaction, "task_issue"):
            return
        task_id = (task_id or "").strip()
        if not TASK_ID_RE.match(task_id):
            await self._private(
                interaction,
                "That doesn't look like a task ID. Copy it from the tasking "
                "platform (letters, numbers and - _ . : / # only).",
            )
            return
        problem = self._check_attachments(attachments)
        if problem:
            await self._private(interaction, problem)
            return
        fields = {
            "Task ID": _clean(task_id, 100),
            "What happened": _clean(description, FIELD_LIMIT),
        }
        if error_message:
            fields["Error message"] = _clean(error_message, FIELD_LIMIT)
        await self._submit(
            interaction,
            "task_issue",
            "Task issue report",
            self.support.task_issue_route,
            fields,
            attachments,
        )

    # --- checks ---

    async def _allowed(self, interaction, kind: str) -> bool:
        if interaction.guild is None:
            await self._private(interaction, "Please use this command in the GAB project channels.")
            return False
        own, parent = channel_keys(interaction.channel)
        if not self.settings.discord.in_scope(*own, *parent):
            await self._private(interaction, "This command only works in the GAB project channels.")
            return False
        key = (kind, interaction.user.id)
        now = self.clock()
        last = self._last_request.get(key)
        wait = self.support.request_cooldown_seconds
        if last is not None and now - last < wait:
            await self._private(
                interaction,
                f"You just sent one. Please wait {int(wait - (now - last)) + 1} "
                "seconds before sending another.",
            )
            return False
        return True

    def _check_attachments(self, attachments: list) -> str | None:
        limit = self.support.max_attachment_mb * 1024 * 1024
        for a in attachments:
            name = (getattr(a, "filename", "") or "").lower()
            ctype = (getattr(a, "content_type", "") or "").lower()
            if not (
                ctype.startswith(("image/", "text/plain")) or name.endswith(ALLOWED_EXTENSIONS)
            ):
                return f"{a.filename}: please attach screenshots (PNG, JPG, GIF, WEBP) or a .txt/.log file."
            if (getattr(a, "size", 0) or 0) > limit:
                return f"{a.filename} is larger than {self.support.max_attachment_mb} MB."
        return None

    # --- delivery ---

    def _requests_channel(self, guild):
        wanted = self.support.requests_channel or self.settings.discord.unanswered_channel
        return find_text_channel(guild, wanted)

    async def _submit(
        self, interaction, kind: str, title: str, route: str, fields: dict, attachments: list
    ) -> None:
        contact = self.support.contact(route)
        target = self._requests_channel(interaction.guild)
        if target is None:
            log.warning(
                "[FAQ] Support requests channel not found; %s from %s not delivered",
                kind,
                interaction.user,
            )
            await self._private(
                interaction,
                f"Sorry, I couldn't send that to the team right now. Please contact "
                f"{contact.name} ({contact.label}) directly.",
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        own, parent = channel_keys(interaction.channel)
        role = self.settings.discord.role_for_channel(*own, *parent)

        embed = discord.Embed(title=title, color=discord.Color.blurple())
        embed.add_field(
            name="Requested by",
            value=f"{interaction.user.mention} ({interaction.user})",
            inline=True,
        )
        embed.add_field(
            name="Where", value=getattr(interaction.channel, "mention", "?"), inline=True
        )
        embed.add_field(name="Role", value=role, inline=True)
        embed.add_field(name="Route to", value=f"{contact.name} ({contact.label})", inline=False)
        for name, value in fields.items():
            embed.add_field(name=name, value=value or "(empty)", inline=False)
        if attachments:
            embed.add_field(
                name="Attachments",
                value=_clean(", ".join(a.filename for a in attachments), FIELD_LIMIT),
                inline=False,
            )
        embed.set_footer(text=f"GAB support request | {kind} | from {interaction.user.id}")

        files = []
        for a in attachments:  # re-uploaded so they don't depend on Discord's expiring links
            try:
                if a.filename.lower().endswith((".txt", ".log")):
                    text = (await a.read()).decode("utf-8", errors="replace")
                    files.append(
                        discord.File(
                            io.BytesIO(redact_secrets(text).encode("utf-8")), filename=a.filename
                        )
                    )
                else:
                    files.append(await a.to_file())
            except discord.HTTPException:
                log.warning("[FAQ] Couldn't copy attachment %s", getattr(a, "filename", "?"))
        ping = contact.mention or None
        try:
            await target.send(
                content=ping,
                embed=embed,
                files=files,
                allowed_mentions=allowed_mentions(ping or ""),
            )
        except discord.HTTPException:
            log.exception(
                "[FAQ] Couldn't post the %s card to #%s", kind, getattr(target, "name", target)
            )
            await interaction.followup.send(
                f"Sorry, I couldn't send that to the team. Please contact "
                f"{contact.name} ({contact.label}) directly.",
                ephemeral=True,
            )
            return

        self._last_request[(kind, interaction.user.id)] = self.clock()
        try:
            await asyncio.to_thread(
                self.question_log.record_request,
                kind=kind,
                channel=str(getattr(interaction.channel, "id", "")),
                user=str(interaction.user.id),
                role=role,
                route=route,
                fields=fields,
                attachments=[a.filename for a in attachments],
            )
        except OSError:
            log.exception("[FAQ] Support request delivered but could not be logged")
        what = "throttle increase request" if kind == "throttle" else "task issue report"
        await interaction.followup.send(
            f"Thanks, your {what} was sent to {contact.name} ({contact.label}). "
            "They'll follow up with you.",
            ephemeral=True,
        )

    @staticmethod
    async def _private(interaction, text: str) -> None:
        await interaction.response.send_message(text, ephemeral=True)
