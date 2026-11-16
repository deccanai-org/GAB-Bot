"""Discord FAQ routing, conversation context, replies, and confirmed staff-card delivery."""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from weakref import WeakValueDictionary

import discord

from .config import Settings, load_environment, load_settings
from .contracts import HELPFUL_OUTCOMES, Answer
from .discord_common import (
    allowed_mentions,
    calls_bot,
    channel_keys,
    find_text_channel,
    notify_contact,
    strip_bot_call,
)
from .discord_common import readable_channels as readable_channels
from .discord_common import strip_mentions as strip_mentions
from .engine import build_engine, describe
from .followup import Followup, card_footer
from .knowledge import KnowledgeBase
from .model_limits import answer_as_user
from .operations import BoundedAnswers, Busy
from .redact import redact_secrets
from .replies import QuestionLog, format_reply, split_message
from .routing import classify, hint_for

log = logging.getLogger(__name__)

DISCORD_LIMIT = 2000
GREETING = (
    "Hi! I answer questions about the GAB project's FAQ: model selection, screen recording, debug "
    "JSON, turn counts, QC checks and so on. Mention me with your question, e.g. "
    '"@Gigi which model do I use?". To ask for a higher task limit use /throttle-request, and to '
    "report a problem with a task use /task-issue."
)
FIELD_LIMIT = 1024  # Discord's limit for one embed field


def route(
    *,
    is_dm: bool,
    mentioned: bool,
    in_answer_channel: bool,
    in_answer_thread: bool,
    answer_in_dms: bool = False,
    in_scope: bool = True,
) -> str | None:
    """ "answer", "thread_followup" (answer only if the bot replied last), or None (ignore)."""
    if is_dm:
        return "answer" if answer_in_dms else None
    if not in_scope:
        return None
    if mentioned or in_answer_channel:
        return "answer"
    if in_answer_thread:
        return "thread_followup"
    return None


def _clip(text: str, limit: int = FIELD_LIMIT) -> str:
    text = (text or "").strip() or "(empty)"
    return text if len(text) <= limit else text[: limit - 3] + "..."


def build_unanswered_embed(
    *,
    asker: str,
    where: str,
    role: str,
    question: str,
    answer: Answer,
    jump_url: str | None,
    footer: str = "",
    route_to: str = "",
) -> discord.Embed:
    """The card posted to the unanswered-questions channel. The footer holds the IDs and status the
    follow-up checks read back (see followup.py)."""
    why = answer.outcome.replace("_", " ")
    if answer.escalation_reason:
        why += f": {answer.escalation_reason}"
    embed = discord.Embed(title="Question the bot couldn't answer", color=discord.Color.orange())
    embed.add_field(name="Asked by", value=_clip(asker, 256), inline=True)
    embed.add_field(name="Where", value=_clip(where, 256), inline=True)
    embed.add_field(name="Role", value=role, inline=True)
    if route_to:
        embed.add_field(name="Route to", value=_clip(route_to, 256), inline=False)
    embed.add_field(name="Question", value=_clip(question), inline=False)
    embed.add_field(name="Why", value=_clip(why), inline=False)
    embed.add_field(name="Bot replied", value=_clip(answer.text), inline=False)
    if jump_url:
        embed.add_field(name="Reply to them", value=f"[Jump to message]({jump_url})", inline=False)
    if footer:
        embed.set_footer(text=footer)
    return embed


