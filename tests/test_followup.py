"""Follow-up on unanswered questions: cards, the 1-hour check, the Discord reminder, and the two
buttons. Uses stand-in Discord objects; nothing is sent anywhere."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import discord

from gab_faq.brain import Answer
from gab_faq.config import FollowupSettings, Settings, _platform
from gab_faq.discord_answers import FaqAnswerer, build_unanswered_embed
from gab_faq.followup import DISCORD_LIMIT, build_reminder, card_footer, read_card
from gab_faq.replies import QuestionLog

BOT_USER = SimpleNamespace(id=999, bot=True, name="faq-bot")
NOW = datetime.now(timezone.utc)


def run(coro):
    return asyncio.run(coro)


class Person:
    def __init__(self, id, name, bot=False):
        self.id, self.name, self.bot = id, name, bot
        self.mention = f"<@{id}>"

    def __str__(self):
        return self.name


ASKER = Person(42, "sam")
STAFF = Person(7, "priya")


class FakeMessage:
    def __init__(
        self, id, author, content="", embeds=(), created_at=NOW, reference=None, channel=None
    ):
        self.id, self.author, self.content = id, author, content
        self.embeds = list(embeds)
        self.created_at = created_at
        self.reference = reference
        self.channel = channel
        self.guild = SimpleNamespace(id=1) if channel is not None else None
        self.jump_url = f"https://discord.com/channels/1/{getattr(channel, 'id', 0)}/{id}"
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        if "embed" in kwargs:
            self.embeds = [kwargs["embed"]]


class FakeChannel:
    def __init__(self, id, name, messages=()):
        self.id, self.name = id, name
        self.mention = f"<#{id}>"
        self.messages = list(messages)
        self.sent = []

    async def history(self, limit=100, after=None, before=None, oldest_first=False):
        count = 0
        for m in sorted(self.messages, key=lambda item: item.id):
            if limit is not None and count >= limit:
                break
            if isinstance(after, discord.Object) and m.id <= after.id:
                continue
            if isinstance(after, datetime) and m.created_at <= after:
                continue
            count += 1
            yield m

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))
        message = FakeMessage(
            100000 + len(self.messages),
            BOT_USER,
            content or "",
            embeds=[kwargs["embed"]] if kwargs.get("embed") else [],
            channel=self,
        )
        self.messages.append(message)
        return message

    async def fetch_message(self, id):
        found = next((m for m in self.messages if m.id == id), None)
        if found is None:
            return not_found(id)
        return found


def not_found(*_):
    raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "unknown channel")


def card(question_channel_id, question_id, minutes_ago, status="open"):
    embed = build_unanswered_embed(
        asker="<@42> (sam)",
        where=f"<#{question_channel_id}>",
        role="qc",
        question="when is the deadline?",
        answer=Answer(
            "I couldn't find this.", "not_in_faq", escalation_reason="no FAQ entry matches"
        ),
        jump_url=f"https://discord.com/channels/1/{question_channel_id}/{question_id}",
        footer=card_footer(question_channel_id, question_id, ASKER.id, status),
    )
    return FakeMessage(
        5000 + question_id,
        BOT_USER,
        embeds=[embed],
        created_at=NOW - timedelta(minutes=minutes_ago),
    )


def make(tmp_path, cards, question_channel, mention="<@&555>", reminder_channel=""):
    unanswered = FakeChannel(13, "faq-bot-unanswered", cards)
    support_team = FakeChannel(14, "gab-support-team")
    channels = {c.id: c for c in (question_channel, unanswered, support_team)}
    guild = SimpleNamespace(text_channels=[question_channel, unanswered, support_team])
    for c in channels.values():
        c.guild = guild
    bot = SimpleNamespace(
        user=BOT_USER, guilds=[guild], get_channel=channels.get, fetch_channel=_async(not_found)
    )
    settings = Settings(
        enabled=True,
        discord=_platform({"unanswered_channel": "faq-bot-unanswered"}),
        followup=FollowupSettings(
            after_minutes=60, reminder_mention=mention, reminder_channel=reminder_channel
        ),
        log_dir=tmp_path,
    )
    answerer = FaqAnswerer(bot, settings, brain=None, question_log=QuestionLog(tmp_path))
    return answerer.followup, unanswered


def _async(fn):
    async def wrapper(*a, **k):
        return fn(*a, **k)

    return wrapper


def status_of(message):
    return read_card(message).status


def test_footer_round_trip():
    c = card(11, 100, minutes_ago=5)
    info = read_card(c)
    assert (info.channel_id, info.message_id, info.asker_id, info.status) == (11, 100, 42, "open")
    assert info.link == "https://discord.com/channels/1/11/100"
    assert read_card(FakeMessage(1, BOT_USER)) is None  # not a card


def test_overdue_question_gets_one_reminder(tmp_path):
    question = FakeMessage(100, ASKER, "when is the deadline?")
    followup, unanswered = make(
        tmp_path, [card(11, 100, minutes_ago=75)], FakeChannel(11, "support", [question])
    )
    run(followup.check_once())
    assert status_of(unanswered.messages[0]) == "reminded"
    ((text, kw),) = unanswered.sent  # posted in the unanswered-questions channel by default
    assert text.startswith("<@&555> 1 question has been waiting over 60 minutes")
    assert "when is the deadline?" in text and "https://discord.com/channels/1/11/100" in text
    assert "<@42>" not in text and "sam" in text  # names the asker without pinging them
    assert kw["allowed_mentions"].everyone is False

    run(followup.check_once())  # already reminded: not again
    assert len(unanswered.sent) == 1


def test_reminder_can_go_to_another_channel(tmp_path):
    question = FakeMessage(100, ASKER, "q")
    followup, unanswered = make(
        tmp_path,
        [card(11, 100, minutes_ago=75)],
        FakeChannel(11, "support", [question]),
        reminder_channel="gab-support-team",
    )
    run(followup.check_once())
    support_team = followup.bot.get_channel(14)
    assert len(support_team.sent) == 1 and unanswered.sent == []


def test_recent_question_waits(tmp_path):
    question = FakeMessage(100, ASKER, "q")
    followup, unanswered = make(
        tmp_path, [card(11, 100, minutes_ago=20)], FakeChannel(11, "support", [question])
    )
    run(followup.check_once())
    assert status_of(unanswered.messages[0]) == "open" and unanswered.sent == []


def test_staff_reply_marks_card_answered(tmp_path):
    question = FakeMessage(100, ASKER, "q")
    reply = FakeMessage(
        101, STAFF, "the deadline is Friday", reference=SimpleNamespace(message_id=100)
    )
    followup, unanswered = make(
        tmp_path, [card(11, 100, minutes_ago=90)], FakeChannel(11, "support", [question, reply])
    )
    run(followup.check_once())
    assert status_of(unanswered.messages[0]) == "answered" and unanswered.sent == []


def test_askers_own_follow_up_or_bot_reply_doesnt_count(tmp_path):
    question = FakeMessage(100, ASKER, "q")
    own = FakeMessage(101, ASKER, "anyone?", reference=SimpleNamespace(message_id=100))
    bot_reply = FakeMessage(
        102, BOT_USER, "I couldn't find this", reference=SimpleNamespace(message_id=100)
    )
    followup, unanswered = make(
        tmp_path,
        [card(11, 100, minutes_ago=90)],
        FakeChannel(11, "support", [question, own, bot_reply]),
    )
    run(followup.check_once())
    assert status_of(unanswered.messages[0]) == "reminded"


def test_several_overdue_questions_share_one_reminder(tmp_path):
    q1, q2 = FakeMessage(100, ASKER, "q1"), FakeMessage(200, ASKER, "q2")
    followup, unanswered = make(
        tmp_path,
        [card(11, 100, 90), card(11, 200, 80), card(11, 300, 5)],
        FakeChannel(11, "support", [q1, q2]),
    )
    run(followup.check_once())
    ((text, _kw),) = unanswered.sent
    assert text.startswith("<@&555> 2 questions have been waiting")
    assert [status_of(m) for m in unanswered.messages if read_card(m)] == [
        "reminded",
        "reminded",
        "open",
    ]


def test_long_reminders_are_split():
    cards = [(read_card(card(11, i, 70)), "x") for i in range(1, 40)]
    texts = build_reminder(cards, 60, "<@&555>")
    assert len(texts) > 1 and all(len(t) <= DISCORD_LIMIT for t in texts)


# --- buttons ---


class FakeInteraction:
    def __init__(self, user, message):
        self.user, self.message = user, message
        self.responses, self.followups = [], []
        self.response = SimpleNamespace(
            edit_message=self._edit, send_message=self._send, defer=self._defer
        )
        self.followup = SimpleNamespace(send=self._follow)

    async def _defer(self, **kw):
        self.responses.append(("defer", kw))

    async def _edit(self, **kw):
        self.responses.append(("edit", kw))

    async def _send(self, content, **kw):
        self.responses.append(("send", content))

    async def _follow(self, content, **kw):
        self.followups.append(content)


def test_mark_answered_button(tmp_path):
    followup, unanswered = make(
        tmp_path, [card(11, 100, minutes_ago=10)], FakeChannel(11, "support")
    )

    async def click():
        interaction = FakeInteraction(STAFF, unanswered.messages[0])
        await followup.on_mark_answered(interaction)
        return interaction

    interaction = run(click())
    kind, kw = interaction.responses[0]
    assert kind == "edit" and "status: answered" in kw["embed"].footer.text
    assert any("priya" in f.value for f in kw["embed"].fields)


def test_didnt_help_button_only_for_the_asker_and_posts_a_card(tmp_path):
    support = FakeChannel(11, "support")
    question = FakeMessage(100, ASKER, "<@999> which model?", channel=support)
    reply = FakeMessage(
        101,
        BOT_USER,
        "From the GAB FAQ (A1...)",
        channel=support,
        reference=SimpleNamespace(message_id=100, resolved=None),
    )
    support.messages = [question, reply]
    followup, unanswered = make(tmp_path, [], support)
    question.guild = followup.bot.guilds[0]

    async def click(user):
        interaction = FakeInteraction(user, reply)
        await followup.on_ask_person(interaction)
        return interaction

    other = run(click(STAFF))
    assert other.responses[0][0] == "send" and "Only the person who asked" in other.responses[0][1]
    assert unanswered.sent == []

    mine = run(click(ASKER))
    assert mine.responses[0][0] == "defer"
    assert reply.edits[0]["view"].ask_person.disabled
    ((_content, kw),) = unanswered.sent
    fields = {f.name: f.value for f in kw["embed"].fields}
    assert fields["Question"] == "which model?"
    assert "didn't help" in fields["Why"]
    assert "status: open" in kw["embed"].footer.text
    assert "passed your question to the team" in mine.followups[0]


def test_human_reply_after_reminder_closes_card_without_another_reminder(tmp_path):
    question = FakeMessage(100, ASKER, "question")
    reply = FakeMessage(101, STAFF, "resolved", reference=SimpleNamespace(message_id=100))
    followup, unanswered = make(
        tmp_path,
        [card(11, 100, 90, status="reminded")],
        FakeChannel(11, "support", [question, reply]),
    )
    run(followup.check_once())
    assert status_of(unanswered.messages[0]) == "answered"
    assert unanswered.sent == []


def test_failed_delivery_keeps_button_usable_and_allows_retry(tmp_path):
    support = FakeChannel(11, "support")
    question = FakeMessage(100, ASKER, "which model?", channel=support)
    reply = FakeMessage(
        101,
        BOT_USER,
        "FAQ answer",
        channel=support,
        reference=SimpleNamespace(message_id=100, resolved=None),
    )
    support.messages = [question, reply]
    followup, unanswered = make(tmp_path, [], support)
    question.guild = followup.bot.guilds[0]
    original_send = unanswered.send

    async def unavailable(*args, **kwargs):
        raise discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"), "synthetic failure"
        )

    async def click():
        interaction = FakeInteraction(ASKER, reply)
        await followup.on_ask_person(interaction)
        return interaction

    unanswered.send = unavailable
    failed = run(click())
    assert "couldn't send" in failed.followups[0]
    assert reply.edits == []
    unanswered.send = original_send
    succeeded = run(click())
    assert "passed your question" in succeeded.followups[0]
    assert len(unanswered.sent) == 1
    assert reply.edits[0]["view"].ask_person.disabled


def test_concurrent_escalation_clicks_deliver_one_card(tmp_path):
    support = FakeChannel(11, "support")
    question = FakeMessage(100, ASKER, "which model?", channel=support)
    reply = FakeMessage(
        101,
        BOT_USER,
        "FAQ answer",
        channel=support,
        reference=SimpleNamespace(message_id=100, resolved=None),
    )
    support.messages = [question, reply]
    followup, unanswered = make(tmp_path, [], support)
    question.guild = followup.bot.guilds[0]

    async def click_twice():
        await asyncio.gather(
            *(followup.on_ask_person(FakeInteraction(ASKER, reply)) for _ in range(2))
        )

    run(click_twice())
    assert len(unanswered.sent) == 1
