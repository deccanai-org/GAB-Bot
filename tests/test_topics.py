"""Topic tracker: throttle / payment / reset / not-added / assessment messages collected into one
staff channel (no network, stand-in Discord objects)."""

import asyncio
from types import SimpleNamespace

import pytest

from gab_faq.config import Settings, _platform
from gab_faq.discord_answers import FaqAnswerer
from gab_faq.replies import QuestionLog
from gab_faq.topics import TopicSettings, TopicTracker, match_topics

from .test_discord_answers import BOT_USER, FakeBrain, FakeChannel, FakeMessage

ANNOTATORS = SimpleNamespace(name="GAB Phase 7 Conversation Annotators", id=900)
OTHER = SimpleNamespace(name="Some Other Project", id=901)
SCOPE = {
    "only_in": ["GAB Phase*", "gab-phase*"],
    "annotator_channels": ["GAB Phase* Annotator*"],
}


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "text, topics",
    [
        ("Why am I not added in phase-7?", ["not_added"]),
        ("I haven't been added to the GAB phase 7 channel yet", ["not_added"]),
        ("why havent i been added", ["not_added"]),
        ("please add me to phase 7", ["not_added"]),
        ("I don't have access to cosmo for phase 7", ["not_added"]),
        ("I cannot see the phase 7 channels", ["not_added"]),
        ("can you increase my task limit", ["throttle"]),
        ("I got throttled, can I get more tasks", ["throttle"]),
        ("when will my payment for phase 6 come?", ["payment"]),
        ("I have not received my payment", ["payment"]),
        ("Reset environment is not working, it shows error", ["reset"]),
        ("where do I paste the reset ID", ["reset"]),
        ("when will assessment results come out", ["assessment"]),
        ("I passed the assesment, what next", ["assessment"]),
        ("did anyone get the qualification test result", ["assessment"]),
        ("my payment is pending and the reset failed", ["payment", "reset"]),
        # Not tracked
        ("which model do I pick for product A", []),
        ("the model keeps switching, what do i do", []),
        ("the persona asks the model to draft a payment reminder email", []),
        ("can't access drive files in the persona account", []),
        ("the model can't see the project files", []),
        ("I want added features in the deck", []),
        ("my task is stuck at submission", []),
    ],
)
def test_topics_are_detected(text, topics):
    assert match_topics(text) == topics


def test_extra_keywords_and_topic_selection_come_from_config():
    settings = TopicSettings.parse(
        {
            "enabled": True,
            "channel": "x",
            "topics": ["assessment"],
            "extra_keywords": {"assessment": ["quiz"]},
        }
    )
    assert match_topics("when is the quiz?", settings) == ["assessment"]
    assert match_topics("increase my task limit", settings) == []  # throttle not selected


@pytest.mark.parametrize(
    "section",
    [{"topics": ["refunds"]}, {"channels": {"refunds": "x"}}, {"window_hours": 0}],
)
def test_bad_config_is_rejected(section):
    with pytest.raises(ValueError):
        TopicSettings.parse(section)


class Author:
    bot = False

    def __init__(self, id, name):
        self.id, self.name = id, name
        self.mention = f"<@{id}>"

    def __str__(self):
        return self.name


def make(channels=None, window_hours=24, **section):
    queries = FakeChannel("project-related-queries", 1, ANNOTATORS)
    other = FakeChannel("project-related-queries", 2, OTHER)
    tracker = FakeChannel("gab-phase-staff-requests", 3)
    payments = FakeChannel("gab-payment-requests", 4)
    guild = SimpleNamespace(id=1, text_channels=[queries, other, tracker, payments], me=None)
    clock = SimpleNamespace(now=1_000_000.0)
    cfg = {"enabled": True, "channel": "gab-phase-staff-requests", "window_hours": window_hours}
    cfg.update(section)
    if channels:
        cfg["channels"] = channels
    bot = SimpleNamespace(user=BOT_USER)
    tracker_obj = TopicTracker(
        bot, TopicSettings.parse(cfg), _platform(SCOPE), clock=lambda: clock.now
    )
    return (
        tracker_obj,
        guild,
        SimpleNamespace(
            queries=queries, other=other, tracker=tracker, payments=payments, clock=clock
        ),
    )


def msg(text, channel, guild, author=None, id=1):
    m = FakeMessage(text, channel, guild)
    m.id = id
    m.jump_url = f"https://discord.com/channels/1/{channel.id}/{id}"
    m.author = author or Author(42, "sam")
    return m


def test_a_tracked_message_becomes_a_card_that_pings_nobody():
    tracker, guild, ch = make()
    assert run(tracker.observe(msg("why am I not added in phase 7?", ch.queries, guild))) is True
    assert len(ch.tracker.sent) == 1
    _, kwargs = ch.tracker.sent[0]
    embed = kwargs["embed"]
    assert embed.title == "Not added to the phase"
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Who"].startswith("<@42>")
    assert fields["Where"] == ch.queries.mention
    assert fields["Times raised"] == "1"
    assert "not added in phase 7" in fields["Latest message"]
    mentions = kwargs["allowed_mentions"]
    assert mentions.everyone is False and mentions.users is False and mentions.roles is False


def test_untracked_messages_and_other_projects_are_ignored():
    tracker, guild, ch = make()
    assert run(tracker.observe(msg("which model for product A?", ch.queries, guild))) is False
    assert run(tracker.observe(msg("increase my task limit", ch.other, guild))) is False
    bot_author = Author(7, "another-bot")
    bot_author.bot = True
    assert (
        run(tracker.observe(msg("increase my task limit", ch.queries, guild, bot_author))) is False
    )
    assert ch.tracker.sent == []


