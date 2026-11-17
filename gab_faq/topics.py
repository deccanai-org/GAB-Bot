"""Topic tracker: every message in a GAB channel about one of a few staff-only topics (task limit /
throttle, payment, environment reset, not added to the phase, assessments) is collected into one
staff channel, so the team sees in one place who is asking for what.

The tracker only reads and posts to the tracker channel. It never replies to the person, never pings
anyone and never changes how the bot answers. Topic detection is plain code (regular expressions plus
optional extra keywords from config.yaml); no AI is involved.

One card per person per topic: if the same person raises the same topic again within window_hours,
their existing card is updated ("Times raised", latest message link) instead of posting a new one.
That memory is kept in the process, so after a restart the next message starts a new card.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

import discord

from .discord_common import allowed_mentions, channel_keys, find_text_channel, strip_bot_call
from .policy import is_payment_matter
from .redact import redact_secrets
from .routing import THROTTLE_RE

log = logging.getLogger(__name__)

FIELD_LIMIT = 1024

# --- Detection: one rule per topic, in display order ---

MORE_TASKS_RE = re.compile(
    r"\b(more|additional|extra)\s+tasks\b|\btask\s+(limit|count)\b|\blimit\s+(reached|exhausted|over)\b",
    re.IGNORECASE,
)
RESET_RE = re.compile(r"\bre-?set(s|ting)?\b|\breset\s*id\b", re.IGNORECASE)
# "not", "haven't", "havent", "didn’t" (curly apostrophe), "never".
NEG = r"(?:\bnot|n['’]t|\b(?:havent|hasnt|hadnt|didnt|dont|doesnt|wasnt|werent|isnt|arent|cant|never))"
# "Why am I not added to Phase 7?", "please add me", "I didn't get access to the phase 7 section".
NOT_ADDED_RE = re.compile(
    NEG
    + r"\s+(?:i\s+|we\s+)?(?:been\s+|yet\s+|be\s+|even\s+)?(?:added|onboarded|selected|invited|included"
    r"|shortlisted|moved|migrated|assigned\s+to\s+(?:the\s+)?(?:phase|project))\b"
    r"|\badd\s+me\b",
    re.IGNORECASE,
)
ACCESS_RE = re.compile(
    r"\b(?:no|without)\s+(?:the\s+|any\s+)?(?:access|role|invite|invitation)\b"
    r"|" + NEG + r"\s+(?:have|get|got|getting|received|been\s+given|given)\s+(?:the\s+|any\s+)?"
    r"(?:access|role|invite|invitation)\b"
    r"|(?:\bcannot|can['’]?t|\bunable\s+to|\bnot\s+able\s+to)\s+(?:see|find|access)\s+(?:the\s+)?"
    r"(?:phase|section|channels?)\b",
    re.IGNORECASE,
)
ACCESS_CONTEXT_RE = re.compile(
    r"\b(phase|project|gab|channels?|section|server|role|cosmo|platform)\b", re.IGNORECASE
)
# "assessment", "assesment", "asessment"; qualification / screening tests.
ASSESSMENT_RE = re.compile(
    r"\bass?ess?ments?\b|\b(qualification|qualifying|screening|entrance|onboarding)\s+(test|task|round|quiz)s?\b"
    r"|\btest\s+results?\b",
    re.IGNORECASE,
)


def _throttle(text: str) -> bool:
    return bool(THROTTLE_RE.search(text) or MORE_TASKS_RE.search(text))


def _not_added(text: str) -> bool:
    if NOT_ADDED_RE.search(text):
        return True
    return bool(ACCESS_RE.search(text) and ACCESS_CONTEXT_RE.search(text))


@dataclass(frozen=True)
class Topic:
    key: str
    label: str  # shown on the card, e.g. "Throttle / task limit"
    color: int
    rule: object  # text -> bool


TOPICS = (
    Topic("throttle", "Throttle / task limit", 0xE67E22, _throttle),
    Topic("payment", "Payment", 0x2ECC71, is_payment_matter),
    Topic("reset", "Environment reset", 0x3498DB, lambda t: bool(RESET_RE.search(t))),
    Topic("not_added", "Not added to the phase", 0x9B59B6, _not_added),
    Topic("assessment", "Assessments", 0xF1C40F, lambda t: bool(ASSESSMENT_RE.search(t))),
)
TOPIC_KEYS = tuple(t.key for t in TOPICS)
_BY_KEY = {t.key: t for t in TOPICS}


@dataclass(frozen=True)
class TopicSettings:
    """gab_faq.topic_tracker in config.yaml."""

    enabled: bool = False
    channel: str = ""  # staff channel (name or ID) every topic goes to
    channels: dict = field(default_factory=dict)  # optional {topic: channel} overrides
    topics: tuple = TOPIC_KEYS  # which topics are collected
    extra_keywords: dict = field(default_factory=dict)  # {topic: (keyword, ...)}
    window_hours: float = 24.0  # same person + same topic inside this window: update the card

    @classmethod
    def parse(cls, section: dict | None) -> TopicSettings:
        section = section or {}
        d = cls()
        topics = tuple(section.get("topics") or TOPIC_KEYS)
        unknown = [t for t in topics if t not in TOPIC_KEYS]
        channels = {
            str(k): str(v).strip().lstrip("#")
            for k, v in (section.get("channels") or {}).items()
            if v
        }
        extras = {
            str(k): tuple(str(w).strip().lower() for w in (v or []) if str(w).strip())
            for k, v in (section.get("extra_keywords") or {}).items()
        }
        unknown += [k for k in list(channels) + list(extras) if k not in TOPIC_KEYS]
        if unknown:
            raise ValueError(
                f"gab_faq.topic_tracker: unknown topic(s) {sorted(set(unknown))}; use {TOPIC_KEYS}"
            )
        window = float(section.get("window_hours", d.window_hours))
        if window <= 0:
            raise ValueError("gab_faq.topic_tracker.window_hours must be more than 0")
        return cls(
            enabled=bool(section.get("enabled", False)),
            channel=str(section.get("channel") or "").strip().lstrip("#"),
            channels=channels,
            topics=topics,
            extra_keywords=extras,
            window_hours=window,
        )

    def destination(self, topic: str) -> str:
        return self.channels.get(topic) or self.channel


def match_topics(text: str, settings: TopicSettings | None = None) -> list[str]:
    """The topics a message is about, in TOPICS order. Empty for most messages."""
    settings = settings or TopicSettings(enabled=True)
    text = text or ""
    low = text.lower()
    found = []
    for topic in TOPICS:
        if topic.key not in settings.topics:
            continue
        extra = settings.extra_keywords.get(topic.key, ())
        if topic.rule(text) or any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", low) for w in extra):
            found.append(topic.key)
    return found


def _clip(text: str, limit: int = FIELD_LIMIT) -> str:
    text = (text or "").strip() or "(empty)"
    return text if len(text) <= limit else text[: limit - 3] + "..."


def build_card(
    topics: list[str],
    *,
    asker: str,
    where: str,
    text: str,
    jump_url: str,
    count: int,
    first: int,
    last: int,
) -> discord.Embed:
    labels = [_BY_KEY[t].label for t in topics]
    embed = discord.Embed(title=" + ".join(labels), color=_BY_KEY[topics[0]].color)
    embed.add_field(name="Who", value=_clip(asker, 256), inline=True)
    embed.add_field(name="Where", value=_clip(where, 256), inline=True)
    embed.add_field(name="Times raised", value=str(count), inline=True)
    embed.add_field(name="Latest message", value=_clip(text), inline=False)
    embed.add_field(name="Open it", value=f"[Jump to message]({jump_url})", inline=True)
    embed.add_field(name="First / last", value=f"<t:{first}:f> / <t:{last}:R>", inline=True)
    embed.set_footer(text="Topic tracker: " + ", ".join(topics))
    return embed


@dataclass
class _Open:
    card: object  # the posted discord.Message
    topics: list
    count: int
    first: int
    last: float


class TopicTracker:
    def __init__(self, bot, settings: TopicSettings, platform, clock=time.time, skip=()):
        self.bot = bot
        self.settings = settings
        self.platform = platform  # PlatformSettings: which channels are in scope
        # Other staff channels (names or IDs) whose messages are never tracked, e.g. the
        # unanswered-questions and reminder channels: staff discussing a card there is not a request.
        self.skip = tuple(skip)
        self.clock = clock
        self._open: dict[tuple, _Open] = {}
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self.settings.enabled and bool(self.settings.channel or self.settings.channels)

    def _staff_channel_names(self) -> set[str]:
        names = {self.settings.channel, *self.settings.channels.values(), *self.skip}
        return {n.casefold() for n in names if n}

    async def observe(self, message) -> bool:
        """Post or update a tracker card if the message is about a tracked topic. Never raises."""
        try:
            return await self._observe(message)
        except Exception:
            log.exception("[Topics] Could not track message %s", getattr(message, "id", "?"))
            return False

    async def _observe(self, message) -> bool:
        if not self.enabled or message.guild is None or message.author.bot:
            return False
        own, parent = channel_keys(message.channel)
        if not self.platform.in_scope(*own, *parent):
            return False
        names = {k.casefold() for k in own + parent}
        if names & self._staff_channel_names():
            return False
        user = getattr(self.bot, "user", None)
        text = strip_bot_call(message.content, user, message.guild) if user else message.content
        topics = match_topics(text, self.settings)
        if not topics:
            return False
        by_channel: dict[str, list[str]] = {}
        for topic in topics:
            by_channel.setdefault(self.settings.destination(topic), []).append(topic)
        posted = False
        for wanted, group in by_channel.items():
            target = find_text_channel(message.guild, wanted)
            if target is None:
                log.warning("[Topics] Tracker channel %r not found", wanted)
                continue
            posted |= await self._post(target, group, message, redact_secrets(text))
        return posted

    async def _post(self, target, topics: list[str], message, text: str) -> bool:
        now = self.clock()
        window = self.settings.window_hours * 3600
        key = (message.guild.id, target.id, message.author.id, tuple(topics))
        async with self._lock:
            # Forget cards whose window has passed.
            for k in [k for k, v in self._open.items() if now - v.last > window]:
                del self._open[k]
            where = getattr(message.channel, "mention", "") or str(message.channel)
            asker = f"{message.author.mention} ({message.author})"
            existing = self._open.get(key)
            if existing is not None:
                existing.count += 1
                existing.last = now
                embed = build_card(
                    topics,
                    asker=asker,
                    where=where,
                    text=text,
                    jump_url=message.jump_url,
                    count=existing.count,
                    first=existing.first,
                    last=int(now),
                )
                try:
                    await existing.card.edit(embed=embed, allowed_mentions=allowed_mentions())
                    return True
                except discord.HTTPException:
                    log.warning("[Topics] Could not update a tracker card; posting a new one")
                    del self._open[key]
            embed = build_card(
                topics,
                asker=asker,
                where=where,
                text=text,
                jump_url=message.jump_url,
                count=1,
                first=int(now),
                last=int(now),
            )
            try:
                card = await target.send(embed=embed, allowed_mentions=allowed_mentions())
            except discord.HTTPException:
                log.exception(
                    "[Topics] Couldn't post to #%s (does the bot have Send Messages + Embed Links?)",
                    getattr(target, "name", target),
                )
                return False
            self._open[key] = _Open(card, topics, 1, int(now), now)
            log.info("[Topics] %s raised %s in %s", message.author, topics, where)
            return True
