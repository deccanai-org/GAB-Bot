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
from gab_faq.knowledge_store import SqliteKnowledgeStore, StoreError
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
        self.user = SimpleNamespace(id=555)

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
    assert {type(view) for view in bot.views} == {UpdateView, DeleteView, ku.PanelView}


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


# ---- the button panel -----------------------------------------------------------------------
def pi(channel=None, user=None, guild=None):
    """A fake Discord interaction (what a button, menu or dialog press gives the bot)."""
    return SimpleNamespace(
        guild=guild,
        channel=channel or Channel(),
        user=user or Member(ident=99, name="Rae"),
        message=SimpleNamespace(embeds=[], edit=AsyncMock()),
        response=SimpleNamespace(
            send_message=AsyncMock(),
            defer=AsyncMock(),
            edit_message=AsyncMock(),
            send_modal=AsyncMock(),
        ),
        followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


def live_docs(store, *names, qwen=False):
    for index, name in enumerate(names):
        publish_doc(store, name, GOOD.replace("N1", f"L{index}"), qwen=qwen)


def test_the_panel_has_seven_buttons_with_fixed_ids():
    async def go():
        view = ku.PanelView(SimpleNamespace())
        assert [b.label for b in view.children] == [
            "Upload PDF",
            "Documents",
            "Uploaded files",
            "Add video link",
            "Archive everything",
            "Gigi in other channels",
            "Import built-in",
        ]
        ids = [b.custom_id for b in view.children]
        assert len(set(ids)) == 7 and all(i.startswith("gab_kb:panel_") for i in ids)

    run(go())


def test_every_panel_flow_refuses_the_wrong_channel_a_public_channel_and_the_wrong_person(tmp_path):
    updates, store, _ = build(tmp_path, allowed_roles=("PM",))
    draft(store)
    pdf = [Attachment("g.pdf")]
    flows = {
        "open_upload": lambda i: updates.open_upload(i),
        "open_documents": lambda i: updates.open_documents(i),
        "open_files": lambda i: updates.open_files(i),
        "open_archive_all": lambda i: updates.open_archive_all(i),
        "import_builtin_button": lambda i: updates.import_builtin_button(i),
        "show_document": lambda i: updates.show_document(i, "notes.md"),
        "choose_keep": lambda i: updates.choose_keep(i, ["notes.md"]),
        "confirm_archive_all": lambda i: updates.confirm_archive_all(i, ["notes.md"]),
        "document_action": lambda i: updates.document_action(i, "notes.md", "publish"),
        "on_upload_submit": lambda i: updates.on_upload_submit(i, "T", pdf),
    }
    contexts = (
        {"channel": Channel(name="general", ident=1), "user": Member(roles=["PM"])},
        {"channel": Channel(public=True), "user": Member(roles=["PM"])},
        {"user": Member(roles=["Annotator"])},
    )
    for name, flow in flows.items():
        for context in contexts:
            interaction = pi(**context)
            run(flow(interaction))
            interaction.response.send_message.assert_awaited_once()
            assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True, name
    assert [d.name for d in store.list_documents()] == ["notes.md"]  # nothing was created
    assert store.get_document("notes.md").status == "draft"  # ...or published


def test_upload_pdf_opens_a_file_picker_dialog(tmp_path):
    updates, _, _ = build(tmp_path)
    interaction = pi()
    run(updates.open_upload(interaction))
    modal = interaction.response.send_modal.await_args.args[0]
    assert isinstance(modal, ku.UploadModal) and modal.title == "Upload a PDF"


def test_the_dialog_submission_creates_a_draft_for_everyone_to_review(tmp_path):
    updates, store, _ = build(tmp_path)

    async def go():
        modal = ku.UploadModal(updates)
        modal.title_input._value = "Test Account Guide"
        modal.file_input._values = [Attachment("anything.pdf")]
        interaction = pi()
        await modal.on_submit(interaction)
        return interaction

    interaction = run(go())
    interaction.response.defer.assert_awaited_once_with(thinking=True)
    sent = interaction.followup.send.await_args
    assert sent.kwargs["embed"].footer.text == "document: test-account-guide.md"
    assert sent.kwargs["file"].filename == "test-account-guide.md"
    assert isinstance(sent.kwargs["view"], UpdateView)
    doc = store.get_document("test-account-guide.md")
    assert doc.status == "draft" and doc.updated_by == "Rae (discord:99)"
    assert store.list_documents("current") == []


def test_dialog_submissions_that_are_not_usable_are_explained_privately(tmp_path, monkeypatch):
    updates, store, _ = build(tmp_path)
    for files, expected in (
        ([], "not a PDF"),
        ([Attachment("notes.txt")], "not a PDF"),
        ([Attachment("big.pdf", size=30 * 1024 * 1024)], "larger than 25 MB"),
    ):
        interaction = pi()
        run(updates.on_upload_submit(interaction, "", files))
        assert expected in interaction.response.send_message.await_args.args[0]
        assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True

    def refuse(data):
        raise ku.PdfImportError("The PDF has no selectable text.")

    monkeypatch.setattr(ku, "extract_pages_isolated", refuse)
    interaction = pi()
    run(updates.on_upload_submit(interaction, "", [Attachment("scan.pdf")]))
    assert "no selectable text" in interaction.followup.send.await_args.args[0]
    assert store.list_documents() == []


def test_documents_lists_them_and_a_choice_opens_the_buttons_that_fit(tmp_path):
    updates, store, _ = build(tmp_path)
    empty = pi()
    run(updates.open_documents(empty))
    assert "No documents yet" in empty.followup.send.await_args.args[0]
    live_docs(store, "a.md", "b.md", qwen=True)
    draft(store)
    listed = pi()
    run(updates.open_documents(listed))
    sent = listed.followup.send.await_args
    assert sent.kwargs["ephemeral"] is True and "3 document(s)" in sent.kwargs["embed"].title
    assert len(sent.kwargs["view"].children[0].options) == 3
    labels = {}
    for name in ("a.md", "notes.md"):
        shown = pi()
        run(updates.show_document(shown, name))
        view = shown.edit_original_response.await_args.kwargs["view"]
        labels[name] = [b.label for b in view.children]
    assert labels["a.md"] == ["Download .md", "Archive", "Stop Qwen using it", "Back to the list"]
    assert "Publish & allow Qwen" in labels["notes.md"] and "Delete…" in labels["notes.md"]


def act(updates, name, action):
    interaction = pi()
    run(updates.document_action(interaction, name, action))
    return interaction


def test_document_buttons_publish_archive_restore_and_switch_qwen(tmp_path):
    updates, store, _ = build(tmp_path)
    draft(store)
    live_docs(store, "other.md")
    act(updates, "notes.md", "publish_qwen")
    doc = store.get_document("notes.md")
    assert doc.status == "current" and doc.external_processing_approved is True
    refreshed = act(updates, "notes.md", "qwen_off")
    assert store.get_document("notes.md").external_processing_approved is False
    assert refreshed.edit_original_response.await_args.kwargs["content"] == "Qwen access updated."
    act(updates, "notes.md", "qwen_on")
    assert store.get_document("notes.md").external_processing_approved is True
    act(updates, "notes.md", "archive")
    assert store.get_document("notes.md").status == "archived"
    restored = act(updates, "notes.md", "restore")
    assert store.get_document("notes.md").status == "current"
    assert "Live again" in restored.edit_original_response.await_args.kwargs["content"]


def test_document_buttons_report_a_refusal_privately(tmp_path):
    updates, store, _ = build(tmp_path)
    live_docs(store, "only.md")
    refused = act(updates, "only.md", "archive")
    assert "last published" in refused.followup.send.await_args.args[0]
    assert refused.followup.send.await_args.kwargs["ephemeral"] is True
    assert store.get_document("only.md").status == "current"


def test_delete_asks_to_confirm_then_deletes_and_cancel_keeps_it(tmp_path):
    updates, store, _ = build(tmp_path)
    draft(store)
    asked = act(updates, "notes.md", "ask_delete")
    shown = asked.response.edit_message.await_args.kwargs
    assert "permanently" in shown["embed"].title
    assert [b.label for b in shown["view"].children] == ["Yes, delete permanently", "Cancel"]
    assert store.get_document("notes.md") is not None
    cancelled = act(updates, "notes.md", "show")  # what the Cancel button does
    assert store.get_document("notes.md") is not None
    assert cancelled.edit_original_response.await_args.kwargs["embed"].title.startswith("Draft")
    done = act(updates, "notes.md", "delete")
    assert store.get_document("notes.md") is None
    assert "Deleted" in done.edit_original_response.await_args.kwargs["content"]


def test_download_sends_the_document_file_privately_and_back_returns_to_the_list(tmp_path):
    updates, store, _ = build(tmp_path)
    draft(store)
    got = act(updates, "notes.md", "download")
    sent = got.response.send_message.await_args.kwargs
    assert sent["file"].filename == "notes.md" and sent["ephemeral"] is True
    back = act(updates, "notes.md", "back")
    assert "document(s)" in back.edit_original_response.await_args.kwargs["embed"].title


def test_uploaded_files_shows_the_pdfs_and_what_became_of_them(tmp_path):
    updates, store, _ = build(tmp_path)
    nothing = pi()
    run(updates.open_files(nothing))
    embed = nothing.followup.send.await_args.kwargs["embed"]
    assert embed.fields[0].value.startswith("None yet") and embed.fields[1].value.startswith(
        "None in"
    )
    send(
        updates,
        Channel(),
        "Test Account Guide",
        [Attachment("Guide One.pdf")],
        Member(name="Priya"),
    )
    store.delete  # (the document stays; the PDF row is what this view lists)
    shown = pi()
    run(updates.open_files(shown))
    embed = shown.followup.send.await_args.kwargs["embed"]
    line = embed.fields[0].value
    assert embed.fields[0].name == "PDFs uploaded (1)"
    assert "Guide One.pdf" in line and "Priya" in line and "`test-account-guide.md`" in line
    store.delete("test-account-guide.md", "pm")
    gone = pi()
    run(updates.open_files(gone))
    assert "(document deleted)" in gone.followup.send.await_args.kwargs["embed"].fields[0].value


def test_uploaded_files_lists_the_tutorial_videos_from_the_catalog(tmp_path):
    from .conftest import ROOT

    store = SqliteKnowledgeStore(tmp_path / "k.sqlite3")
    updates = KnowledgeUpdates(
        Bot(),
        KnowledgeUpdatesSettings(enabled=True),
        DocumentOps(store, ROOT / "knowledge" / "current"),
    )
    interaction = pi()
    run(updates.open_files(interaction))
    videos = interaction.followup.send.await_args.kwargs["embed"].fields[1]
    assert videos.name.startswith("Tutorial videos (") and "http" in videos.value
    assert len(videos.value) <= 1024
    # a catalog stored in the database wins over the built-in one
    store.set_support(
        "playground-videos.yaml",
        "videos:\n- {id: v1, title: Only Video, url: 'https://drive.example/x', faq_ids: [A1]}\n",
        "pm",
    )
    interaction = pi()
    run(updates.open_files(interaction))
    videos = interaction.followup.send.await_args.kwargs["embed"].fields[1]
    assert videos.name == "Tutorial videos (1)" and "Only Video" in videos.value


def test_long_lists_are_clipped_not_rejected_by_discord(tmp_path):
    many = ku.UploadedFiles(
        tuple(
            {
                "filename": f"file-{i}.pdf",
                "size": 2048,
                "uploaded_at": "2026-11-18T10:00:00Z",
                "uploaded_by": "Priya (discord:1)",
                "sha256": str(i),
                "documents": (),
            }
            for i in range(80)
        ),
        tuple(
            {"title": f"Video {i}", "url": "https://drive.example/f", "faq_ids": ["A1"]}
            for i in range(80)
        ),
    )
    embed = ku.files_embed(many)
    assert all(len(field.value) <= 1024 for field in embed.fields)
    assert "more" in embed.fields[0].value and "more" in embed.fields[1].value


# ---- archive everything ---------------------------------------------------------------------
def test_archive_everything_needs_at_least_two_live_documents(tmp_path):
    updates, store, _ = build(tmp_path)
    live_docs(store, "only.md")
    interaction = pi()
    run(updates.open_archive_all(interaction))
    assert "nothing to archive" in interaction.followup.send.await_args.args[0]


def test_archive_everything_asks_what_to_keep_then_confirms_then_archives_the_rest(tmp_path):
    updates, store, _ = build(tmp_path)
    live_docs(store, "a.md", "b.md", "c.md")
    draft(store)
    start = pi()
    run(updates.open_archive_all(start))
    sent = start.followup.send.await_args.kwargs
    keep_select = sent["view"].children[0]
    assert sent["ephemeral"] is True and keep_select.min_values == 1 and keep_select.max_values == 3

    chosen = pi()
    run(updates.choose_keep(chosen, ["a.md"]))
    shown = chosen.edit_original_response.await_args.kwargs
    assert "Archive 2 document(s)?" == shown["embed"].title
    assert "`a.md`" in shown["embed"].description and "`b.md`" in shown["embed"].description
    assert [b.label for b in shown["view"].children] == ["Archive 2 document(s)", "Cancel"]
    assert {d.status for d in store.list_documents("current")} == {"current"}  # nothing yet

    done = pi()
    run(updates.confirm_archive_all(done, ["a.md"]))
    assert [d.name for d in store.list_documents("current")] == ["a.md"]
    assert {store.get_document(n).status for n in ("b.md", "c.md")} == {"archived"}
    assert store.get_document("notes.md").status == "draft"  # drafts are never touched
    text = done.edit_original_response.await_args.kwargs["content"]
    assert "Archived 2" in text and "`a.md`" in text


def test_archive_everything_can_never_leave_gigi_with_nothing(tmp_path):
    updates, store, _ = build(tmp_path)
    live_docs(store, "a.md", "b.md")
    for keep in ([], ["ghost.md"]):
        interaction = pi()
        run(updates.confirm_archive_all(interaction, keep))
        assert "at least one" in interaction.edit_original_response.await_args.kwargs["content"]
    assert len(store.list_documents("current")) == 2
    everything = pi()
    run(updates.choose_keep(everything, ["a.md", "b.md"]))
    assert "nothing to archive" in everything.edit_original_response.await_args.kwargs["content"]


def test_archive_everything_reports_the_ones_it_could_not_archive(tmp_path, monkeypatch):
    updates, store, _ = build(tmp_path)
    live_docs(store, "a.md", "b.md", "c.md")
    real = store.archive

    def flaky(name, actor):
        if name == "b.md":
            raise StoreError("database hiccup")
        return real(name, actor)

    monkeypatch.setattr(store, "archive", flaky)
    interaction = pi()
    run(updates.confirm_archive_all(interaction, ["a.md"]))
    text = interaction.edit_original_response.await_args.kwargs["content"]
    assert "Archived 1" in text and "Not archived: b.md: database hiccup" in text
    assert store.get_document("c.md").status == "archived"


def test_cancelling_archive_everything_changes_nothing(tmp_path):
    updates, store, _ = build(tmp_path)
    live_docs(store, "a.md", "b.md")
    interaction = pi()
    run(updates.cancel(interaction))
    assert "Nothing changed" in interaction.response.edit_message.await_args.kwargs["content"]
    assert len(store.list_documents("current")) == 2


# ---- posting the panel -----------------------------------------------------------------------
class PanelChannel(Channel):
    def __init__(self, history=(), **kwargs):
        super().__init__(**kwargs)
        self.past = list(history)
        self.sent = AsyncMock(return_value=SimpleNamespace(pin=AsyncMock()))

    async def history(self, limit=50):
        for message in self.past:
            yield message

    async def send(self, **kwargs):
        return await self.sent(**kwargs)


def old_panel(bot_id=555, footer=ku.PANEL_FOOTER):
    return SimpleNamespace(
        author=SimpleNamespace(id=bot_id),
        embeds=[discord.Embed().set_footer(text=footer)],
        edit=AsyncMock(),
    )


def test_the_panel_is_posted_once_pinned_and_then_refreshed_not_duplicated(tmp_path):
    updates, _, _ = build(tmp_path)
    fresh = PanelChannel()
    run(updates.ensure_panel(fresh))
    posted = fresh.sent.await_args.kwargs
    assert posted["embed"].footer.text == ku.PANEL_FOOTER and isinstance(
        posted["view"], ku.PanelView
    )
    fresh.sent.return_value.pin.assert_awaited_once()

    existing = old_panel()
    again = PanelChannel(
        history=[SimpleNamespace(author=SimpleNamespace(id=7), embeds=[]), existing]
    )
    run(updates.ensure_panel(again))
    existing.edit.assert_awaited_once()
    again.sent.assert_not_awaited()
    other = PanelChannel(history=[old_panel(bot_id=999), old_panel(footer="something else")])
    run(updates.ensure_panel(other))  # not ours: a new one is posted
    other.sent.assert_awaited_once()


def test_a_panel_that_cannot_be_pinned_is_still_posted(tmp_path):
    updates, _, _ = build(tmp_path)
    channel = PanelChannel()
    channel.sent.return_value.pin.side_effect = discord.HTTPException(
        SimpleNamespace(status=403, reason="Forbidden"), "missing permissions"
    )
    run(updates.ensure_panel(channel))
    channel.sent.assert_awaited_once()


def test_panels_are_posted_only_in_a_private_updates_channel(tmp_path, caplog):
    updates, _, _ = build(tmp_path)
    private, public = PanelChannel(), PanelChannel(public=True)
    other = PanelChannel(name="general", ident=1)
    for guild_channels, posts in (([private, other], 1), ([public, other], 0), ([other], 0)):
        for channel in guild_channels:
            channel.sent.reset_mock()
        guild = SimpleNamespace(text_channels=guild_channels)
        run(updates.ensure_panels([guild]))
        assert sum(c.sent.await_count for c in guild_channels) == posts
    assert "everyone in the server can read" in caplog.text or "No panel in" in caplog.text


def test_the_panel_command_posts_the_panel_again(tmp_path):
    updates, _, _ = build(tmp_path)
    channel = PanelChannel()
    _, message = send(updates, channel, "panel")
    channel.sent.assert_awaited_once()
    assert "panel" in message.replies[0]["text"]
    public = PanelChannel(public=True)
    _, refused = send(updates, public, "panel")
    public.sent.assert_not_awaited()  # a public channel gets an explanation, never a panel
    assert "private staff channel" in refused.replies[0]["text"]


# ---- found while testing with a real upload --------------------------------------------------
def test_discords_underscored_file_names_and_version_numbers_survive(tmp_path):
    updates, store, _ = build(tmp_path)
    send(updates, Channel(), "", [Attachment("GAB_-_Evaluation_Guide_-_v6.1.pdf")])
    doc = store.list_documents()[0]
    assert doc.title == "GAB - Evaluation Guide - v6.1"
    assert doc.name == "gab-evaluation-guide-v6-1.md"  # "v6.1" is not a ".1" file extension


def test_markdown_in_a_title_cannot_become_formatting_or_a_fake_link():
    assert (
        ku._escape("Guide [v2](x) *b* _i_ `c`") == "Guide \\[v2\\]\\(x\\) \\*b\\* \\_i\\_ \\`c\\`"
    )
    files = ku.UploadedFiles(
        (),
        ({"title": "x](http://evil.example) y", "url": "https://drive.example/f", "faq_ids": []},),
    )
    value = ku.files_embed(files).fields[1].value
    assert "http://evil.example" in value and "\\](" not in value.split("(http://evil")[0][-3:]
    assert value.count("](https://drive.example/f)") == 1  # only the real link is a link
    assert "[x\\]\\(http://evil.example\\) y]" in value


# ---- add a video by Google Drive link -------------------------------------------------------
DRIVE = "https://drive.google.com/file/d/1AbCdEf/view"


def ops_with_live_entries(tmp_path, builtin_dir=None):
    store = SqliteKnowledgeStore(tmp_path / "k.sqlite3")
    publish_doc(store, "a.md", GOOD)  # entry N1
    return DocumentOps(store, builtin_dir), store


def test_only_real_drive_links_are_accepted():
    for good in (DRIVE, "https://docs.google.com/document/d/1x/edit?usp=sharing"):
        assert ku.parse_drive_link(good) == good
    for bad in (
        "",
        "http://drive.google.com/file/d/1/view",  # not https
        "https://drive.google.com.evil.example/x",  # look-alike host
        "https://drive.google.com@evil.example/x",  # credentials trick
        "https://evil.example/drive.google.com/x",
        "https://youtube.com/watch?v=1",
        "https://drive.google.com:8443/x",
        "javascript:alert(1)",
        "https://drive.google.com/a b",
        "https://drive.google.com/" + "x" * 600,
    ):
        with pytest.raises(StoreError):
            ku.parse_drive_link(bad)


def test_entry_ids_are_normalised_and_checked():
    assert ku.parse_entry_ids("a5, PG3  in6;a5") == ["A5", "PG3", "IN6"]
    for bad in ("", "  ", "five", "A", "A5; DROP", "A5, " + ", ".join(f"A{i}" for i in range(20))):
        with pytest.raises(StoreError):
            ku.parse_entry_ids(bad)


def test_a_video_is_added_to_the_catalog_and_the_bot_attaches_it_to_those_answers(tmp_path):
    from gab_faq.knowledge import KnowledgeBase
    from gab_faq.knowledge_store import StoreSource
    from gab_faq.search import split_entries

    ops, store = ops_with_live_entries(tmp_path)
    video = ops.add_video("Account setup walkthrough", DRIVE, "n1", "Rae (discord:2)")
    assert video == {
        "id": "account-setup-walkthrough",
        "title": "Account setup walkthrough",
        "url": DRIVE,
        "faq_ids": ["N1"],
    }
    assert store.audit_log(1)[0]["actor"] == "Rae (discord:2)"
    source = StoreSource(store, tmp_path / "none", poll_seconds=0)
    knowledge = KnowledgeBase(tmp_path / "live", source=source)
    entry = next(e for d in knowledge.documents for e in split_entries(d) if e.id == "N1")
    assert [v.title for v in entry.tutorials] == ["Account setup walkthrough"]
    assert f"<{DRIVE}>" in entry.answer_body  # what freelancers see under the answer


def test_adding_one_video_never_replaces_the_catalog_built_into_the_image(tmp_path):
    from .conftest import ROOT

    built_in = ROOT / "knowledge" / "current"
    ops, store = ops_with_live_entries(tmp_path, built_in)
    before = len(ops.files().videos)
    assert before >= 10
    ops.add_video("One more", DRIVE, "N1", "pm")
    after = ops.files().videos
    assert len(after) == before + 1 and "One more" in [v["title"] for v in after]
    assert store.get_support("playground-videos.yaml").count("playground-01") == 1


def test_video_ids_stay_unique_and_a_link_is_added_only_once(tmp_path):
    ops, _ = ops_with_live_entries(tmp_path)
    first = ops.add_video("Setup", DRIVE, "N1", "pm")
    second = ops.add_video("Setup", "https://drive.google.com/file/d/2/view", "N1", "pm")
    assert (first["id"], second["id"]) == ("setup", "setup-2")
    with pytest.raises(StoreError, match="already in the tutorial catalog"):
        ops.add_video("Again", DRIVE, "N1", "pm")


def test_a_video_needs_a_title_a_drive_link_and_entries_that_exist(tmp_path):
    ops, store = ops_with_live_entries(tmp_path)
    for args, expected in (
        (("", DRIVE, "N1"), "title"),
        (("T", "https://evil.example/x", "N1"), "Google Drive link"),
        (("T", DRIVE, ""), "which FAQ entries"),
        (("T", DRIVE, "ZZ9"), "not in any live document: ZZ9"),
        (("password: hunter2", DRIVE, "N1"), "could not be added"),
    ):
        with pytest.raises(StoreError, match=expected):
            ops.add_video(*args, "pm")
    assert store.get_support("playground-videos.yaml") is None  # nothing was saved


def test_a_video_cannot_be_added_before_any_document_is_live(tmp_path):
    ops = DocumentOps(SqliteKnowledgeStore(tmp_path / "k.sqlite3"))
    with pytest.raises(StoreError, match="Import built-in"):
        ops.add_video("T", DRIVE, "A1", "pm")


def test_add_video_link_opens_a_dialog_and_submitting_it_adds_the_video(tmp_path):
    updates, store, _ = build(tmp_path)
    publish_doc(store, "a.md", GOOD)
    opened = pi()
    run(updates.open_add_video(opened))
    modal = opened.response.send_modal.await_args.args[0]
    assert isinstance(modal, ku.AddVideoModal) and modal.title == "Add a video link"

    async def go():
        dialog = ku.AddVideoModal(updates)
        dialog.title_input._value = "Setup walkthrough"
        dialog.link_input._value = DRIVE
        dialog.entries_input._value = "N1"
        interaction = pi()
        await dialog.on_submit(interaction)
        return interaction

    done = run(go())
    done.response.defer.assert_awaited_once_with(ephemeral=True)
    said = done.followup.send.await_args
    assert "Added **Setup walkthrough**" in said.args[0] and said.kwargs["ephemeral"] is True
    assert "Setup walkthrough" in store.get_support("playground-videos.yaml")


def test_a_refused_video_is_explained_privately_and_the_panel_rules_apply(tmp_path):
    updates, store, _ = build(tmp_path, allowed_roles=("PM",))
    publish_doc(store, "a.md", GOOD)
    bad = pi(user=Member(roles=["PM"]))
    run(updates.on_add_video_submit(bad, "T", "https://evil.example/x", "N1"))
    assert "Not added" in bad.followup.send.await_args.args[0]
    assert bad.followup.send.await_args.kwargs["ephemeral"] is True
    for context in (
        {"channel": Channel(name="general", ident=1), "user": Member(roles=["PM"])},
        {"channel": Channel(public=True), "user": Member(roles=["PM"])},
        {"user": Member(roles=["Annotator"])},
    ):
        for flow in (
            lambda i: updates.open_add_video(i),
            lambda i: updates.on_add_video_submit(i, "T", DRIVE, "N1"),
        ):
            interaction = pi(**context)
            run(flow(interaction))
            assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True
    assert store.get_support("playground-videos.yaml") is None
