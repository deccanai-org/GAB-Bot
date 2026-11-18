"""PostgreSQL-only behaviour of the knowledge store: the bot's least-privilege account, dropped
connections, binary PDFs. The shared lifecycle tests run on PostgreSQL too (test_knowledge_store.py).

Needs a throwaway server; CI provides one as a service. Locally:

    docker run -d -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=pw postgres:16-alpine
    GAB_TEST_POSTGRES_URL=postgresql://postgres:pw@127.0.0.1:55432/postgres pytest
"""

import uuid

import pytest

from gab_faq.knowledge import KnowledgeBase
from gab_faq.knowledge_store import StoreSource, open_store

from .test_knowledge_store import POSTGRES_ADMIN_URL, _in_schema, doc, entry_ids, publish

pytest.importorskip("psycopg")


@pytest.fixture
def location():
    """Overrides the two-backend fixture of test_knowledge_store: always PostgreSQL, in a schema
    of its own that is dropped afterwards."""
    import psycopg

    if not POSTGRES_ADMIN_URL:
        pytest.skip("set GAB_TEST_POSTGRES_URL to run the PostgreSQL tests")
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


def _schema_of(url: str) -> str:
    return url.split("search_path%3D")[1]


def test_postgres_a_dropped_connection_is_reopened(store):
    import psycopg

    publish(store, "a.md", doc(ids=("A1",)))
    with psycopg.connect(POSTGRES_ADMIN_URL, autocommit=True) as admin:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE application_name = 'gab-faq-admin' AND pid <> pg_backend_pid()"
        )
    assert store.revision() == 1  # the read is retried once on a fresh connection
    assert [d.name for d in store.list_documents("current")] == ["a.md"]


def test_postgres_the_bots_account_needs_select_on_three_tables_only(store, location, tmp_path):
    """The grants in docs/knowledge-admin.md are enough for the bot, and no more."""
    import psycopg
    from psycopg import sql

    publish(store, "a.md", doc(ids=("A1",)), qwen=True)
    store.set_support("playground-videos.yaml", "videos: []\n", "pm")
    schema = _schema_of(location)
    role = "gabbot_" + uuid.uuid4().hex[:10]
    password = "pw-" + uuid.uuid4().hex
    with psycopg.connect(POSTGRES_ADMIN_URL, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        admin.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            )
        )
        for table in ("documents", "support", "meta"):
            admin.execute(
                sql.SQL("GRANT SELECT ON {}.{} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(table), sql.Identifier(role)
                )
            )
    try:
        host_and_db = POSTGRES_ADMIN_URL.split("@", 1)[1]
        url = _in_schema(f"postgresql://{role}:{password}@{host_and_db}", schema)
        reader = open_store(url, readonly=True)
        source = StoreSource(reader, tmp_path / "none", poll_seconds=0)
        kb = KnowledgeBase(tmp_path / "live", source=source)
        assert entry_ids(kb) == ["A1"]
        assert [d.external_processing_approved for d in kb.documents] == [True]
        assert (tmp_path / "live" / "playground-videos.yaml").exists()
        for forbidden in ("pdfs", "versions", "audit"):
            with pytest.raises(Exception, match="(?i)permission denied"):
                reader._db.execute(f"SELECT * FROM {forbidden}")
        with pytest.raises(Exception, match="(?i)read-only|permission denied"):
            reader._db.execute("UPDATE documents SET status='archived'")
        reader.close()
    finally:
        with psycopg.connect(POSTGRES_ADMIN_URL, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_postgres_pdfs_round_trip_as_bytes(store):
    pdf = b"%PDF-1.7\n" + bytes(range(256)) * 200
    digest = store.put_pdf(pdf, "binary.pdf", "pm")
    assert store.get_pdf(digest) == ("binary.pdf", pdf)
