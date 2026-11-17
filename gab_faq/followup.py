"""Durable Discord follow-up tracking: cards, persisted ticket state, incremental history cursors, and retryable reminders."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from weakref import WeakValueDictionary

import discord
from discord.ext import tasks

from .config import FollowupSettings
from .discord_common import find_text_channel
from .operations import Metrics
from .redact import redact_secrets, scrub_mentions
from .tickets import Ticket, TicketStore

if TYPE_CHECKING:
    from .discord_answers import FaqAnswerer

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30), "IST")
FOOTER_PREFIX = "GAB FAQ bot"
FOOTER_RE = re.compile(r"question (\d+)/(\d+) \| asker (\d+) \| status: (\w+)")
LINK_RE = re.compile(r"\((https://\S+)\)")
COLORS = {
    "open": discord.Color.orange(),
    "answered": discord.Color.green(),
    "reminded": discord.Color.red(),
}
DISCORD_LIMIT = 2000
# The reminder may tag the team (a role or people), but never @everyone / @here.
REMINDER_MENTIONS = discord.AllowedMentions(everyone=False, roles=True, users=True)


def card_footer(channel_id: int, message_id: int, asker_id: int, status: str = "open") -> str:
    return f"{FOOTER_PREFIX} | question {channel_id}/{message_id} | asker {asker_id} | status: {status}"


@dataclass(frozen=True)
class Card:
    """What the bot reads back from a card it posted."""

    channel_id: int
    message_id: int
    asker_id: int
    status: str
    fields: dict
    posted_at: datetime

    @property
    def link(self) -> str | None:
        match = LINK_RE.search(self.fields.get("Reply to them", ""))
        return match.group(1) if match else None


def read_card(message) -> Card | None:
    if not message.embeds:
        return None
    embed = message.embeds[0]
    footer = getattr(embed.footer, "text", None) or ""
    match = FOOTER_RE.search(footer) if footer.startswith(FOOTER_PREFIX) else None
    if not match:
        return None
    return Card(
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        match.group(4),
        {f.name: f.value for f in embed.fields},
        message.created_at,
    )


def with_status(message, status: str, note: tuple[str, str] | None = None) -> discord.Embed:
    """A copy of the card's embed with a new status (colour + footer) and an optional extra field."""
    card = read_card(message)
    embed = discord.Embed.from_dict(message.embeds[0].to_dict())
    embed.color = COLORS[status]
    embed.set_footer(text=card_footer(card.channel_id, card.message_id, card.asker_id, status))
    if note:
        embed.add_field(name=note[0], value=note[1][:1024], inline=False)
    return embed


def _plain(text: str) -> str:
    """'<@123> (sam)' -> 'sam', so the reminder doesn't ping the freelancer."""
    match = re.search(r"\(([^)]+)\)\s*$", text or "")
    return match.group(1) if match else re.sub(r"<@!?\d+>", "", text or "").strip() or "someone"


def build_reminder(
    cards: list[tuple[Card, str]], after_minutes: int, mention: str = ""
) -> list[str]:
    """The reminder posted in Discord, as one or more messages under Discord's 2000-character limit.
    `cards` pairs each card with the link to the card message."""
    n = len(cards)
    head = (
        f"{mention + ' ' if mention else ''}{n} question{'s have' if n != 1 else ' has'} been waiting "
        f"over {after_minutes} minutes with no reply. Please pick {'them' if n != 1 else 'it'} up:"
    )
    items = []
    for i, (card, card_link) in enumerate(cards, 1):
        f = card.fields
        question = scrub_mentions(
            redact_secrets(f.get("Question", "(question not available)"))
        ).replace("\n", " ")
        if len(question) > 300:
            question = question[:297] + "..."
        asked = card.posted_at.astimezone(IST).strftime("%I:%M %p IST")
        where = card.link or card_link
        items.append(
            f'{i}. "{question}" from {_plain(f.get("Asked by", ""))} ({f.get("Role", "unknown")}), '
            f"asked {asked}\n   Reply here: {where}"
        )
    tail = 'Replies are noticed automatically; otherwise click "Mark as answered" on the card.'
    messages, current = [], head
    for item in items:
        if len(current) + len(item) + 2 > DISCORD_LIMIT - 100:
            messages.append(current)
            current = "(continued)"
        current += "\n" + item
    messages.append(current + "\n" + tail)
    return messages


