"""The Phase 7 round of changes: no staff names in public replies, the payment mailbox, the reply
footer (carry on / ask again, announcements), the repeat limit, the "GAB Phase ..." sections, two
staff channels, and the Phase 7 FAQ content."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from gab_faq.config import load_settings
from gab_faq.contracts import Answer
from gab_faq.discord_answers import announcements_link
from gab_faq.discord_bot.queries import watched
from gab_faq.discord_bot.settings import BotSettings
from gab_faq.knowledge import KnowledgeBase
from gab_faq.repeats import RepeatSettings, RepeatTracker, same_question, words
from gab_faq.replies import REPEAT_VIA, format_reply
from gab_faq.retrieval import LocalRetriever
from gab_faq.routing import SupportSettings

from .conftest import ROOT
from .test_discord_answers import FakeBrain, FakeChannel, FakeMessage, make

STAFF_NAMES = ("Amtul", "Adiba", "Rachana", "Divya")


def run(coro):
    return asyncio.run(coro)


# --- Public replies never name staff; payment questions get the mailbox ---


@pytest.mark.parametrize("route", ["task_qc", "playground", "payment", "environment_reset"])
def test_no_staff_name_in_any_public_reply(route):
    reply = format_reply(
        Answer("Not in the FAQ.", "not_in_faq", route=route), support=SupportSettings()
    )
    assert not any(name in reply for name in STAFF_NAMES)
    assert "the admin of this project" in reply


def test_payment_reply_points_to_the_mailbox_then_the_admin():
    reply = format_reply(
        Answer("Payment questions aren't covered by the FAQ.", "needs_human", route="payment"),
        support=SupportSettings(),
    )
    assert "please drop a mail at support@deccanexperts.ai" in reply
    assert reply.index("support@deccanexperts.ai") < reply.index("the admin of this project")


def test_public_contact_and_mailbox_come_from_config():
    support = load_settings(ROOT / "config.yaml").support
    assert support.public_contact == "the admin of this project"
    assert support.payment_email == "support@deccanexperts.ai"


# --- Footer: carry on or ask again, and the announcements ---


def test_answers_say_how_to_carry_on_and_point_to_announcements():
    reply = format_reply(Answer("Use 3.5 Flash-Lite.", "answered"), announcements="<#42>")
    assert "ask again with a bit more detail" in reply
    assert reply.endswith("📢 Please keep checking <#42> for the latest updates.")


def test_a_closest_match_invites_the_asker_to_carry_on_or_rephrase():
    reply = format_reply(Answer("Closest entry: ...", "partial"))
    assert "you can carry on with it" in reply and "rephrase your question" in reply
    assert "announcements" in reply


@pytest.mark.parametrize("outcome", ["small_talk", "limited"])
def test_greetings_and_limit_messages_have_no_footer(outcome):
    assert format_reply(Answer("Hi!", outcome)) == "Hi!"


def test_repeat_limit_reply_has_no_ask_again_line():
    reply = format_reply(Answer("You've asked this 3 times.", "needs_human", via=REPEAT_VIA))
    assert "ask me again" not in reply and "announcements" in reply


def test_announcements_link_prefers_the_askers_own_section():
    section = SimpleNamespace()
    local = FakeChannel("announcements", 7, category=section)
    other = FakeChannel("announcements", 8)
    asked_in = FakeChannel("project-related-queries", 9, category=section)
    section.text_channels = [local, asked_in]
    asked_in.guild = SimpleNamespace(text_channels=[other, local, asked_in])
    assert announcements_link(asked_in) == "<#7>"
    asked_in.category = None
    assert announcements_link(asked_in) == "<#8>"
    asked_in.guild = SimpleNamespace(text_channels=[asked_in])
    assert announcements_link(asked_in) == "the announcements channel"


# --- The same question again and again ---


def test_same_question_ignores_case_punctuation_and_a_changed_word():
    assert same_question(words("Which model do I use?"), words("which model do i use"))
    assert same_question(
        words("which model do I use for product A in phase 7"),
        words("which model should I use for product A in phase 7"),
    )
    assert not same_question(words("which model for product A"), words("how do I reset"))
    assert not same_question(words("model A?"), words("model B?"))  # short: must match exactly


def test_tracker_counts_within_the_window_only():
    now = [0.0]
    tracker = RepeatTracker(RepeatSettings(max_asks=3, window_minutes=60), clock=lambda: now[0])
    assert [tracker.record("u1", "which model?") for _ in range(3)] == [1, 2, 3]
    assert tracker.record("u2", "which model?") == 1  # per person
    now[0] += 61 * 60
    assert tracker.record("u1", "which model?") == 1  # the window has passed
    assert tracker.reply(2) is None
    text, flag = tracker.reply(3)
    assert flag and "flagged" in text
    text, flag = tracker.reply(4)
    assert not flag and "already" in text


def test_repeat_limit_can_be_switched_off():
    tracker = RepeatTracker(RepeatSettings(max_asks=0))
    assert tracker.record("u1", "which model?") == 0 and tracker.reply(99) is None


def test_third_ask_is_flagged_once_and_later_asks_skip_the_engine(tmp_path):
    brain = FakeBrain()
    answerer, guild, ch = make(tmp_path, brain)
    replies = []
    for i in range(1, 5):
        msg = FakeMessage("which model for product A?", ch.ask, guild)
        msg.id = i
        assert run(answerer.handle(msg))
        replies.append(msg.replies[0])
    assert len(brain.calls) == 2  # asks 3 and 4 never reach the engine
    assert "flagged" in replies[2] and "already" in replies[3]
    assert len(ch.unanswered.sent) == 1  # one staff card, for the 3rd ask
    fields = {f.name: f.value for f in ch.unanswered.sent[0][1]["embed"].fields}
    assert "asked repeatedly" in fields["Why"]


def test_greetings_never_count_as_repeats(tmp_path):
    answerer, guild, ch = make(tmp_path)
    for i in range(5):
        msg = FakeMessage("hi", ch.ask, guild)
        msg.id = i + 1
        run(answerer.handle(msg))
    assert ch.unanswered.sent == []


# --- Staff card wording ---


def test_staff_card_asks_the_team_to_pick_it_up(tmp_path):
    answerer, guild, ch = make(tmp_path, FakeBrain(Answer("Not in the FAQ.", "not_in_faq")))
    run(answerer.handle(FakeMessage("what is the capital of France?", ch.ask, guild)))
    embed = ch.unanswered.sent[0][1]["embed"]
    assert embed.title == "Unanswered question: please pick this up"
    assert "Mark as answered" in embed.description


# --- "GAB Phase ..." sections and the two staff channels ---


@pytest.mark.parametrize(
    "section,role",
    [
        ("GAB Phase 7 Conversation Annotators", "annotator"),
        ("GAB Phase 7 Conversation QC", "qc"),
        ("GAB Phase 7 Evaluation", "unknown"),
        ("GAB Phase 8 Conversation Annotators", "annotator"),  # next phase: no edit needed
    ],
)
def test_gab_phase_sections_are_answered_with_the_right_role(section, role):
    discord = load_settings(ROOT / "config.yaml").discord
    assert discord.in_scope("project-related-queries", section)
    assert discord.role_for_channel("project-related-queries", section) == role


@pytest.mark.parametrize(
    "section",
    ["Project MAITRIX", "Project GAB P6 QC Deployed", "Project GAB", "Project GAB - India"],
)
def test_only_gab_phase_sections_are_answered(section):
    discord = load_settings(ROOT / "config.yaml").discord
    assert not discord.in_scope("project-related-queries", section)


def test_question_collection_follows_gab_phase_sections():
    names = BotSettings.load(ROOT / "config.yaml").watched_names
    assert watched("GAB Phase 7 Conversation QC", names)
    assert watched("GAB Phase 9 Evaluation", names)
    assert not watched("Project GAB P6 Annotators Deployed", names)
    assert not watched("Project MAITRIX", names)


def test_followups_have_their_own_staff_channel():
    settings = load_settings(ROOT / "config.yaml")
    assert settings.discord.unanswered_channel == "gab-phase-faq-unanswered"
    assert settings.followup.reminder_channel == "gab-phase-faq-followups"
    assert settings.followup.after_minutes == 60


# --- Phase 7 FAQ content ---


def test_only_phase7_documents_are_live(current_knowledge):
    assert {d.phase for d in current_knowledge.documents} == {"7"}
    assert len(current_knowledge.documents) == 3
    assert all(d.external_processing_approved for d in current_knowledge.documents)


def test_phase7_rules_are_live_and_phase62_rules_are_gone(current_knowledge):
    text = current_knowledge.render()
    for fact in ("3.5 Flash-Lite", "3.8 Flash-Lite -> Model Underwing", "Reset ID"):
        assert fact in text
    assert "Screen recording is required in Phase 7" in text
    for old in (
        "flash_1p_old_test_arm",
        "do not work on any Reset",
        "No screen recording is needed",
    ):
        assert old not in text


def test_archived_phase6_files_are_marked_archived():
    archive = ROOT / "knowledge" / "archive"
    for name in ("phase62-updates.md", "phase6-qc.md", "rating-reference.md"):
        assert "status: archived" in (archive / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "question,expected",
    [
        ("Which model do I use for product B in phase 7?", {"V1"}),
        ("the model keeps switching, what do I do", {"V2"}),
        ("is screen recording required?", {"V3", "V29"}),
        ("how do I reset the environment after model A", {"V20", "V4"}),
        ("how many times can I nudge the model", {"V23"}),
        ("how do I record only the tab on a mac", {"V30"}),
        ("turn count in debug json doesn't match", {"V17"}),
        ("do I upload calendar invites as pdf", {"V12"}),
    ],
)
def test_phase7_questions_reach_their_entries(current_knowledge, question, expected):
    evidence = LocalRetriever(current_knowledge).retrieve(question, "annotator")
    assert expected & {c.entry.id for c in evidence.candidates[:3]}


def test_phase7_file_parses_with_unique_numbered_entries():
    kb = KnowledgeBase(ROOT / "knowledge" / "current")
    assert Path(kb.documents[0].path).name == "phase7-instructions.md"


@pytest.mark.parametrize(
    "question,role,expected",
    [
        ("what thinking level should I use for product A", "annotator", {"S1", "V1"}),
        ("I only see Flash-Lite Model Underwing, not 3.8", "annotator", {"S2"}),
        ("do I record model A and model B separately", "annotator", {"S5"}),
        ("can I use the snipping tool to record", "annotator", {"S6"}),
        ("clipchamp stopped recording at 30 minutes", "annotator", {"S7"}),
        ("model took more than 30 minutes to respond", "annotator", {"S12"}),
        ("does the first ask count as a nudge", "annotator", {"S16"}),
        ("product A used thinking level low, should I reject", "qc", {"QC1"}),
        ("do I have to check the screen recording in QC", "qc", {"QC2", "S5"}),
        ("should I ask what have we been working on before the seed prompt", "annotator", {"S20", "S21"}),
        ("I submitted with thinking level low before the announcement, what happens", "annotator", {"S22", "QC1"}),
        ("has phase 7.2 started", "annotator", {"S23", "S1"}),
        ("my task got auto skipped, can I get a new task", "annotator", {"S24"}),
        ("which tab should I use for product B, can I use another tab", "annotator", {"S25"}),
        ("when should I start the screen recording, from model selection?", "annotator", {"S5"}),
        ("annotator used a different tab instead of chat, what now", "qc", {"S25"}),
        ("cannot open the QC specification doc, access denied", "qc", {"QC5"}),
        ("model created an interactive visual not in the intent, do I upload it", "annotator", {"S14"}),
        ("my task came back for rework, do I redo only model A or both", "annotator", {"S26"}),
        ("do I need to reset the environment for the rework or delete previous turns", "annotator", {"S26"}),
        ("I don't see the rework option for my rejected task", "annotator", {"S27"}),
        ("one of my tasks was rejected, will I be removed from the project", "annotator", {"S28"}),
        ("annotator used the task tab for model B but everything else is correct", "qc", {"QC6"}),
        ("should I reassign to the same annotator or another one", "qc", {"QC7"}),
        ("the screen recording is only 2 minutes long", "qc", {"QC8"}),
        ("files are missing and the form won't let me submit the rejection", "qc", {"QC9"}),
        ("do rework tasks expire", "annotator", {"S27"}),
        ("start new task says no pending tasks are available for you", "annotator", {"S30"}),
        ("my assessment task says gemini 3.6 flash but the account does not have it", "annotator", {"S31"}),
        ("debug json is missing a conversation turn but the recording is complete", "qc", {"QC10"}),
        ("I was busy and couldn't work on 7.1, will I still be eligible", "annotator", {"S29"}),
        ("are QC tasks also exhausted", "annotator", {"S30"}),
        ("my task was rejected for thinking level but I selected high and it is in the recording", "annotator", {"S32"}),
        ("what is the payout cap from phase 7.2", "annotator", {"S33"}),
        ("is the 20% increment still going on", "annotator", {"S34"}),
        ("only one artifact file from model B is missing, everything else is fine", "qc", {"QC11"}),
    ],
)
def test_phase7_team_answers_reach_their_entries(current_knowledge, question, role, expected):
    evidence = LocalRetriever(current_knowledge).retrieve(question, role)
    assert expected & {c.entry.id for c in evidence.candidates[:3]}


def test_qc_entries_are_only_for_qc(current_knowledge):
    qc = next(d for d in current_knowledge.documents if d.path.name == "phase7-qc.md")
    assert qc.audience == "qc"


def test_no_personal_data_in_the_current_faq(current_knowledge):
    import re

    text = current_knowledge.render()
    assert not re.search(r"[\w.+-]+@(gmail|yahoo|outlook|hotmail)\.com", text)
    assert "alloc_2" not in text  # no task IDs copied from Discord


@pytest.mark.parametrize(
    "answer",
    [
        Answer(
            "Payment questions aren't covered.",
            "needs_human",
            route="payment",
            via="guard: payment",
        ),
        Answer("I can't reset environments.", "needs_human", via="guard: action request"),
        Answer("Not in the FAQ.", "not_in_faq", route="payment"),
    ],
)
def test_rule_decided_replies_do_not_suggest_asking_again(answer):
    reply = format_reply(answer, support=SupportSettings())
    assert "ask me again" not in reply and "ask again" not in reply
    assert "announcements" in reply
