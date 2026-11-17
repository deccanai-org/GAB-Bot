"""/throttle-request and /task-issue (support.py) with stand-in Discord objects: no network, no AI."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import discord
from discord import app_commands

from gab_faq.config import Settings, _platform
from gab_faq.replies import QuestionLog
from gab_faq.routing import SupportSettings, parse_contacts
from gab_faq.support import SupportDesk

from .test_discord_answers import (
    ANNOTATORS,
    GAB_CONFIG,
    OTHER_PROJECT,
    FakeChannel,
    FakeDirectory,
    FakeDMUser,
)


class FakeResponse:
    def __init__(self):
        self.sent, self.deferred = [], None

    async def send_message(self, content, ephemeral=False):
        self.sent.append((content, ephemeral))

    async def defer(self, ephemeral=False, thinking=False):
        self.deferred = (ephemeral, thinking)


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content, ephemeral=False):
        self.sent.append((content, ephemeral))


class FakeUser:
    id = 42
    mention = "<@42>"

    def __str__(self):
        return "sam"


class FakeAttachment:
    def __init__(self, filename, size=1000, content_type="image/png"):
        self.filename, self.size, self.content_type = filename, size, content_type

    async def read(self):
        return b"synthetic log content"

    async def to_file(self):
        return SimpleNamespace(filename=self.filename)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def setup(tmp_path, support=None, with_requests_channel=True, directory=None):
    channels = {
        "queries": FakeChannel("project-related-queries", 1, ANNOTATORS),
        "other": FakeChannel("project-related-queries", 5, OTHER_PROJECT),
        "staff": FakeChannel("faq-bot-unanswered", 6),
    }
    guild = SimpleNamespace(
        text_channels=[c for k, c in channels.items() if with_requests_channel or k != "staff"]
    )
    settings = Settings(
        enabled=True,
        environment="production",
        discord=_platform(GAB_CONFIG),
        support=support or SupportSettings(),
    )
    clock = Clock()
    directory = directory or FakeDirectory()
    bot = SimpleNamespace(user=None, get_user=directory.get_user, fetch_user=directory.fetch_user)
    desk = SupportDesk(bot, settings, QuestionLog(tmp_path), clock=clock)
    return desk, guild, channels, clock


def interaction(guild, channel):
    return SimpleNamespace(
        guild=guild,
        channel=channel,
        user=FakeUser(),
        response=FakeResponse(),
        followup=FakeFollowup(),
    )


def run(coro):
    return asyncio.run(coro)


def card(channel):
    ((content, kwargs),) = channel.sent
    return content, kwargs, {f.name: f.value for f in kwargs["embed"].fields}


def test_throttle_request_goes_to_task_queries_contact(tmp_path):
    desk, guild, ch, _ = setup(tmp_path)
    i = interaction(guild, ch["queries"])
    run(
        desk.handle_throttle(
            i, "I finish tasks fast and run out of work", "4 per hour", "annotation"
        )
    )
    content, kwargs, fields = card(ch["staff"])
    assert kwargs["embed"].title == "Throttle increase request"
    assert fields["Route to"] == "Amtul / Adiba (task queries and QC)"
    assert fields["Requested limit"] == "4 per hour" and fields["Stage"] == "annotation"
    assert fields["Role"] == "annotator"
    assert content is None  # no mention configured, so nobody is pinged
    ((msg, private),) = i.followup.sent
    assert private and "project team" in msg and "Amtul" not in msg  # names stay on the card
    logged = json.loads((tmp_path / "support_requests.jsonl").read_text().splitlines()[0])
    assert logged["kind"] == "throttle" and logged["route"] == "task_qc"


def test_task_issue_collects_id_description_error_and_screenshots(tmp_path):
    desk, guild, ch, _ = setup(tmp_path)
    i = interaction(guild, ch["queries"])
    shots = [FakeAttachment("error.png"), FakeAttachment("console.log", content_type="text/plain")]
    run(
        desk.handle_task_issue(
            i, "TASK-1234", "Submit button does nothing", "Error 500: upload failed", shots
        )
    )
    content, kwargs, fields = card(ch["staff"])
    assert (
        fields["Task ID"] == "TASK-1234" and fields["What happened"] == "Submit button does nothing"
    )
    assert fields["Error message"] == "Error 500: upload failed"
    assert [f.filename for f in kwargs["files"]] == [
        "error.png",
        "console.log",
    ]  # re-uploaded, not links
    assert fields["Route to"] == "Amtul / Adiba (task queries and QC)"


def test_task_issue_input_is_checked(tmp_path):
    desk, guild, ch, _ = setup(tmp_path)
    bad_id = interaction(guild, ch["queries"])
    run(desk.handle_task_issue(bad_id, "<@&1> drop table", "something broke", None, []))
    assert "task ID" in bad_id.response.sent[0][0] and bad_id.response.sent[0][1]
    exe = interaction(guild, ch["queries"])
    run(
        desk.handle_task_issue(
            exe,
            "T-1",
            "something broke",
            None,
            [FakeAttachment("tool.exe", content_type="application/octet-stream")],
        )
    )
    assert "screenshots" in exe.response.sent[0][0]
    big = interaction(guild, ch["queries"])
    run(
        desk.handle_task_issue(
            big, "T-1", "something broke", None, [FakeAttachment("huge.png", size=50 * 2**20)]
        )
    )
    assert "larger than" in big.response.sent[0][0]
    assert ch["staff"].sent == []


def test_only_in_gab_channels_and_servers(tmp_path):
    desk, guild, ch, _ = setup(tmp_path)
    outside = interaction(guild, ch["other"])
    run(desk.handle_throttle(outside, "need more tasks please", None, None))
    assert "only works in the GAB project channels" in outside.response.sent[0][0]
    dm = interaction(None, FakeChannel(None, 50))
    run(desk.handle_throttle(dm, "need more tasks please", None, None))
    assert dm.response.sent[0][1] is True
    assert ch["staff"].sent == []


def test_one_request_per_person_per_cooldown(tmp_path):
    desk, guild, ch, clock = setup(tmp_path)
    run(
        desk.handle_throttle(
            interaction(guild, ch["queries"]), "need more tasks please", None, None
        )
    )
    again = interaction(guild, ch["queries"])
    run(desk.handle_throttle(again, "need more tasks please", None, None))
    assert "Please wait" in again.response.sent[0][0] and len(ch["staff"].sent) == 1
    clock.now += 61
    run(
        desk.handle_throttle(
            interaction(guild, ch["queries"]), "need more tasks please", None, None
        )
    )
    assert len(ch["staff"].sent) == 2


def two_contacts():
    return replace(
        SupportSettings(),
        contacts=parse_contacts(
            {"task_qc": {"name": "Amtul / Adiba", "mention": "<@111111111> <@222222222>"}}
        ),
    )


def test_contacts_get_a_dm_and_the_card_pings_nobody_and_user_text_pings_nobody(tmp_path):
    amtul, adiba = FakeDMUser(111111111), FakeDMUser(222222222)
    desk, guild, ch, _ = setup(
        tmp_path, support=two_contacts(), directory=FakeDirectory(amtul, adiba)
    )
    run(
        desk.handle_throttle(
            interaction(guild, ch["queries"]), "@everyone <@999999999> raise it", None, None
        )
    )
    content, kwargs, fields = card(ch["staff"])  # exactly one message: the card, no extra ping
    assert content is None and kwargs["allowed_mentions"].users is False
    assert "<@999999999>" not in fields["Reason"] and "@everyone" not in fields["Reason"]
    for person in (amtul, adiba):
        ((text, dm),) = person.sent
        assert "throttle increase request" in text and "task queries and QC" in text
        dm_fields = {f.name: f.value for f in dm["embed"].fields}
        assert "<@999999999>" not in dm_fields["Reason"] and "@everyone" not in dm_fields["Reason"]
        assert dm["allowed_mentions"].users is False


def test_a_contact_with_closed_dms_is_pinged_in_the_staff_channel_instead(tmp_path):
    amtul, adiba = FakeDMUser(111111111), FakeDMUser(222222222, closed=True)
    desk, guild, ch, _ = setup(
        tmp_path, support=two_contacts(), directory=FakeDirectory(amtul, adiba)
    )
    i = interaction(guild, ch["queries"])
    run(desk.handle_throttle(i, "need more tasks please", None, None))
    assert len(amtul.sent) == 1 and adiba.sent == []
    (_card, ping) = ch["staff"].sent
    assert ping[0] == "<@222222222>"  # only the person who couldn't be messaged
    assert [o.id for o in ping[1]["allowed_mentions"].users] == [222222222]
    assert i.followup.sent  # the asker still gets their confirmation


def test_no_requests_channel_tells_the_asker_who_to_contact(tmp_path):
    desk, guild, ch, _ = setup(tmp_path, with_requests_channel=False)
    i = interaction(guild, ch["queries"])
    run(desk.handle_throttle(i, "need more tasks please", None, None))
    assert "contact the admin of this project" in i.response.sent[0][0]
    assert "Amtul" not in i.response.sent[0][0]


def test_commands_are_registered_server_only():
    client = discord.Client(intents=discord.Intents.none())
    tree = app_commands.CommandTree(client)
    settings = Settings(enabled=True, discord=_platform(GAB_CONFIG))
    SupportDesk(client, settings, SimpleNamespace()).register(tree)
    commands = {c.name: c for c in tree.get_commands()}
    assert set(commands) == {"throttle-request", "task-issue"}
    assert all(c.guild_only for c in commands.values())
    params = [p.name for p in commands["task-issue"].parameters]
    assert params[:3] == ["task_id", "description", "error_message"] and "screenshot" in params


def test_log_failure_does_not_hide_successful_support_delivery(tmp_path):
    desk, guild, channels, _ = setup(tmp_path)

    def unavailable(**kwargs):
        raise OSError("synthetic disk failure")

    desk.question_log.record_request = unavailable
    request = interaction(guild, channels["queries"])
    run(desk.handle_throttle(request, "need more tasks please", None, None))
    assert len(channels["staff"].sent) == 1
    assert "was sent" in request.followup.sent[0][0]


def test_plaintext_attachments_are_scrubbed_before_staff_upload(tmp_path):
    desk, guild, channels, _ = setup(tmp_path)
    attachment = FakeAttachment("debug.log", content_type="text/plain")

    async def read():
        return b"Error context\npassword: SYNTHETIC_SECRET"

    attachment.read = read
    run(
        desk.handle_task_issue(
            interaction(guild, channels["queries"]), "TASK-1", "failed upload", None, [attachment]
        )
    )
    file = channels["staff"].sent[0][1]["files"][0]
    assert b"SYNTHETIC_SECRET" not in file.fp.getvalue()
    assert b"[redacted]" in file.fp.getvalue()
    file.close()


def test_concurrent_support_submissions_cannot_bypass_cooldown(tmp_path):
    desk, guild, channels, _ = setup(tmp_path)

    async def submit():
        await asyncio.gather(
            *(
                desk.handle_throttle(
                    interaction(guild, channels["queries"]), "need more tasks please", None, None
                )
                for _ in range(3)
            )
        )

    run(submit())
    assert len(channels["staff"].sent) == 1
