"""The knowledge database: validation, lifecycle, and how the bot picks published documents up."""

import os
import sqlite3
import threading
import uuid
from dataclasses import replace
from urllib.parse import quote

import pytest
import yaml

from gab_faq.config import load_settings
from gab_faq.knowledge import KnowledgeBase, build_knowledge
from gab_faq.knowledge_store import (
    PostgresKnowledgeStore,
    ReconnectingStore,
    SqliteKnowledgeStore,
    StoreError,
    StoreSource,
    open_store,
    redact_location,
    slugify,
    validate_document,
)
from gab_faq.search import split_entries

from .conftest import ROOT

# A superuser URL of a throwaway PostgreSQL, e.g.
#   docker run -d -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=pw postgres:16-alpine
#   GAB_TEST_POSTGRES_URL=postgresql://postgres:pw@127.0.0.1:55432/postgres
# Each test gets its own schema, dropped afterwards. Without it the PostgreSQL runs are skipped.
POSTGRES_ADMIN_URL = os.environ.get("GAB_TEST_POSTGRES_URL", "")


def _in_schema(url: str, schema: str) -> str:
    options = quote(f"-c search_path={schema}")
    return f"{url}{'&' if '?' in url else '?'}options={options}"


def doc(title="Sample FAQ", ids=("T1", "T2"), header_extra="", body_extra=""):
    entries = "\n".join(f"{i}. Question {i}?\nAnswer for {i}.\n" for i in ids)
    return (
        f"---\ntitle: {title}\naudience: all\nphase: '6'\nupdated: 2026-11-18\n{header_extra}---\n\n"
        f"## Section\n\n{body_extra}{entries}"
    )