# --- Buttons. Their custom_ids are fixed so they keep working after the bot restarts. ---


class CardView(discord.ui.View):
    """The button on each card in the unanswered-questions channel."""

    def __init__(self, followup: Followup, answered: bool = False):
        super().__init__(timeout=None)
        self.followup = followup
        if answered:
            self.mark_answered.disabled = True
            self.mark_answered.label = "Answered"

    @discord.ui.button(
        label="Mark as answered",
        style=discord.ButtonStyle.success,
        custom_id="gab_faq:mark_answered",
    )
    async def mark_answered(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.followup.on_mark_answered(interaction)


class ReplyView(discord.ui.View):
    """The button under the bot's answers."""

    def __init__(self, followup: Followup, sent: bool = False):
        super().__init__(timeout=None)
        self.followup = followup
        if sent:
            self.ask_person.disabled = True
            self.ask_person.label = "Sent to the team"

    @discord.ui.button(
        label="Didn't help? Ask a person",
        style=discord.ButtonStyle.secondary,
        custom_id="gab_faq:ask_person",
    )
    async def ask_person(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.followup.on_ask_person(interaction)


class Followup:
    def __init__(self, answerer: FaqAnswerer, settings: FollowupSettings):
        self.answerer = answerer
        self.bot = answerer.bot
        self.settings = settings
        self.tickets = TicketStore(answerer.question_log.log_dir)
        self.metrics = getattr(self.bot, "metrics", None) or Metrics()
        self._loop: tasks.Loop | None = None
        self._escalation_locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()
        self._delivered: OrderedDict[int, None] = OrderedDict()

    def card_view(self) -> CardView:
        return CardView(self)

    def reply_view(self) -> ReplyView:
        return ReplyView(self)

    async def start(self) -> None:
        """Called during application setup: makes old buttons work again and starts the checks."""
        self.bot.add_view(CardView(self))
        self.bot.add_view(ReplyView(self))
        if self._loop is None:
            self._loop = tasks.loop(minutes=self.settings.check_every_minutes)(self.check_once)
            self._loop.start()
            log.info(
                "[FAQ] Follow-up checks every %d min; unanswered after %d min -> reminder in %s%s",
                self.settings.check_every_minutes,
                self.settings.after_minutes,
                "#" + self.settings.reminder_channel
                if self.settings.reminder_channel
                else "the unanswered-questions channel",
                f" tagging {self.settings.reminder_mention}"
                if self.settings.reminder_mention
                else "",
            )

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.cancel()

    async def close(self) -> None:
        self.stop()
        task = self._loop.get_task() if self._loop else None
        if task and task is not asyncio.current_task():
            await asyncio.gather(task, return_exceptions=True)

    # --- the periodic check ---

    async def check_once(self) -> None:
        if hasattr(self.bot, "wait_until_ready"):
            await self.bot.wait_until_ready()
        try:
            await self._check()
        except Exception:
            log.exception("[FAQ] Follow-up check failed; will try again next time")

    async def track(self, message, channel=None) -> None:
        card = read_card(message)
        channel = channel or getattr(message, "channel", None)
        if card is None or channel is None:
            return
        await asyncio.to_thread(
            self.tickets.record,
            Ticket(
                card.channel_id,
                card.message_id,
                card.asker_id,
                channel.id,
                message.id,
                card.posted_at.timestamp(),
                card.status,
            ),
        )

    async def sync_channel(self, channel) -> bool:
        """Incremental migration/reconciliation, with a persisted forward cursor."""
        key = f"cards:{channel.id}"
        cursor = await asyncio.to_thread(self.tickets.cursor, key)
        seen = 0
        async for message in channel.history(
            limit=self.settings.history_batch_size,
            after=discord.Object(id=cursor) if cursor else None,
            oldest_first=True,
        ):
            if message.author == self.bot.user:
                await self.track(message, channel)
            await asyncio.to_thread(self.tickets.advance, key, message.id)
            seen += 1
        return seen < self.settings.history_batch_size

    async def _check(self) -> None:
        now = datetime.now(timezone.utc)
        for channel in self._card_channels():
            try:
                await self.sync_channel(channel)
            except discord.HTTPException:
                self.metrics.add("gab_ticket_scan_failures_total")
                log.exception("[FAQ] Could not index staff channel %s", channel.id)
        due = {}
        for ticket in await asyncio.to_thread(self.tickets.pending, self.settings.batch_size):
            await asyncio.to_thread(self.tickets.touch, ticket, now.timestamp())
            try:
                channel = await self._channel(ticket.staff_channel_id)
                message = await channel.fetch_message(ticket.staff_message_id)
                card = read_card(message)
                me = getattr(self.bot, "user", None)
                if card is not None and me is not None and message.author.id != me.id:
                    # Posted by another bot (e.g. a different bot used the same output folder).
                    # Discord won't let us edit it, so stop tracking it instead of retrying forever.
                    log.warning(
                        "[FAQ] Staff card for question %s was posted by another bot; not tracked",
                        ticket.message_id,
                    )
                    card = None
                if card is None:
                    await asyncio.to_thread(
                        self.tickets.status, ticket.channel_id, ticket.message_id, "missing"
                    )
                    self.metrics.add("gab_ticket_missing_total")
                    continue
                if card.status == "answered":
                    await asyncio.to_thread(
                        self.tickets.status, card.channel_id, card.message_id, "answered"
                    )
                    continue
                responder = await self._human_reply(card)
                if responder is not None:
                    await message.edit(
                        embed=with_status(
                            message, "answered", ("Answered", f"{responder} replied in Discord")
                        ),
                        view=CardView(self, answered=True),
                    )
                    await asyncio.to_thread(
                        self.tickets.status, card.channel_id, card.message_id, "answered"
                    )
                    self.metrics.add("gab_tickets_resolved_total")
                    continue
                if ticket.status == "reminded" and card.status != "reminded":
                    await message.edit(embed=with_status(message, "reminded"))
                if (
                    ticket.status == "open"
                    and now.timestamp() - ticket.posted_at >= self.settings.after_minutes * 60
                ):
                    due.setdefault(channel.id, (channel, []))[1].append((message, card))
            except discord.NotFound:
                await asyncio.to_thread(
                    self.tickets.status, ticket.channel_id, ticket.message_id, "missing"
                )
                self.metrics.add("gab_ticket_missing_total")
                log.error("[FAQ] Staff card missing for question %s", ticket.message_id)
            except discord.HTTPException:
                self.metrics.add("gab_ticket_check_failures_total")
                log.exception(
                    "[FAQ] Could not check question %s; retained for retry", ticket.message_id
                )
        for channel, cards in due.values():
            await self._remind(channel, cards)
        counts = await asyncio.to_thread(self.tickets.counts)
        self.metrics.set("gab_tickets_pending", counts.get("open", 0) + counts.get("reminded", 0))

    async def _remind(self, card_channel, due: list[tuple[discord.Message, Card]]) -> None:
        target = self._reminder_channel(card_channel)
        # Persist each successfully sent batch before editing UI cards. An edit
        # failure cannot cause that batch's reminder to be sent again next run.
        batches, current = [], []
        for item in due:
            candidate = current + [item]
            texts = build_reminder(
                [(c, m.jump_url) for m, c in candidate],
                self.settings.after_minutes,
                self.settings.reminder_mention,
            )
            if len(texts) > 1 and current:
                batches.append(current)
                current = [item]
            else:
                current = candidate
        if current:
            batches.append(current)
        for batch in batches:
            text = build_reminder(
                [(c, m.jump_url) for m, c in batch],
                self.settings.after_minutes,
                self.settings.reminder_mention,
            )[0]
            try:
                await target.send(text, allowed_mentions=REMINDER_MENTIONS)
            except discord.HTTPException:
                self.metrics.add("gab_reminder_failures_total")
                log.exception("[FAQ] Reminder delivery failed; retained for retry")
                continue
            for message, card in batch:
                await asyncio.to_thread(
                    self.tickets.status, card.channel_id, card.message_id, "reminded"
                )
                try:
                    await message.edit(
                        embed=with_status(
                            message,
                            "reminded",
                            (
                                "Reminder",
                                f"Unanswered for over {self.settings.after_minutes} min: team reminded",
                            ),
                        )
                    )
                except discord.HTTPException:
                    log.warning(
                        "[FAQ] Reminder delivered but card %s could not be updated", message.id
                    )
            self.metrics.add("gab_reminders_sent_total")

    def _reminder_channel(self, card_channel):
        """Where reminders go: gab_faq.followup.reminder_channel in the same server, else the
        unanswered-questions channel itself."""
        wanted = self.settings.reminder_channel
        if not wanted:
            return card_channel
        guild = getattr(card_channel, "guild", None)
        found = find_text_channel(guild, wanted)
        if found is None:
            log.warning(
                "[FAQ] Reminder channel %r not found; posting in #%s instead",
                wanted,
                getattr(card_channel, "name", card_channel),
            )
        return found or card_channel

    def _card_channels(self) -> list:
        seen, out = set(), []
        for guild in self.bot.guilds:
            channel = self.answerer._find_unanswered_channel(guild)
            if channel is not None and channel.id not in seen:
                seen.add(channel.id)
                out.append(channel)
        return out

    async def _channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)
        return channel

    async def _human_reply(self, card: Card) -> str | None:
        def counts(message):
            return not message.author.bot and message.author.id != card.asker_id

        async def scan(channel, in_thread):
            key = f"replies:{card.channel_id}:{card.message_id}:{channel.id}"
            cursor = await asyncio.to_thread(self.tickets.cursor, key) or card.message_id
            async for message in channel.history(
                limit=self.settings.reply_batch_size,
                after=discord.Object(id=cursor),
                oldest_first=True,
            ):
                if counts(message) and (
                    in_thread
                    or (message.reference and message.reference.message_id == card.message_id)
                ):
                    return str(message.author)
                await asyncio.to_thread(self.tickets.advance, key, message.id)
            return None

        channel = await self._channel(card.channel_id)
        try:
            thread = await self._channel(card.message_id)
        except discord.NotFound:
            thread = None
        if isinstance(thread, discord.Thread):
            if person := await scan(thread, True):
                return person
        return await scan(channel, isinstance(channel, discord.Thread))

    # --- buttons ---

    async def on_mark_answered(self, interaction: discord.Interaction) -> None:
        message = interaction.message
        if message is None or read_card(message) is None:
            await interaction.response.send_message("This isn't a question card.", ephemeral=True)
            return
        embed = with_status(
            message, "answered", ("Answered", f"Marked as answered by {interaction.user}")
        )
        await interaction.response.edit_message(embed=embed, view=CardView(self, answered=True))
        card = read_card(message)
        await asyncio.to_thread(self.tickets.status, card.channel_id, card.message_id, "answered")

    async def on_ask_person(self, interaction: discord.Interaction) -> None:
        reply = interaction.message
        ref = reply.reference if reply else None
        question = None
        if ref and ref.message_id:
            question = ref.resolved if isinstance(ref.resolved, discord.Message) else None
            if question is None:
                try:
                    question = await reply.channel.fetch_message(ref.message_id)
                except discord.HTTPException:
                    question = None
        if question is None:
            await interaction.response.send_message(
                "I couldn't find the original question. Please ask the team directly.",
                ephemeral=True,
            )
            return
        if interaction.user.id != question.author.id:
            await interaction.response.send_message(
                "Only the person who asked can use this button. Ask your own question and I'll answer it.",
                ephemeral=True,
            )
            return
        # Acknowledge promptly without disabling the retry button before delivery succeeds.
        await interaction.response.defer(ephemeral=True, thinking=True)
        lock = self._escalation_locks.setdefault(question.id, asyncio.Lock())
        async with lock:
            if question.id in self._delivered:
                await interaction.followup.send(
                    "Your question has already been sent to the team.", ephemeral=True
                )
                return
            delivered = await self.answerer.escalate(
                question, reply.content, reason="the asker said the FAQ answer didn't help"
            )
            if not delivered:
                await interaction.followup.send(
                    "I couldn't send your question to the team. Please try this button again or contact the team directly.",
                    ephemeral=True,
                )
                return
            self._delivered[question.id] = None
            if len(self._delivered) > 4096:
                self._delivered.popitem(last=False)
            try:
                await reply.edit(view=ReplyView(self, sent=True))
            except discord.HTTPException:
                log.warning(
                    "[FAQ] Question %s delivered, but could not update its button", question.id
                )
            await interaction.followup.send(
                "Thanks, I've passed your question to the team.", ephemeral=True
            )