class FaqAnswerer:
    def __init__(self, bot: discord.Client, settings: Settings, brain, question_log: QuestionLog):
        self.bot = bot
        self.settings = settings
        self.brain = brain
        self.question_log = question_log
        limits = settings.runtime
        self.executor = BoundedAnswers(
            workers=limits.answer_workers,
            capacity=limits.answer_capacity,
            timeout=limits.answer_timeout,
            per_user=limits.user_requests_per_minute,
            metrics=getattr(bot, "metrics", None),
        )
        self._delivery_locks = WeakValueDictionary()
        self.followup = Followup(self, settings.followup)

    async def start(self) -> None:
        """Called during application setup."""
        await self.followup.start()

    async def handle(self, message: discord.Message) -> bool:
        """Answer the message if it's for the bot. Returns True if it answered. Never raises: a
        problem here must not stop the rest of the bot."""
        try:
            return await self._handle(message)
        except Exception:
            log.exception("[FAQ] Failed to answer message %s", message.id)
            return False

    async def _handle(self, message: discord.Message) -> bool:
        if message.author.bot or self.bot.user is None:
            return False
        channel = message.channel
        is_thread = isinstance(channel, discord.Thread)
        own, parent = channel_keys(channel)
        platform = self.settings.discord
        decision = route(
            is_dm=message.guild is None,
            mentioned=calls_bot(message, self.bot.user),
            in_answer_channel=not is_thread and platform.is_answer_channel(*own),
            in_answer_thread=is_thread and platform.is_answer_channel(*parent),
            answer_in_dms=platform.answer_in_dms,
            in_scope=platform.in_scope(*own, *parent),
        )
        if decision is None:
            return False
        if decision == "thread_followup":
            last = [m async for m in channel.history(limit=1, before=message)]
            if not last or last[0].author != self.bot.user:
                return False  # a person is handling this thread

        question = strip_bot_call(message.content, self.bot.user, message.guild)
        if not question:
            await message.reply(GREETING, allowed_mentions=allowed_mentions())
            return True

        role = platform.role_for_channel(*own, *parent)
        async with channel.typing():
            history = await self._history(message)
            try:
                answer = await self.executor.answer(
                    partial(
                        answer_as_user,
                        self.brain,
                        f"discord:{message.author.id}",
                        question,
                        role,
                        history,
                    ),
                    user=str(message.author.id),
                    conversation=f"{channel.id}:{message.author.id}",
                )
            except Busy as error:
                await message.reply(str(error), allowed_mentions=allowed_mentions())
                return False
            except TimeoutError:
                answer = Answer(
                    "I couldn't finish the FAQ lookup in time. A team member can help.",
                    "error",
                    escalation_reason="answer deadline exceeded",
                )
            except Exception:
                # Anything else the engine didn't handle (an AI/API failure, a bug): still reply,
                # and hand the question to the right person instead of going silent.
                log.exception("[FAQ] Answering failed for message %s; escalating it", message.id)
                answer = Answer(
                    "Sorry, I couldn't process that right now. I've flagged it so a team member "
                    "can help you.",
                    "error",
                    escalation_reason="answering failed unexpectedly",
                )
        self._ensure_route(answer, question)
        question = redact_secrets(question)
        delivery_failed = answer.needs_escalation and not await self._post_unanswered(
            message, question, role, answer
        )
        if delivery_failed:
            answer.text = "I couldn't send your question to the team right now. "
            answer.text += (
                "Please try the button below or contact the team directly."
                if message.guild
                else "Please contact the team directly."
            )
        support = self.settings.support
        text = format_reply(
            answer,
            platform.escalation_mention,
            self.settings.environment,
            support=support,
            mentions_allowed=True,
        )
        pings = allowed_mentions(
            platform.escalation_mention if answer.needs_escalation else "",
            support.contact(answer.route).mention
            if answer.needs_escalation and answer.route and support.mention_in_reply
            else "",
        )
        chunks = split_message(text, DISCORD_LIMIT)
        for i, chunk in enumerate(chunks):
            # An answer (FAQ or general guidance) gets a "Didn't help? Ask a person" button under
            # its last part.
            extra = (
                {"view": self.followup.reply_view()}
                if (
                    (answer.outcome in HELPFUL_OUTCOMES or delivery_failed)
                    and i == len(chunks) - 1
                    and message.guild is not None
                )
                else {}
            )
            await message.reply(chunk, allowed_mentions=pings, **extra)
        log.info(
            "[FAQ] #%s %s (%s) → %s %s route=%s",
            getattr(channel, "name", "DM"),
            message.author,
            role,
            answer.outcome,
            answer.sources,
            answer.route or "-",
        )

        question = redact_secrets(
            question
        )  # never keep a pasted password/token in logs or staff cards
        try:
            await asyncio.to_thread(
                self.question_log.record,
                platform="discord",
                channel=str(channel.id),
                user=str(message.author.id),
                role=role,
                question=question,
                answer=answer,
            )
        except OSError:
            log.exception("[FAQ] Could not log question %s", message.id)
        return True

    def _ensure_route(self, answer: Answer, question: str) -> None:
        """Who handles it, if a person is needed: always decided by routing.classify (code). The
        guarded engine already sets it; this also covers any engine that doesn't."""
        if answer.needs_escalation and not answer.route:
            answer.route = classify(question, self.settings.support)
            answer.route_hint = hint_for(question)

    async def _history(self, message: discord.Message) -> list[dict]:
        """Earlier messages in the same conversation, so follow-up questions make sense.

        Least privilege: only messages from this asker and from the bot, only from the channel the
        question was asked in (which the asker can see). Other people's messages, other channels and
        attachments are never passed on."""
        limit = self.settings.max_history_messages
        allowed_authors = {message.author.id, self.bot.user.id}
        channel_id = getattr(message.channel, "id", None)
        earlier: list[discord.Message] = []
        if isinstance(message.channel, (discord.Thread, discord.DMChannel)):
            earlier = [m async for m in message.channel.history(limit=limit * 3, before=message)]
            earlier.reverse()
        elif message.reference and message.reference.message_id:
            ref = message.reference
            while ref and ref.message_id and len(earlier) < limit:
                if getattr(ref, "channel_id", channel_id) != channel_id:
                    break  # a reply pointing into another channel: not followed
                try:
                    parent = (
                        ref.resolved
                        if isinstance(ref.resolved, discord.Message)
                        else await message.channel.fetch_message(ref.message_id)
                    )
                except discord.HTTPException:
                    break
                earlier.insert(0, parent)
                ref = parent.reference
        earlier = [m for m in earlier if getattr(m.author, "id", None) in allowed_authors][-limit:]
        return [
            {
                "role": "assistant" if m.author == self.bot.user else "user",
                "content": strip_bot_call(m.content, self.bot.user, message.guild),
            }
            for m in earlier
        ]

    def _find_unanswered_channel(self, guild: discord.Guild | None):
        return find_text_channel(guild, self.settings.discord.unanswered_channel)

    async def escalate(
        self, question_message: discord.Message, bot_reply: str, reason: str
    ) -> bool:
        """Hand a question the bot already replied to over to the team (the asker clicked
        "Didn't help? Ask a person")."""
        own, parent = channel_keys(question_message.channel)
        role = self.settings.discord.role_for_channel(*own, *parent)
        question = redact_secrets(
            strip_bot_call(question_message.content, self.bot.user, question_message.guild)
        )
        answer = Answer(bot_reply, "needs_human", escalation_reason=reason)
        self._ensure_route(answer, question)
        delivered = await self._post_unanswered(question_message, question, role, answer)
        try:
            await asyncio.to_thread(
                self.question_log.record,
                platform="discord",
                channel=str(question_message.channel.id),
                user=str(question_message.author.id),
                role=role,
                question=question,
                answer=answer,
            )
        except OSError:
            log.exception("[FAQ] Could not log escalation for question %s", question_message.id)
        return delivered

    async def _post_unanswered(
        self, message: discord.Message, question: str, role: str, answer: Answer
    ) -> bool:
        lock = self._delivery_locks.setdefault(message.id, asyncio.Lock())
        async with lock:
            target = self._find_unanswered_channel(message.guild)
            if target is not None:
                try:
                    synced = await self.followup.sync_channel(target)
                    if await asyncio.to_thread(
                        self.followup.tickets.known, message.channel.id, message.id
                    ):
                        return True
                    if not synced:
                        return False  # finish reconciling history before deciding a send is new
                except discord.HTTPException:
                    log.exception("[FAQ] Could not reconcile staff cards before delivery")
                    return False
            return await self._deliver_unanswered(message, question, role, answer)

    async def _deliver_unanswered(
        self, message: discord.Message, question: str, role: str, answer: Answer
    ) -> bool:
        target = self._find_unanswered_channel(message.guild)
        if target is None:
            if self.settings.discord.unanswered_channel:
                log.warning(
                    "[FAQ] Unanswered-questions channel %r not found; question only logged to file",
                    self.settings.discord.unanswered_channel,
                )
            return False
        in_dm = message.guild is None
        contact = self.settings.support.contact(answer.route) if answer.route else None
        embed = build_unanswered_embed(
            asker=f"{message.author.mention} ({message.author})",
            where="Direct message to the bot" if in_dm else message.channel.mention,
            role=role,
            question=redact_secrets(question),
            answer=answer,
            jump_url=None if in_dm else message.jump_url,
            footer=card_footer(message.channel.id, message.id, message.author.id),
            route_to=f"{contact.name} ({contact.label})" if contact else "",
        )
        # The card pings nobody. The routed contact (if a mention is configured) is told by direct
        # message instead; they are pinged in the staff channel only if that DM fails.
        try:
            posted = await target.send(
                embed=embed,
                view=self.followup.card_view(),
                allowed_mentions=allowed_mentions(),
            )
            if posted is not None:
                await self.followup.track(posted, target)
        except discord.HTTPException:
            log.exception(
                "[FAQ] Couldn't post to #%s (does the bot have Send Messages + Embed Links there?)",
                getattr(target, "name", target),
            )
            return False
        await notify_contact(
            self.bot,
            target,
            contact,
            embed=embed,
            card=posted,
            intro=f"A question needs your help ({contact.label})." if contact else "",
        )
        return True