@pytest.fixture(params=["sqlite", "postgres"])
def location(request, tmp_path):
    """Where this test's database lives: every lifecycle test runs on both backends."""
    if request.param == "sqlite":
        yield tmp_path / "k.sqlite3"
        return
    if not POSTGRES_ADMIN_URL:
        pytest.skip("set GAB_TEST_POSTGRES_URL to run the PostgreSQL tests")
    psycopg = pytest.importorskip("psycopg")
    schema = "gabtest_" + uuid.uuid4().hex[:12]
    with psycopg.connect(POSTGRES_ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
    try:
        yield _in_schema(POSTGRES_ADMIN_URL, schema)
    finally:
        with psycopg.connect(POSTGRES_ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture
def store(location):
    opened = open_store(location)
    yield opened
    opened.close()


@pytest.fixture
def sqlite_store(tmp_path):
    return SqliteKnowledgeStore(tmp_path / "s.sqlite3")


def publish(store, name, text, qwen=False, actor="pm"):
    store.create_draft(name, text, actor)
    return store.publish(name, actor, external_processing_approved=qwen)


# ---- validation ------------------------------------------------------------------------------
def test_a_good_document_passes_and_reports_its_entries():
    check = validate_document("sample.md", doc())
    assert check.ok and check.entry_ids == ("T1", "T2") and check.title == "Sample FAQ"


@pytest.mark.parametrize(
    "name,text,fragment",
    [
        ("Bad Name.md", doc(), "file name"),
        ("../evil.md", doc(), "file name"),
        ("a.md", "just some prose without entries", "No numbered entries"),
        ("a.md", doc(ids=("T1", "T1")), "more than once"),
        ("a.md", doc(body_extra="the password is hunter22\n\n"), "password"),
        ("a.md", "---\ntitle: x\nT1. A?\nB.\n", "not closed"),
        ("a.md", doc(header_extra="status: archived\n"), "archived"),
        ("a.md", doc(header_extra="audience: nobody\n"), "audience"),
    ],
)
def test_invalid_documents_are_refused_with_a_reason(name, text, fragment):
    check = validate_document(name, text)
    assert not check.ok and fragment in " ".join(check.problems)


def test_entry_ids_may_not_clash_with_another_published_document():
    check = validate_document("b.md", doc(ids=("T2", "T9")), {"a.md": {"T1", "T2"}})
    assert not check.ok and "T2" in check.problems[0] and "a.md" in check.problems[0]


def test_text_outside_entries_is_a_warning_not_an_error():
    check = validate_document("a.md", doc().replace("## Section\n", "## Section\nloose text\n"))
    assert check.ok and "outside a numbered entry" in check.warnings[0]


def test_slugify_gives_safe_names():
    assert slugify("GAB - Production Guide v6.1.pdf") == "gab-production-guide-v6-1.md"
    assert slugify("../../etc/passwd") == "etc-passwd.md"
    assert slugify("???") == "document.md"


# ---- lifecycle -------------------------------------------------------------------------------
def test_a_draft_is_not_live_until_published_and_publishing_bumps_the_revision(store):
    store.create_draft("a.md", doc(), "pm")
    assert store.revision() == 0 and store.list_documents("current") == []
    store.publish("a.md", "pm")
    assert store.revision() == 1 and [d.name for d in store.list_documents("current")] == ["a.md"]


def test_qwen_approval_is_never_on_unless_asked(store):
    store.create_draft("a.md", doc(), "pm")
    assert store.publish("a.md", "pm").external_processing_approved is False
    assert store.set_external_approval("a.md", True, "pm").external_processing_approved is True


def test_publish_refuses_invalid_text_and_a_live_document_cannot_be_saved_broken(store):
    store.create_draft("a.md", "no entries here", "pm")
    with pytest.raises(StoreError, match="Cannot publish"):
        store.publish("a.md", "pm")
    publish(store, "b.md", doc(ids=("B1",)))
    with pytest.raises(StoreError, match="Not saved"):
        store.save_text("b.md", "ruined", "pm")
    assert "B1." in store.get_document("b.md").text


def test_a_draft_can_be_saved_while_still_incomplete(store):
    store.create_draft("a.md", doc(), "pm")
    store.save_text("a.md", "work in progress", "pm")
    assert store.get_document("a.md").text == "work in progress"


def test_entry_ids_are_unique_across_published_documents(store):
    publish(store, "a.md", doc(ids=("T1",)))
    store.create_draft("b.md", doc(ids=("T1", "T5")), "pm")
    with pytest.raises(StoreError, match="already used in a.md"):
        store.publish("b.md", "pm")


def test_archive_keeps_the_document_and_can_be_restored_but_not_the_last_live_one(store):
    publish(store, "a.md", doc(ids=("A1",)))
    with pytest.raises(StoreError, match="last published"):
        store.archive("a.md", "pm")
    publish(store, "b.md", doc(ids=("B1",)))
    store.archive("a.md", "pm")
    assert store.get_document("a.md").status == "archived"
    assert [d.name for d in store.list_documents("current")] == ["b.md"]
    assert store.publish("a.md", "pm").status == "current"


def test_delete_needs_the_document_to_be_offline_and_keeps_history_and_audit(store):
    publish(store, "a.md", doc(ids=("A1",)))
    publish(store, "b.md", doc(ids=("B1",)))
    with pytest.raises(StoreError, match="Archive"):
        store.delete("a.md", "pm")
    store.archive("a.md", "pm")
    store.delete("a.md", "pm")
    assert store.get_document("a.md") is None
    assert store.history("a.md") and any(r["action"] == "delete" for r in store.audit_log())


def test_rollback_restores_an_earlier_version_as_a_new_version(store):
    publish(store, "a.md", doc(ids=("A1",)))
    first = store.history("a.md")[-1]["id"]
    store.save_text("a.md", doc(ids=("A1", "A2")), "pm")
    store.rollback("a.md", first, "pm")
    assert "A2." not in store.get_document("a.md").text
    assert store.history("a.md")[0]["note"].startswith("restored version")
    with pytest.raises(StoreError):
        store.rollback("a.md", 999999, "pm")


def test_published_for_answers_prefers_latest_versions_row(store):
    publish(store, "a.md", doc(ids=("A1",)))
    store.save_text("a.md", doc(ids=("A1", "A2")), "pm")
    # Simulate documents.text lagging behind versions (manual DB drift / race).
    with store._lock, store._tx():
        store._db.execute(
            "UPDATE documents SET text=? WHERE name=?",
            (doc(ids=("A1",)), "a.md"),
        )
    served = store.published_for_answers()
    assert len(served) == 1
    assert "A2." in served[0].text


def test_audit_log_records_who_did_what(store):
    publish(store, "a.md", doc(), actor="priya")
    assert {(r["actor"], r["action"]) for r in store.audit_log()} >= {
        ("priya", "create"),
        ("priya", "publish"),
    }


def test_names_must_be_safe_and_unique(store):
    with pytest.raises(StoreError):
        store.create_draft("../x.md", doc(), "pm")
    store.create_draft("a.md", doc(), "pm")
    with pytest.raises(StoreError, match="already exists"):
        store.create_draft("a.md", doc(), "pm")
    assert store.unique_name("a.md") == "a-2.md"


def test_pdf_storage_checks_the_file_really_is_a_pdf_and_dedupes(store):
    with pytest.raises(StoreError, match="not a PDF"):
        store.put_pdf(b"MZ not a pdf", "x.pdf", "pm")
    digest = store.put_pdf(b"%PDF-1.4 fake", "x.pdf", "pm")
    assert store.put_pdf(b"%PDF-1.4 fake", "y.pdf", "pm") == digest
    assert store.get_pdf(digest)[1] == b"%PDF-1.4 fake"


def test_the_bots_read_only_connection_cannot_change_anything(store, location):
    publish(store, "a.md", doc())
    reader = open_store(location, readonly=True)
    assert [d.name for d in reader.list_documents("current")] == ["a.md"]
    with pytest.raises(StoreError):
        reader.archive("a.md", "bot")
    # Even raw SQL is refused by the database session itself (SQLite and PostgreSQL).
    with pytest.raises(Exception, match=r"(?i)read-?only"):
        reader._db.execute("DELETE FROM documents")
    assert store.get_document("a.md") is not None
    reader.close()


# ---- how the bot picks documents up ----------------------------------------------------------
class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def live_knowledge(tmp_path, store, baked_text=None):
    baked = tmp_path / "baked"
    baked.mkdir(exist_ok=True)
    if baked_text:
        (baked / "baked.md").write_text(baked_text, encoding="utf-8")
    source = StoreSource(store, baked, poll_seconds=0, retry_seconds=0, clock=Clock())
    return KnowledgeBase(tmp_path / "live", source=source)


def entry_ids(kb):
    return sorted(e.id for d in kb.documents for e in split_entries(d))


def test_the_bot_serves_the_built_in_documents_until_something_is_published(tmp_path, store):
    kb = live_knowledge(tmp_path, store, baked_text=doc(ids=("B1",)))
    assert entry_ids(kb) == ["B1"]


def test_publishing_replaces_the_built_in_documents_and_the_bot_reloads(tmp_path, store):
    kb = live_knowledge(tmp_path, store, baked_text=doc(ids=("B1",)))
    publish(store, "new.md", doc(ids=("N1", "N2")), qwen=True)
    assert kb.reload_if_changed() is True
    assert entry_ids(kb) == ["N1", "N2"]
    assert all(d.external_processing_approved for d in kb.documents)
    assert kb.reload_if_changed() is False  # unchanged: no needless index rebuild


def test_not_ticking_qwen_keeps_the_document_unapproved_for_qwen(tmp_path, store):
    publish(store, "new.md", doc(ids=("N1",)), qwen=False)
    kb = live_knowledge(tmp_path, store)
    assert [d.external_processing_approved for d in kb.documents] == [False]


def test_archived_and_draft_documents_are_never_served(tmp_path, store):
    publish(store, "a.md", doc(ids=("A1",)))
    publish(store, "b.md", doc(ids=("B1",)))
    store.create_draft("c.md", doc(ids=("C1",)), "pm")
    kb = live_knowledge(tmp_path, store)
    assert entry_ids(kb) == ["A1", "B1"]
    store.archive("a.md", "pm")
    assert kb.reload_if_changed() is True
    assert entry_ids(kb) == ["B1"] and not (tmp_path / "live" / "a.md").exists()


def test_an_unreachable_database_keeps_the_last_good_faq(tmp_path, store):
    publish(store, "a.md", doc(ids=("A1",)))
    kb = live_knowledge(tmp_path, store)

    def broken():
        raise sqlite3.OperationalError("database is down")

    store.revision = broken
    kb.reload_if_changed()
    assert entry_ids(kb) == ["A1"]


def test_a_database_that_is_missing_at_start_is_not_a_startup_error_and_recovers(tmp_path):
    path = tmp_path / "later.sqlite3"
    baked = tmp_path / "baked"
    baked.mkdir()
    (baked / "baked.md").write_text(doc(ids=("B1",)), encoding="utf-8")
    clock = Clock()
    source = StoreSource(
        ReconnectingStore(lambda: SqliteKnowledgeStore(path, readonly=True)),
        baked,
        poll_seconds=0,
        retry_seconds=0,
        clock=clock,
    )
    kb = KnowledgeBase(tmp_path / "live", source=source)
    assert entry_ids(kb) == ["B1"]
    writer = SqliteKnowledgeStore(path)
    publish(writer, "n.md", doc(ids=("N1",)))
    clock.now += 1
    assert kb.reload_if_changed() is True and entry_ids(kb) == ["N1"]


def test_a_document_that_fails_validation_is_skipped_and_the_others_still_load(tmp_path, store):
    publish(store, "a.md", doc(ids=("A1",)))
    publish(store, "b.md", doc(ids=("B1",)))
    store._db.execute(
        "UPDATE documents SET text='broken' WHERE name='b.md'"
    )  # as if edited outside the UI
    store._db.execute("UPDATE meta SET value=99 WHERE key='revision'")
    kb = live_knowledge(tmp_path, store)
    assert entry_ids(kb) == ["A1"]


def test_the_poll_interval_limits_how_often_the_database_is_asked(tmp_path, store):
    publish(store, "a.md", doc(ids=("A1",)))
    clock = Clock()
    source = StoreSource(store, tmp_path / "baked", poll_seconds=5, clock=clock)
    kb = KnowledgeBase(tmp_path / "live", source=source)
    calls = []
    original = store.revision
    store.revision = lambda: calls.append(1) or original()
    for _ in range(10):
        kb.reload_if_changed()
    assert calls == []  # within 5 s of the first check
    clock.now = 6
    kb.reload_if_changed()
    assert calls == [1]


def test_the_policy_file_for_the_bot_comes_from_the_database_flags(tmp_path, store):
    publish(store, "a.md", doc(ids=("A1",)), qwen=True)
    publish(store, "b.md", doc(ids=("B1",)), qwen=False)
    live_knowledge(tmp_path, store)
    policy = yaml.safe_load((tmp_path / "live" / "entry-policy.yaml").read_text(encoding="utf-8"))
    assert policy["documents"] == {
        "a.md": {"external_processing_approved": True},
        "b.md": {"external_processing_approved": False},
    }


def test_importing_the_built_in_documents_serves_exactly_what_the_image_serves(tmp_path, store):
    built_in = ROOT / "knowledge" / "current"
    imported = store.import_directory(built_in)
    assert len(imported) >= 8
    kb = live_knowledge(tmp_path, store)
    reference = KnowledgeBase(built_in)

    def shape(knowledge):
        return {
            d.path.name: (
                d.external_processing_approved,
                [(e.id, e.title, e.body, e.status) for e in split_entries(d)],
                d.entry_metadata,
                d.tutorials,
            )
            for d in knowledge.documents
        }

    assert shape(kb) == shape(reference)
    assert store.import_directory(built_in) == []  # idempotent


def test_build_knowledge_uses_the_database_only_when_configured(tmp_path, store, location):
    publish(store, "n.md", doc(ids=("N1",)))
    plain = replace(load_settings(), knowledge_store=None)
    assert build_knowledge(plain).directory == plain.knowledge_dir
    configured = replace(
        load_settings(),
        knowledge_store=location,
        knowledge_live_dir=tmp_path / "live",
    )
    kb = build_knowledge(configured)
    assert entry_ids(kb) == ["N1"]


def test_settings_read_the_database_path_from_the_environment(monkeypatch, tmp_path):
    assert load_settings().knowledge_store is None  # off unless configured
    monkeypatch.setenv("GAB_KNOWLEDGE_DB", str(tmp_path / "x.sqlite3"))
    monkeypatch.setenv("GAB_KNOWLEDGE_LIVE_DIR", str(tmp_path / "liv"))
    settings = load_settings()
    assert settings.knowledge_store == tmp_path / "x.sqlite3"
    assert settings.knowledge_live_dir == tmp_path / "liv"


# ---- both backends: transactions, concurrency, addresses -------------------------------------
def test_a_failed_write_is_rolled_back_completely(store, monkeypatch):
    store.create_draft("a.md", doc(ids=("A1",)), "pm")

    def explode(*args, **kwargs):
        raise RuntimeError("the database failed halfway through publishing")

    monkeypatch.setattr(store, "_audit", explode)
    with pytest.raises(RuntimeError):
        store.publish("a.md", "pm")
    monkeypatch.undo()
    assert store.get_document("a.md").status == "draft"  # the status change did not stick
    assert store.revision() == 0
    assert (
        len(store.history("a.md")) == 1
    )  # only "created": the failed "published" snapshot is gone


def test_two_admins_cannot_publish_clashing_entry_ids_at_the_same_time(store, location):
    """Check-then-write is serialised: of two drafts that reuse an entry ID, exactly one goes live."""
    store.create_draft("a.md", doc(ids=("X1",)), "pm")
    store.create_draft("b.md", doc(ids=("X1",)), "pm")
    other = open_store(location)
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def publish_with(target, name):
        barrier.wait()
        try:
            target.publish(name, "pm")
            outcomes.append("published")
        except StoreError:
            outcomes.append("refused")

    threads = [
        threading.Thread(target=publish_with, args=(store, "a.md")),
        threading.Thread(target=publish_with, args=(other, "b.md")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    other.close()
    assert sorted(outcomes) == ["published", "refused"]
    assert len(store.list_documents("current")) == 1


def test_reconnecting_store_opens_again_after_a_database_failure():
    class Flaky:
        opened = 0
        broken_once = False  # the network fails once, whichever connection is in use

        def __init__(self):
            Flaky.opened += 1

        def revision(self):
            if not Flaky.broken_once:
                Flaky.broken_once = True
                raise ConnectionError("connection dropped")
            return 7

        def close(self):
            pass

    holder = ReconnectingStore(Flaky)
    with pytest.raises(ConnectionError):
        holder.revision()
    assert holder.revision() == 7  # a fresh connection, not the broken one
    assert Flaky.opened == 2


def test_reconnecting_store_does_not_reconnect_for_a_refused_change():
    class Strict:
        opened = 0

        def __init__(self):
            Strict.opened += 1

        def archive(self):
            raise StoreError("refused")

    holder = ReconnectingStore(Strict)
    for _ in range(2):
        with pytest.raises(StoreError):
            holder.archive()
    assert Strict.opened == 1


def test_database_addresses_are_shown_without_their_password():
    url = "postgresql://gab_admin:S3cret%21@db.example.com:5432/gab?sslmode=require&password=x"
    shown = redact_location(url)
    assert shown == "postgresql://gab_admin@db.example.com:5432/gab"
    assert "S3cret" not in shown and "password" not in shown
    assert redact_location("C:/data/k.sqlite3") == "C:/data/k.sqlite3"
    assert redact_location("postgresql://[bad").startswith("postgresql://")


def test_a_postgres_url_in_the_environment_is_kept_but_hidden(monkeypatch):
    url = "postgresql://bot:hunter2@db.example.com/gab"
    monkeypatch.setenv("GAB_KNOWLEDGE_DB", url)
    settings = load_settings()
    assert settings.knowledge_store == url
    assert "hunter2" not in repr(settings)


def test_the_postgres_driver_missing_is_a_clear_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "psycopg" or name.startswith("psycopg."):
            raise ImportError("no psycopg")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(StoreError, match="psycopg"):
        PostgresKnowledgeStore("postgresql://u:p@127.0.0.1:1/x")


def test_postgres_unreachable_server_is_an_error_not_a_hang():
    import time

    pytest.importorskip("psycopg")
    started = time.monotonic()
    with pytest.raises(Exception):
        PostgresKnowledgeStore("postgresql://u:p@127.0.0.1:1/x?connect_timeout=2")
    assert time.monotonic() - started < 10


def test_slugify_removes_only_real_file_extensions():
    assert slugify("Guide v6.1") == "guide-v6-1.md"
    assert slugify("Guide v6.1.pdf") == "guide-v6-1.md"
    assert slugify("NOTES.PDF") == "notes.md"
    assert slugify("a.docx") == "a.md" and slugify("a.b.c") == "a-b-c.md"


def test_uploaded_pdfs_are_listed_without_their_bytes(store):
    assert store.list_pdfs() == []
    store.put_pdf(b"%PDF-1.4 first", "First Guide.pdf", "Priya (discord:1)")
    store.put_pdf(b"%PDF-1.4 second!", "Second.pdf", "Rae (discord:2)")
    rows = store.list_pdfs()
    assert [r["filename"] for r in rows] == ["Second.pdf", "First Guide.pdf"] or {
        r["filename"] for r in rows
    } == {"First Guide.pdf", "Second.pdf"}
    first = next(r for r in rows if r["filename"] == "First Guide.pdf")
    assert first["size"] == len(b"%PDF-1.4 first") and first["uploaded_by"] == "Priya (discord:1)"
    assert "data" not in first and len(first["sha256"]) == 64
