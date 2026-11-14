"""When does the bot reply, and what does it send? Tests for Slack and Discord without connecting
to either."""

import json

from gab_faq import discord_answers, slack_app
from gab_faq.brain import Answer
from gab_faq.config import PlatformSettings, _platform
from gab_faq.replies import QuestionLog, format_reply, split_message

BOT = "UBOT"
LISTEN = frozenset({"cask"})  # config values are stored lower-case


def ev(**kw):
    base = {
        "type": "message",
        "user": "U1",
        "text": "hello",
        "channel": "CGEN",
        "ts": "1.0",
        "channel_type": "channel",
    }
    base.update(kw)
    return base


# --- Slack ---


def test_slack_dm_is_answered_unless_switched_off():
    assert (
        slack_app.message_route(
            ev(channel_type="im", channel="D1"), BOT, LISTEN, answer_in_dms=True
        )
        == "answer"
    )
    assert (
        slack_app.message_route(
            ev(channel_type="im", channel="D1"), BOT, LISTEN, answer_in_dms=False
        )
        is None
    )


def test_slack_answer_channel_top_level_is_answered():
    assert slack_app.message_route(ev(channel="CASK"), BOT, LISTEN) == "answer"


def test_slack_answer_channel_thread_reply_is_followup():
    assert (
        slack_app.message_route(ev(channel="CASK", ts="2.0", thread_ts="1.0"), BOT, LISTEN)
        == "thread_followup"
    )


def test_slack_other_channel_ignored():
    assert slack_app.message_route(ev(channel="CGEN"), BOT, LISTEN) is None


def test_slack_mention_in_channel_left_to_app_mention_handler():
    assert slack_app.message_route(ev(channel="CASK", text=f"<@{BOT}> hi"), BOT, LISTEN) is None


def test_slack_ignores_bots_and_edits():
    assert slack_app.message_route(ev(channel="CASK", bot_id="B1"), BOT, LISTEN) is None
    assert (
        slack_app.message_route(ev(channel="CASK", subtype="message_changed"), BOT, LISTEN) is None
    )


def test_slack_clean_text():
    assert slack_app.clean_text(f"<@{BOT}> which model?", BOT) == "which model?"
    assert slack_app.clean_text(f"<@{BOT}|helpbot> hi", BOT) == "hi"


def test_slack_history_roles():
    msgs = [
        {"ts": "1", "user": "U1", "text": "q"},
        {"ts": "2", "user": BOT, "text": "a"},
        {"ts": "3", "user": "U1", "text": "now"},
    ]
    assert slack_app.to_history(msgs, BOT, current_ts="3") == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
    ]


# --- Discord ---


def droute(**kw):
    base = dict(is_dm=False, mentioned=False, in_answer_channel=False, in_answer_thread=False)
    base.update(kw)
    return discord_answers.route(**base)


def test_discord_routes():
    assert droute(is_dm=True, answer_in_dms=True) == "answer"
    assert droute(is_dm=True) is None  # DMs are off by default
    assert droute(is_dm=True, answer_in_dms=False) is None
    assert droute(mentioned=True) == "answer"
    assert droute(in_answer_channel=True) == "answer"
    assert droute(in_answer_thread=True) == "thread_followup"
    assert droute() is None
    assert droute(mentioned=True, in_scope=False) is None  # outside only_in
    assert (
        droute(is_dm=True, answer_in_dms=True, in_scope=False) == "answer"
    )  # only_in doesn't apply to DMs


def test_only_in():
    s = _platform({"only_in": ["Project GAB P5 QC Deployed"]})
    assert s.in_scope("support", "4", "project gab p5 qc deployed", "200")
    assert not s.in_scope("support", "5", "Project Maitrix")
    assert _platform({}).in_scope("anything")  # empty = anywhere


def test_discord_strip_mentions():
    assert discord_answers.strip_mentions("<@123> hi <@!123>", 123) == "hi"


def test_unanswered_card():
    answer = Answer("I don't have that.", "not_in_faq", escalation_reason="pay rates")
    embed = discord_answers.build_unanswered_embed(
        asker="<@1> (sam)",
        where="<#2>",
        role="qc",
        question="q" * 3000,
        answer=answer,
        jump_url="https://discord.com/channels/1/2/3",
    )
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Why"] == "not in faq: pay rates"
    assert len(fields["Question"]) <= 1024  # Discord rejects longer fields
    assert "https://discord.com/channels/1/2/3" in fields["Reply to them"]


# --- Shared ---


def test_role_for_channel_by_name_or_id():
    s = _platform(
        {
            "annotator_channels": ["coders-maitrix"],
            "qc_channels": ["#Maitrix-QC", 123],
            "qm_channels": ["qm-only"],
        }
    )
    assert s.role_for_channel("qm-only") == "qm"
    assert s.role_for_channel("CODERS-MAITRIX") == "annotator"
    assert s.role_for_channel("maitrix-qc") == "qc"  # # and case don't matter
    assert s.role_for_channel("123") == "qc"  # IDs work too
    assert s.role_for_channel("random") == "unknown"
    assert s.role_for_channel("my-thread", "999", "maitrix-qc") == "qc"  # thread inherits parent


def test_answer_channel_matching():
    s = PlatformSettings(answer_channels=frozenset({"ask-the-bot"}))
    assert s.is_answer_channel("Ask-The-Bot", "555")
    assert not s.is_answer_channel("general", "1", None)


def test_escalation_tag_only_when_needed():
    ok = Answer("Use Flash.", "answered")
    unknown = Answer("Not in the FAQ.", "not_in_faq")
    assert format_reply(ok, "<@U9>") == "Use Flash."
    assert format_reply(unknown, "<@U9>").endswith("<@U9> could you help with this one?")
    assert format_reply(unknown, "") == "Not in the FAQ."


def test_staging_replies_are_marked():
    assert format_reply(Answer("x", "answered"), environment="staging").startswith("[TEST BOT]")


def test_split_message():
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(100))
    chunks = split_message(text, 2000)
    assert all(len(c) <= 2000 for c in chunks)
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
    assert split_message("short", 2000) == ["short"]
    assert all(len(c) <= 2000 for c in split_message("y" * 4500, 2000))


def test_question_log_files(tmp_path):
    qlog = QuestionLog(tmp_path)
    qlog.record(
        platform="discord",
        channel="C",
        user="U",
        role="qc",
        question="q1",
        answer=Answer("a", "answered"),
    )
    qlog.record(
        platform="discord",
        channel="C",
        user="U",
        role="qc",
        question="q2",
        answer=Answer("?", "not_in_faq"),
    )
    all_q = (tmp_path / "faq_questions.jsonl").read_text().splitlines()
    unanswered = (tmp_path / "faq_unanswered.jsonl").read_text().splitlines()
    assert len(all_q) == 2 and len(unanswered) == 1
    assert json.loads(unanswered[0])["question"] == "q2"