def test_the_same_person_and_topic_updates_one_card():
    tracker, guild, ch = make()
    run(tracker.observe(msg("increase my task limit please", ch.queries, guild, id=1)))
    ch.clock.now += 3600
    run(tracker.observe(msg("any update on my throttle?", ch.queries, guild, id=2)))
    assert len(ch.tracker.sent) == 1
    card = ch.tracker.messages[next(iter(ch.tracker.messages))]
    fields = {f.name: f.value for f in card.embeds[0].fields}
    assert fields["Times raised"] == "2"
    assert "any update on my throttle" in fields["Latest message"]
    assert fields["Open it"].endswith(f"/{ch.queries.id}/2)")  # links the latest message


def test_a_different_person_or_topic_gets_its_own_card():
    tracker, guild, ch = make()
    run(tracker.observe(msg("increase my task limit", ch.queries, guild)))
    run(tracker.observe(msg("increase my task limit", ch.queries, guild, Author(43, "kim"))))
    run(tracker.observe(msg("reset is failing", ch.queries, guild)))
    assert len(ch.tracker.sent) == 3


def test_after_the_window_a_new_card_is_posted():
    tracker, guild, ch = make(window_hours=1)
    run(tracker.observe(msg("increase my task limit", ch.queries, guild)))
    ch.clock.now += 2 * 3600
    run(tracker.observe(msg("increase my task limit", ch.queries, guild)))
    assert len(ch.tracker.sent) == 2


def test_a_topic_can_go_to_its_own_channel():
    tracker, guild, ch = make(channels={"payment": "gab-payment-requests"})
    run(tracker.observe(msg("my payment is pending and the reset failed", ch.queries, guild)))
    assert [k["embed"].title for _, k in ch.payments.sent] == ["Payment"]
    assert [k["embed"].title for _, k in ch.tracker.sent] == ["Environment reset"]


def test_a_missing_tracker_channel_is_not_an_error():
    tracker, guild, ch = make(channel="does-not-exist")
    assert run(tracker.observe(msg("increase my task limit", ch.queries, guild))) is False


def test_off_by_default():
    assert TopicSettings().enabled is False
    tracker = TopicTracker(SimpleNamespace(user=BOT_USER), TopicSettings(), _platform(SCOPE))
    assert tracker.enabled is False


def test_the_bot_still_answers_and_tracks_the_same_message(tmp_path):
    queries = FakeChannel("project-related-queries", 1, ANNOTATORS)
    tracker_ch = FakeChannel("gab-phase-staff-requests", 3)
    unanswered = FakeChannel("faq-bot-unanswered", 6)
    guild = SimpleNamespace(id=1, text_channels=[queries, tracker_ch, unanswered])
    bot = SimpleNamespace(user=BOT_USER, guilds=[guild], get_channel=lambda i: None)
    settings = Settings(
        enabled=True,
        environment="production",
        discord=_platform({**SCOPE, "unanswered_channel": "faq-bot-unanswered"}),
        topic_tracker=TopicSettings.parse({"enabled": True, "channel": "gab-phase-staff-requests"}),
    )
    brain = FakeBrain()
    answerer = FaqAnswerer(bot, settings, brain, QuestionLog(tmp_path))
    # Not addressed to the bot: no answer, but tracked.
    assert run(answerer.handle(FakeMessage("increase my task limit", queries, guild))) is False
    # Addressed to the bot: answered and tracked.
    m = FakeMessage("<@999> how do I reset the environment?", queries, guild, mentions=[BOT_USER])
    assert run(answerer.handle(m)) is True
    assert brain.calls == [("how do I reset the environment?", "annotator")]
    titles = [k["embed"].title for _, k in tracker_ch.sent]
    assert titles == ["Throttle / task limit", "Environment reset"]
    assert "<@999>" not in tracker_ch.sent[1][1]["embed"].fields[3].value


def test_messages_in_the_tracker_channel_itself_are_not_tracked():
    tracker, guild, ch = make()
    assert run(tracker.observe(msg("increase my task limit", ch.tracker, guild))) is False
    assert ch.tracker.sent == []


def test_gigi_answers_mentions_in_the_gab_phase_staff_channel_without_tracking_them(tmp_path):
    staff = FakeChannel("gab-phase-staff-requests", 3)
    unanswered = FakeChannel("faq-bot-unanswered", 6)
    guild = SimpleNamespace(id=1, text_channels=[staff, unanswered])
    bot = SimpleNamespace(user=BOT_USER, guilds=[guild], get_channel=lambda i: None)
    settings = Settings(
        enabled=True,
        environment="production",
        discord=_platform({**SCOPE, "unanswered_channel": "faq-bot-unanswered"}),
        topic_tracker=TopicSettings.parse({"enabled": True, "channel": "gab-phase-staff-requests"}),
    )
    brain = FakeBrain()
    answerer = FaqAnswerer(bot, settings, brain, QuestionLog(tmp_path))
    m = FakeMessage("<@999> how do I reset the environment?", staff, guild, mentions=[BOT_USER])
    assert run(answerer.handle(m)) is True
    assert brain.calls == [("how do I reset the environment?", "unknown")]
    assert all("embed" not in k for _, k in staff.sent)  # a reply, not a tracker card


def test_the_shipped_config_puts_the_tracker_channel_in_gigis_scope():
    from gab_faq.config import load_settings

    settings = load_settings()
    channel = settings.topic_tracker.channel
    assert channel.startswith("gab-phase")
    assert settings.discord.in_scope(channel)
    assert settings.topic_tracker.enabled