def setup_faq_answers(bot: discord.Client, config_path=None) -> FaqAnswerer | None:
    """Called once by bot.py. Returns None (and logs why) when FAQ answering is switched off or
    its settings are broken, so the rest of the bot (moderation, /export...) keeps running."""
    try:
        return _setup(bot, config_path)
    except Exception:
        log.exception(
            "[FAQ] Answering is OFF: could not start it (check the gab_faq section of "
            "config.yaml and the files in knowledge/current/)"
        )
        return None


def _setup(bot: discord.Client, config_path=None) -> FaqAnswerer | None:
    load_environment()
    settings = load_settings(config_path) if config_path is not None else load_settings()
    if not settings.enabled:
        log.info("[FAQ] Answering is OFF (gab_faq.enabled is false in config.yaml)")
        return None
    if settings.engine == "qwen" and not settings.dashscope_api_key_set:
        log.warning(
            "[FAQ] Answering is OFF: Qwen requires DASHSCOPE_API_KEY; no provider fallback is used"
        )
        return None
    knowledge = KnowledgeBase(settings.knowledge_dir)
    brain = build_engine(settings, knowledge)
    question_log = QuestionLog(settings.log_dir, environment=settings.environment)
    d = settings.discord
    log.info(
        "[FAQ] Answering is ON (%s, %s, %d FAQ files). Only in: %s. Answer channels: %s. "
        "DMs: %s. Unanswered questions go to: %s",
        settings.environment,
        describe(settings),
        len(knowledge.documents),
        sorted(d.only_in) or "anywhere",
        sorted(d.answer_channels) or "none (only @mentions)",
        "yes" if d.answer_in_dms else "no",
        d.unanswered_channel or "nowhere (log file only)",
    )
    answerer = FaqAnswerer(bot, settings, brain, question_log)
    if settings.support.enabled and getattr(bot, "tree", None) is not None:
        from .support import SupportDesk  # imported here: support.py uses this module's helpers

        SupportDesk(bot, settings, question_log).register(bot.tree)
    return answerer
