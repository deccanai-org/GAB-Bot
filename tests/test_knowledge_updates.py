"""Gigi's staff upload channel: PDFs in, drafts out, publish by button, documents managed by
command. Discord is faked around the real store, real embeds and real button views."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from gab_faq import knowledge_updates as ku
from gab_faq.config import KnowledgeUpdatesSettings, _knowledge_updates, load_settings
from gab_faq.discord_answers import FaqAnswerer
from gab_faq.knowledge_store import SqliteKnowledgeStore
from gab_faq.knowledge_updates import (
    DeleteView,
    DocumentOps,
    KnowledgeUpdates,
    UpdateView,
    build_knowledge_updates,
    clean_title,
    doc_name,
    parse_command,
)

from .test_admin import GUIDE_LINES, make_pdf

FAKE_PAGES = ["Which account do I use?\nUse the test account from the tasking window.\n"]
GOOD = "---\ntitle: Notes\nupdated: 2026-11-18\n---\nN1. What now?\nPublish it.\n"
CHANNEL_ID = 4242


# ---- fakes -----------------------------------------------------------------------------------
class Typing:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class Channel:
    def __init__(self, name="gigi-updates", ident=CHANNEL_ID, public=False):
        self.name, self.id, self.public = name, ident, public
        self.guild = SimpleNamespace(default_role=object())

    def permissions_for(self, role):
        return SimpleNamespace(view_channel=self.public)

    def typing(self):
        return Typing()


class Member:
    def __init__(self, ident=7, name="Priya", roles=()):
        self.id, self.display_name = ident, name
        self.roles = [SimpleNamespace(id=1000 + i, name=r) for i, r in enumerate(roles)]


class Attachment:
    def __init__(self, filename, data=b"%PDF-1.4 fake", size=None):
        self.filename, self.data = filename, data
        self.size = len(data) if size is None else size

    async def read(self):
        return self.data


class Message:
    def __init__(self, channel, content="", attachments=(), author=None):
        self.channel, self.content = channel, content
        self.attachments, self.author = list(attachments), author or Member()
        self.guild, self.id, self.replies = channel.guild, 1, []

    async def reply(self, text=None, **kwargs):
        self.replies.append({"text": text, **kwargs})
        return self


class Bot:
    def __init__(self):
        self.views = []

    def add_view(self, view):
        self.views.append(view)


def build(tmp_path, **overrides):
    store = SqliteKnowledgeStore(tmp_path / "k.sqlite3")
    settings = KnowledgeUpdatesSettings(enabled=True, **overrides)
    bot = Bot()
    return KnowledgeUpdates(bot, settings, DocumentOps(store)), store, bot


@pytest.fixture(autouse=True)
def quick_reader(monkeypatch):
    """Most tests do not need a real PDF reader process (a few below use the real one)."""
    monkeypatch.setattr(ku, "extract_pages_isolated", lambda data: FAKE_PAGES)


def run(coroutine):
    return asyncio.run(coroutine)


def send(updates, channel, content="", attachments=(), author=None):
    message = Message(channel, content, attachments, author)

    async def go():
        claimed = await updates.handle(message)
        return claimed, message

    return run(go())


def publish_doc(store, name="a.md", text=GOOD, qwen=False):
    store.create_draft(name, text, "pm")
    store.publish(name, "pm", external_processing_approved=qwen)


# ---- small pure pieces -----------------------------------------------------------------------
def test_command_forms_are_exact_so_chatter_is_not_mistaken_for_one():
    assert parse_command("list") == ("list", [])
    assert parse_command("Gigi list") == ("list", [])
    assert parse_command("get my-doc") == ("get", ["my-doc"])
    assert parse_command("qwen my-doc on") == ("qwen", ["my-doc", "on"])
    for chatter in ("", "list of things we need to do", "delete", "get", "hello team", "qwen x"):
        assert parse_command(chatter) is None


def test_document_names_are_normalised_and_checked():
    assert doc_name("My-Doc") == "my-doc.md" and doc_name("a.md") == "a.md"
    for bad in ("../x", "a b", "", "x/y", "A_B"):
        assert doc_name(bad) is None


def test_titles_lose_mentions_and_control_characters():
    assert clean_title("  QC <@123> guide\nsecond line ") == "QC guide"
    assert clean_title("<@&99><#5>") == ""
    assert len(clean_title("x" * 500)) == 120


def test_settings_parse_and_default_to_off():
    assert load_settings().knowledge_updates.enabled is False
    parsed = _knowledge_updates(
        {"enabled": True, "channel": "#staff-gigi", "allowed_roles": ["PM", 99]}
    )
    assert parsed == KnowledgeUpdatesSettings(True, "staff-gigi", ("PM", "99"))
    assert _knowledge_updates({"enabled": "yes"}).enabled is False  # only a real true counts
    with pytest.raises(ValueError):
        _knowledge_updates({"allowed_roles": "PM"})


# ---- switching it on -------------------------------------------------------------------------
def test_it_is_off_without_the_switch_or_the_write_account(monkeypatch, caplog):
    off = SimpleNamespace(
        knowledge_updates=KnowledgeUpdatesSettings(), knowledge_store=None, knowledge_dir=None
    )
    assert build_knowledge_updates(Bot(), off) is None
    on = SimpleNamespace(
        knowledge_updates=KnowledgeUpdatesSettings(enabled=True),
        knowledge_store=None,
        knowledge_dir=None,
    )
    monkeypatch.delenv("GAB_KNOWLEDGE_ADMIN_DB", raising=False)
    with caplog.at_level(logging.ERROR):
        assert build_knowledge_updates(Bot(), on) is None
    assert "GAB_KNOWLEDGE_ADMIN_DB" in caplog.text


def test_with_the_account_set_it_starts_warns_about_the_read_account_and_hides_the_password(
    monkeypatch, tmp_path, caplog
):
    monkeypatch.setenv("GAB_KNOWLEDGE_ADMIN_DB", str(tmp_path / "x.sqlite3"))
    on = SimpleNamespace(
        knowledge_updates=KnowledgeUpdatesSettings(enabled=True),
        knowledge_store=None,
        knowledge_dir=None,
    )
    with caplog.at_level(logging.INFO):
        assert isinstance(build_knowledge_updates(Bot(), on), KnowledgeUpdates)
    assert "not pick up documents" in caplog.text  # no read-only GAB_KNOWLEDGE_DB configured
    monkeypatch.setenv("GAB_KNOWLEDGE_ADMIN_DB", "postgresql://gab_admin:hunter2@db.example/x")
    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert build_knowledge_updates(Bot(), on) is not None
    assert "hunter2" not in caplog.text and "gab_admin@db.example" in caplog.text


def test_start_registers_the_buttons_so_old_messages_keep_working(tmp_path):
    updates, _, bot = build(tmp_path)

    async def go():
        await updates.start()

    run(go())
    assert {type(view) for view in bot.views} == {UpdateView, DeleteView}


def test_the_buttons_have_fixed_ids():
    async def go():
        updates = SimpleNamespace()
        ids = {item.custom_id for item in UpdateView(updates).children}
        assert ids == {ku.PUBLISH, ku.PUBLISH_QWEN, ku.DISCARD}
        assert {item.custom_id for item in DeleteView(updates).children} == {ku.DELETE}

    run(go())


# ---- where it listens ------------------------------------------------------------------------
def test_only_the_configured_channel_is_claimed(tmp_path):
    updates, store, _ = build(tmp_path)
    other = Channel(name="general", ident=1)
    claimed, message = send(updates, other, attachments=[Attachment("g.pdf")])
    assert claimed is False and message.replies == [] and store.list_documents() == []
    assert send(updates, Channel(name="GIGI-Updates"), "list")[0] is True  # name: any case
    by_id = build(tmp_path, channel=str(CHANNEL_ID))[0]
    assert send(by_id, Channel(name="renamed"), "list")[0] is True
    assert send(by_id, Channel(name="gigi-updates", ident=5), "list")[0] is False


def test_threads_and_direct_messages_are_not_the_channel(tmp_path):
    updates, _, _ = build(tmp_path)
    thread = object.__new__(discord.Thread)
    assert updates.is_updates_channel(thread) is False
    direct = Channel()
    direct.guild = None
    assert updates.is_updates_channel(direct) is False and updates.is_updates_channel(None) is False


def test_everything_said_in_the_channel_is_claimed_but_chatter_gets_no_reply(tmp_path):
    updates, _, _ = build(tmp_path)
    claimed, message = send(updates, Channel(), "good morning team, @Gigi what is the plan?")
    assert claimed is True and message.replies == []


def test_a_channel_everyone_can_read_is_refused_and_explained_only_once(tmp_path):
    updates, store, _ = build(tmp_path)
    public = Channel(public=True)
    claimed, first = send(updates, public, attachments=[Attachment("g.pdf")])
    assert claimed is True and "private staff channel" in first.replies[0]["text"]
    assert store.list_documents() == []
    _, second = send(updates, public, "list")
    assert second.replies == []  # no spam: one explanation per ten minutes


def test_only_members_with_an_allowed_role_may_use_it(tmp_path):
    updates, store, _ = build(tmp_path, allowed_roles=("PM", "1001"))
    outsider = Member(roles=["Annotator"])
    _, refused = send(updates, Channel(), attachments=[Attachment("g.pdf")], author=outsider)
    assert "do not have a role" in refused.replies[0]["text"] and store.list_documents() == []
    for member in (Member(roles=["pm"]), Member(roles=["x", "y"])):  # by name; by ID (1001)
        _, ok = send(updates, Channel(), attachments=[Attachment("g.pdf")], author=member)
        assert ok.replies[0]["embed"] is not None


# ---- dropping a PDF --------------------------------------------------------------------------
def test_a_pdf_becomes_a_draft_that_is_not_live_with_checks_a_file_and_buttons(tmp_path):
    updates, store, _ = build(tmp_path)
    _, message = send(
        updates, Channel(), "Test Account Guide", [Attachment("anything.pdf")], Member(ident=77)
    )
    reply = message.replies[0]
    embed, file = reply["embed"], reply["file"]
    assert embed.title == "Draft: Test Account Guide"
    assert embed.footer.text == "document: test-account-guide.md"
    assert "Not live yet" in embed.description
    assert any(f.name == "Checks" and f.value == "Passed" for f in embed.fields)
    assert any("allow Qwen" in f.value for f in embed.fields)
    assert file.filename == "test-account-guide.md"
    assert isinstance(reply["view"], UpdateView)
    doc = store.get_document("test-account-guide.md")
    assert doc.status == "draft" and "Which account do I use?" in doc.text
    assert doc.updated_by == "Priya (discord:77)"  # who did it, for the activity log
    assert store.list_documents("current") == []


def test_the_title_falls_back_to_the_file_name(tmp_path):
    updates, store, _ = build(tmp_path)
    send(updates, Channel(), "", [Attachment("QC Handbook v2.pdf")])
    assert [d.name for d in store.list_documents()] == ["qc-handbook-v2.md"]


def test_unusable_files_get_a_clear_reason_and_store_nothing(tmp_path):
    updates, store, _ = build(tmp_path)
    _, big = send(updates, Channel(), attachments=[Attachment("big.pdf", size=30 * 1024 * 1024)])
    assert "larger than 25 MB" in big.replies[0]["text"]
    _, fake = send(updates, Channel(), attachments=[Attachment("x.pdf", data=b"MZ not a pdf")])
    assert "not a PDF" in fake.replies[0]["text"] and "embed" not in fake.replies[0]
    assert store.list_documents() == []


def test_several_pdfs_in_one_message_are_capped(tmp_path):
    updates, store, _ = build(tmp_path)
    files = [Attachment(f"doc{i}.pdf") for i in range(7)]
    _, message = send(updates, Channel(), attachments=files)
    assert "first 5" in message.replies[0]["text"]
    assert len(store.list_documents()) == 5


def test_a_failure_inside_is_reported_and_never_escapes(tmp_path, monkeypatch):
    updates, _, _ = build(tmp_path)

    def explode(*args, **kwargs):
        raise RuntimeError("database melted")

    monkeypatch.setattr(updates.ops, "new_draft", explode)
    claimed, message = send(updates, Channel(), attachments=[Attachment("g.pdf")])
    assert claimed is True and "Something went wrong" in message.replies[0]["text"]
    assert "melted" not in message.replies[0]["text"]  # details stay in the log


def test_the_real_reader_produces_the_draft_end_to_end(tmp_path, monkeypatch):
    monkeypatch.undo()  # undo the fast fake: use the real separate reader process
    updates, store, _ = build(tmp_path)
    attachment = Attachment("guide.pdf", data=make_pdf(GUIDE_LINES))
    _, message = send(updates, Channel(), "Test Account Guide", [attachment])
    doc = store.get_document("test-account-guide.md")
    assert doc is not None and "Which account do I use?" in doc.text
    assert message.replies[0]["embed"].footer.text == "document: test-account-guide.md"


# ---- editing by posting the file back --------------------------------------------------------
def test_posting_the_file_back_replaces_a_draft_and_shows_the_new_checks(tmp_path):
    updates, store, _ = build(tmp_path)
    store.create_draft("notes.md", "rough", "pm")
    _, message = send(updates, Channel(), attachments=[Attachment("notes.md", GOOD.encode())])
    reply = message.replies[0]
    assert store.get_document("notes.md").text == GOOD
    assert any(f.name == "Checks" and f.value == "Passed" for f in reply["embed"].fields)
    assert isinstance(reply["view"], UpdateView)  # still a draft: publish buttons again


def test_a_bad_edit_of_a_live_document_is_refused_and_the_old_text_stays(tmp_path):
    updates, store, _ = build(tmp_path)
    publish_doc(store, "notes.md")
    _, message = send(updates, Channel(), attachments=[Attachment("notes.md", b"no entries")])
    assert "Not saved" in message.replies[0]["text"]
    assert store.get_document("notes.md").text == GOOD


def test_a_good_edit_of_a_live_document_applies_at_once_without_publish_buttons(tmp_path):
    updates, store, _ = build(tmp_path)
    publish_doc(store, "notes.md")
    newer = GOOD.replace("Publish it.", "Do it today.")
    _, message = send(updates, Channel(), attachments=[Attachment("notes.md", newer.encode())])
    reply = message.replies[0]
    assert "Your change is in use" in reply["embed"].description and reply["view"] is None
    assert "Do it today." in store.get_document("notes.md").text


def test_odd_edit_files_get_a_helpful_answer(tmp_path):
    updates, store, _ = build(tmp_path)
    for attachment, expected in (
        (Attachment("Notes File.md", b"x"), "original name"),
        (Attachment("notes.md", b"x", size=2_000_000), "original name"),
        (Attachment("notes.md", b"\xff\xfe\x00bad"), "not UTF-8"),
        (Attachment("ghost.md", GOOD.encode()), "no document called"),
    ):
        _, message = send(updates, Channel(), attachments=[attachment])
        assert expected in message.replies[0]["text"], expected


# ---- commands --------------------------------------------------------------------------------
def test_help_and_list(tmp_path):
    updates, store, _ = build(tmp_path)
    publish_doc(store, "a.md", qwen=True)
    store.create_draft("b.md", GOOD.replace("N1", "B1"), "pm")
    _, helped = send(updates, Channel(), "help")
    assert "Drop a PDF" in helped.replies[0]["text"]
    _, listed = send(updates, Channel(), "list")
    description = listed.replies[0]["embed"].description
    assert "`a.md` · Live · 1 entries · Qwen yes" in description
    assert "`b.md` · Draft" in description


def test_get_sends_the_document_as_a_file(tmp_path):
    updates, store, _ = build(tmp_path)
    publish_doc(store, "a.md")
    _, message = send(updates, Channel(), "get a")
    assert message.replies[0]["file"].filename == "a.md"
    _, missing = send(updates, Channel(), "get nothing")
    assert "no document called" in missing.replies[0]["text"]
    _, invalid = send(updates, Channel(), "get ../etc")
    assert "not a document name" in invalid.replies[0]["text"]


def test_archive_restore_and_qwen_by_command(tmp_path):
    updates, store, _ = build(tmp_path)
    publish_doc(store, "a.md", qwen=True)
    publish_doc(store, "b.md", GOOD.replace("N1", "B1"))
    _, archived = send(updates, Channel(), "archive a")
    assert "Archived" in archived.replies[0]["text"]
    assert store.get_document("a.md").status == "archived"
    _, restored = send(updates, Channel(), "restore a")
    assert "live again" in restored.replies[0]["text"] and "yes" in restored.replies[0]["text"]
    doc = store.get_document("a.md")
    assert doc.status == "current" and doc.external_processing_approved is True  # kept
    _, off = send(updates, Channel(), "qwen a off")
    assert "no longer" in off.replies[0]["text"]
    assert store.get_document("a.md").external_processing_approved is False
    _, nonsense = send(updates, Channel(), "qwen a maybe")
    assert "qwen <name> on" in nonsense.replies[0]["text"]
    _, again = send(updates, Channel(), "restore b")
    assert "not archived" in again.replies[0]["text"]


def test_the_last_live_document_cannot_be_archived_by_command(tmp_path):
    updates, store, _ = build(tmp_path)
    publish_doc(store, "only.md")
    _, message = send(updates, Channel(), "archive only")
    assert "last published" in message.replies[0]["text"]
    assert store.get_document("only.md").status == "current"


def test_delete_asks_first_and_never_touches_a_live_document(tmp_path):
    updates, store, _ = build(tmp_path)
    store.create_draft("old.md", GOOD, "pm")
    _, ask = send(updates, Channel(), "delete old")
    reply = ask.replies[0]
    assert isinstance(reply["view"], DeleteView) and "permanently" in reply["embed"].title
    assert reply["embed"].footer.text == "document: old.md"
    assert store.get_document("old.md") is not None  # nothing happens until the button
    publish_doc(store, "live.md", GOOD.replace("N1", "L1"))
    _, refused = send(updates, Channel(), "delete live")
    assert "Archive it first" in refused.replies[0]["text"] and "view" not in refused.replies[0]


# ---- the buttons -----------------------------------------------------------------------------
def click(updates, action, footer="document: notes.md", channel=None, user=None, embeds=True):
    interaction = SimpleNamespace(
        channel=channel or Channel(),
        user=user or Member(ident=99, name="Rae"),
        message=SimpleNamespace(
            embeds=[discord.Embed().set_footer(text=footer)] if embeds else [], edit=AsyncMock()
        ),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    run(updates.on_button(interaction, action))
    return interaction


def draft(store, name="notes.md", text=GOOD):
    store.create_draft(name, text, "pm")


def test_publish_makes_it_live_without_qwen_and_removes_the_buttons(tmp_path):
    updates, store, _ = build(tmp_path)
    draft(store)
    interaction = click(updates, "publish")
    doc = store.get_document("notes.md")
    assert doc.status == "current" and doc.external_processing_approved is False
    assert doc.updated_by == "Rae (discord:99)"
    interaction.message.edit.assert_awaited_once_with(view=None)
    said = interaction.followup.send.await_args.args[0]
    assert "Published" in said and "Qwen may use it: no" in said


def test_publish_and_allow_qwen_is_its_own_button(tmp_path):
    updates, store, _ = build(tmp_path)
    draft(store)
    interaction = click(updates, "publish_qwen")
    assert store.get_document("notes.md").external_processing_approved is True
    assert "Qwen may use it: yes" in interaction.followup.send.await_args.args[0]


def test_discard_removes_a_draft_but_never_a_live_document(tmp_path):
    updates, store, _ = build(tmp_path)
    draft(store)
    click(updates, "discard")
    assert store.get_document("notes.md") is None
    publish_doc(store, "live.md", GOOD.replace("N1", "L1"))
    interaction = click(updates, "discard", footer="document: live.md")
    assert store.get_document("live.md").status == "current"
    assert "Only a draft" in interaction.followup.send.await_args.args[0]
    assert interaction.followup.send.await_args.kwargs["ephemeral"] is True


def test_the_delete_button_deletes_an_archived_document(tmp_path):
    updates, store, _ = build(tmp_path)
    publish_doc(store, "keep.md", GOOD.replace("N1", "K1"))
    publish_doc(store, "old.md")
    store.archive("old.md", "pm")
    interaction = click(updates, "delete", footer="document: old.md")
    assert store.get_document("old.md") is None
    assert "Deleted" in interaction.followup.send.await_args.args[0]


def test_publishing_something_that_fails_the_checks_says_why_and_keeps_the_buttons(tmp_path):
    updates, store, _ = build(tmp_path)
    draft(store, text="no numbered entries at all")
    interaction = click(updates, "publish")
    assert store.get_document("notes.md").status == "draft"
    interaction.message.edit.assert_not_awaited()
    assert "No numbered entries" in interaction.followup.send.await_args.args[0]


def test_buttons_refuse_the_wrong_channel_a_public_channel_and_the_wrong_person(tmp_path):
    updates, store, _ = build(tmp_path, allowed_roles=("PM",))
    draft(store)
    # Each refusal is tested alone: the clicker holds the PM role except in the last case, so
    # only the channel rules can be what refuses the first two.
    cases = (
        {"channel": Channel(name="general", ident=1), "user": Member(roles=["PM"])},
        {"channel": Channel(public=True), "user": Member(roles=["PM"])},
        {"user": Member(roles=["Annotator"])},
    )
    for case in cases:
        interaction = click(updates, "publish", **case)
        interaction.response.send_message.assert_awaited_once()
        assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True
        assert store.get_document("notes.md").status == "draft"
    interaction = click(updates, "publish", user=Member(roles=["PM"]))
    assert store.get_document("notes.md").status == "current"
    assert interaction.followup.send.await_count == 1


def test_a_button_on_a_message_that_names_no_valid_document_does_nothing(tmp_path):
    updates, store, _ = build(tmp_path)
    draft(store)
    for footer, embeds in (("document: ../evil.md", True), ("hello", True), ("", False)):
        interaction = click(updates, "publish", footer=footer, embeds=embeds)
        assert "cannot tell which document" in interaction.response.send_message.await_args.args[0]
    assert store.get_document("notes.md").status == "draft"


def test_an_unexpected_failure_in_a_button_is_reported_privately(tmp_path, monkeypatch):
    updates, store, _ = build(tmp_path)
    draft(store)

    def explode(*args, **kwargs):
        raise RuntimeError("secret details")

    monkeypatch.setattr(updates.ops, "publish", explode)
    interaction = click(updates, "publish")
    said = interaction.followup.send.await_args
    assert "went wrong" in said.args[0] and "secret details" not in said.args[0]
    assert said.kwargs["ephemeral"] is True


# ---- the answerer ----------------------------------------------------------------------------
def test_a_message_in_the_updates_channel_never_reaches_the_faq_answering():
    answerer = object.__new__(FaqAnswerer)
    answerer._handle = AsyncMock(return_value="answered")
    answerer.updates = SimpleNamespace(handle=AsyncMock(return_value=True))

    async def go():
        return await answerer.handle(SimpleNamespace(id=1))

    assert run(go()) is True
    answerer._handle.assert_not_awaited()
    answerer.updates.handle = AsyncMock(return_value=False)
    assert run(go()) == "answered"  # other channels carry on as before
    answerer.updates = None
    assert run(go()) == "answered"  # feature off: exactly the old behaviour


# ---- the first publish must not wipe Gigi's built-in FAQ -------------------------------------
def build_with_builtin(tmp_path, builtin_dir):
    store = SqliteKnowledgeStore(tmp_path / "k.sqlite3")
    settings = KnowledgeUpdatesSettings(enabled=True)
    return KnowledgeUpdates(Bot(), settings, DocumentOps(store, builtin_dir)), store


def test_publishing_into_an_empty_database_is_refused_until_the_built_in_faq_is_imported(tmp_path):
    from .conftest import ROOT

    updates, store = build_with_builtin(tmp_path, ROOT / "knowledge" / "current")
    draft(store)
    refused = click(updates, "publish")
    said = refused.followup.send.await_args.args[0]
    assert "import builtin" in said and "replace Gigi's built-in FAQ" in said
    assert store.get_document("notes.md").status == "draft"
    assert store.list_documents("current") == []

    _, imported = send(updates, Channel(), "import builtin")
    assert "Imported" in imported.replies[0]["text"]
    live = store.list_documents("current")
    assert len(live) >= 8 and any(d.external_processing_approved for d in live)  # approvals kept

    click(updates, "publish")
    assert store.get_document("notes.md").status == "current"  # now it is added to the others
    assert len(store.list_documents("current")) == len(live) + 1

    _, again = send(updates, Channel(), "import builtin")
    assert "already here" in again.replies[0]["text"]


def test_without_a_built_in_folder_there_is_nothing_to_guard_or_import(tmp_path):
    updates, store, _ = build(tmp_path)  # no built-in folder configured
    draft(store)
    click(updates, "publish")
    assert store.get_document("notes.md").status == "current"
    _, message = send(updates, Channel(), "import builtin")
    assert "No built-in documents" in message.replies[0]["text"]


def test_import_needs_its_exact_form(tmp_path):
    updates, _, _ = build(tmp_path)
    _, message = send(updates, Channel(), "import everything")
    assert "import builtin" in message.replies[0]["text"]
    assert parse_command("import") is None  # a bare word in chatter is not a command
