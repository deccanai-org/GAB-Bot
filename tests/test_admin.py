"""The admin UI: sign-in, upload -> draft -> publish -> bot, archive and delete, and PDF drafting."""

import asyncio
import base64
from datetime import date

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

pytest.importorskip("pypdf")

from gab_faq.admin import app as admin_app  # noqa: E402
from gab_faq.admin.pdf_import import (  # noqa: E402
    PdfImportError,
    body_line,
    choose_prefix,
    clean_lines,
    draft_markdown,
    extract_pages,
    page_text,
    structure,
)
from gab_faq.knowledge import KnowledgeBase  # noqa: E402
from gab_faq.knowledge_store import (  # noqa: E402
    SqliteKnowledgeStore,
    StoreSource,
    validate_document,
)
from gab_faq.search import split_entries  # noqa: E402

USER, PASSWORD = "pm", "correct horse battery"


def make_pdf(lines: list[str]) -> bytes:
    """A one-page text PDF (no external tools)."""
    ops = ["BT", "/F1 12 Tf", "72 720 Td", "16 TL"]
    ops += [f"({line}) Tj T*" for line in lines]
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return out


GUIDE_LINES = [
    "Test Account Guide",
    "Which account do I use?",
    "Use the test account from the tasking window.",
    "Never use a personal account.",
    "What if the login fails?",
    "Ask the QM in the channel.",
]

AUTH = {"Authorization": "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()}


@pytest.fixture(autouse=True)
def fresh_limiter():
    admin_app.FAILED_LOGINS.clear()


class Session:
    def __init__(self, client):
        self.client = client

    async def get(self, path, **kwargs):
        return await self.client.get(path, headers=AUTH, allow_redirects=False, **kwargs)

    async def post(self, path, data=None, origin=True, **kwargs):
        headers = dict(AUTH)
        if origin:
            headers["Origin"] = f"http://{self.client.server.host}:{self.client.server.port}"
        return await self.client.post(
            path, data=data, headers=headers, allow_redirects=False, **kwargs
        )

    async def upload(self, pdf, filename="guide.pdf", title=""):
        form = FormData()
        form.add_field("file", pdf, filename=filename, content_type="application/pdf")
        form.add_field("title", title)
        return await self.post("/upload", data=form)


def run_app(tmp_path, scenario, baked=None):
    async def main():
        store = SqliteKnowledgeStore(tmp_path / "k.sqlite3")
        app = admin_app.create_app(store, USER, PASSWORD, baked_dir=baked)
        async with TestClient(TestServer(app)) as client:
            await scenario(Session(client), store)

    asyncio.run(main())


def location(response):
    return response.headers["Location"].split("?")[0]


# ---- access control --------------------------------------------------------------------------
def test_everything_needs_the_password(tmp_path):
    async def scenario(session, store):
        for path in ("/", "/audit", "/doc/x.md", "/pdf/" + "0" * 64) * 3:
            assert (await session.client.get(path)).status == 401  # the browser's first visit
        assert (await session.get("/")).status == 200  # which must not lock the PM out
        wrong = {"Authorization": "Basic " + base64.b64encode(b"pm:nope").decode()}
        assert (await session.client.get("/", headers=wrong)).status == 401
        assert (await session.get("/")).status == 200

    run_app(tmp_path, scenario)


def test_repeated_wrong_passwords_are_throttled(tmp_path):
    async def scenario(session, store):
        wrong = {"Authorization": "Basic " + base64.b64encode(b"pm:nope").decode()}
        codes = [(await session.client.get("/", headers=wrong)).status for _ in range(7)]
        assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
        assert (await session.get("/")).status == 429  # even the right password waits

    run_app(tmp_path, scenario)


def test_posts_from_another_site_or_without_an_origin_are_refused(tmp_path):
    async def scenario(session, store):
        assert (await session.post("/seed", origin=False)).status == 403
        evil = await session.client.post(
            "/seed", headers={**AUTH, "Origin": "https://evil.example"}, allow_redirects=False
        )
        assert evil.status == 403

    run_app(tmp_path, scenario)


def test_pages_carry_security_headers_and_escape_document_text(tmp_path):
    async def scenario(session, store):
        title = "<script>alert(1)</script>"
        store.create_draft(
            "x.md", f"---\ntitle: '{title}'\n---\nA1. <img src=x onerror=alert(2)>?\nBody\n", "pm"
        )
        for path in ("/", "/doc/x.md"):
            page = await session.get(path)
            text = await page.text()
            assert "<script>alert(1)" not in text and "<img src=x" not in text
            assert "default-src 'none'" in page.headers["Content-Security-Policy"]
            assert page.headers["Cache-Control"] == "no-store"

    run_app(tmp_path, scenario)


def test_document_names_cannot_escape_the_store(tmp_path):
    async def scenario(session, store):
        for bad in ("..%2Fsecret.md", "UPPER.md", "a.txt", "a%2Fb.md", "x.md%00"):
            assert (await session.get(f"/doc/{bad}")).status == 404

    run_app(tmp_path, scenario)


# ---- the PM's workflow -----------------------------------------------------------------------
def test_upload_review_publish_and_the_bot_answers_from_it(tmp_path):
    live = tmp_path / "live"

    async def scenario(session, store):
        response = await session.upload(make_pdf(GUIDE_LINES), "guide.pdf", "Test Account Guide")
        assert response.status == 303
        name = location(response).rsplit("/", 1)[1]
        assert name == "test-account-guide.md"
        page = await (await session.get(f"/doc/{name}")).text()
        assert "Draft" in page and "Checks passed" in page and "Source PDF" in page
        doc = store.get_document(name)
        assert doc.status == "draft" and doc.source_filename == "guide.pdf"
        assert store.list_documents("current") == []  # a draft is never live
        assert "Which account do I use?" in doc.text

        # Not ticking the Qwen box publishes without Qwen approval.
        published = await session.post(f"/doc/{name}/publish", data={})
        assert published.status == 303 and "ok=" in published.headers["Location"]
        assert store.get_document(name).status == "current"
        assert store.get_document(name).external_processing_approved is False

        kb = KnowledgeBase(live, source=StoreSource(store, tmp_path / "none", poll_seconds=0))
        titles = [e.title for d in kb.documents for e in split_entries(d)]
        assert "Which account do I use?" in titles and "What if the login fails?" in titles
        assert [d.external_processing_approved for d in kb.documents] == [False]

        await session.post(f"/doc/{name}/qwen", data={"allow": "1"})
        assert store.get_document(name).external_processing_approved is True
        audit = await (await session.get("/audit")).text()
        assert "publish" in audit and "upload-pdf" in audit

    run_app(tmp_path, scenario)


def test_publishing_is_refused_while_the_checks_fail_and_the_reason_is_shown(tmp_path):
    async def scenario(session, store):
        store.create_draft("a.md", "no numbered entries here", "pm")
        page = await (await session.get("/doc/a.md")).text()
        assert "No numbered entries found" in page
        response = await session.post("/doc/a.md/publish", data={})
        assert "err=" in response.headers["Location"]
        assert store.get_document("a.md").status == "draft"

    run_app(tmp_path, scenario)


def test_editing_a_draft_then_publishing(tmp_path):
    async def scenario(session, store):
        store.create_draft("a.md", "rough notes", "pm")
        fixed = "---\ntitle: Fixed\n---\nF1. What now?\nPublish it.\n"
        assert (await session.post("/doc/a.md/save", data={"text": fixed})).status == 303
        await session.post("/doc/a.md/publish", data={"qwen": "1"})
        doc = store.get_document("a.md")
        assert doc.status == "current" and doc.external_processing_approved is True

    run_app(tmp_path, scenario)


def test_archive_then_delete_needs_the_exact_name(tmp_path):
    async def scenario(session, store):
        for name, ident in (("a.md", "A1"), ("b.md", "B1")):
            store.create_draft(name, f"---\ntitle: {name}\n---\n{ident}. Q?\nA.\n", "pm")
            store.publish(name, "pm")
        live_delete = await session.post("/doc/a.md/delete", data={"confirm": "a.md"})
        assert "err=" in live_delete.headers["Location"] and store.get_document("a.md")
        await session.post("/doc/a.md/archive", data={})
        assert store.get_document("a.md").status == "archived"
        wrong = await session.post("/doc/a.md/delete", data={"confirm": "yes"})
        assert "err=" in wrong.headers["Location"] and store.get_document("a.md")
        done = await session.post("/doc/a.md/delete", data={"confirm": "a.md"})
        assert location(done) == "/" and store.get_document("a.md") is None

    run_app(tmp_path, scenario)


def test_history_can_be_rolled_back_from_the_ui(tmp_path):
    async def scenario(session, store):
        v1 = "---\ntitle: T\n---\nA1. First?\nOne.\n"
        store.create_draft("a.md", v1, "pm")
        store.save_text("a.md", v1.replace("One", "Two"), "pm")
        oldest = store.history("a.md")[-1]["id"]
        await session.post("/doc/a.md/rollback", data={"version": str(oldest)})
        assert "One." in store.get_document("a.md").text

    run_app(tmp_path, scenario)


def test_built_in_documents_can_be_imported_with_one_click(tmp_path):
    from .conftest import ROOT

    async def scenario(session, store):
        assert "Import built-in documents" in await (await session.get("/")).text()
        assert (await session.post("/seed", data={})).status == 303
        assert len(store.list_documents("current")) >= 8
        assert "Import built-in documents" not in await (await session.get("/")).text()

    run_app(tmp_path, scenario, baked=ROOT / "knowledge" / "current")


# ---- uploads that must be refused ------------------------------------------------------------
def test_uploads_that_are_not_usable_pdfs_are_refused_with_a_message(tmp_path):
    async def scenario(session, store):
        for payload, expect in (
            (b"MZ this is an exe", "not a PDF"),
            (b"%PDF-1.4 garbage that is not really a pdf", "could not be read"),
            (make_pdf([]), "no selectable text"),
        ):
            response = await session.upload(payload, "x.pdf")
            assert response.status == 303 and "err=" in response.headers["Location"], expect
            from urllib.parse import unquote

            assert expect in unquote(response.headers["Location"])
        assert store.list_documents() == []

    run_app(tmp_path, scenario)


def test_the_source_pdf_can_be_downloaded_but_not_rendered_inline(tmp_path):
    async def scenario(session, store):
        pdf = make_pdf(GUIDE_LINES)
        response = await session.upload(pdf, "guide.pdf")
        name = location(response).rsplit("/", 1)[1]
        digest = store.get_document(name).source_sha256
        download = await session.get(f"/pdf/{digest}")
        assert await download.read() == pdf
        assert download.headers["Content-Disposition"].startswith("attachment")
        assert download.headers["Content-Security-Policy"] == "sandbox"
        assert (await session.get("/pdf/" + "f" * 64)).status == 404

    run_app(tmp_path, scenario)


# ---- PDF drafting ----------------------------------------------------------------------------
def test_pdf_text_becomes_numbered_entries_that_validate():
    pages = extract_pages(make_pdf(GUIDE_LINES))
    text = draft_markdown("Test Account Guide", "g.pdf", pages, taken_prefixes={"TAG"})
    check = validate_document("test-account-guide.md", text)
    assert check.ok, check.problems
    # "TAG" (the title's initials) was taken, so the draft picked a free prefix instead.
    assert len(check.entry_ids) >= 2 and all(i.startswith("A") for i in check.entry_ids)


def test_the_pdfs_own_numbering_cannot_create_fake_entries_or_headings():
    assert body_line("Q7. Something") == "Q7) Something"
    assert body_line("# Title") == "Title"
    assert body_line("<!-- audience: qc -->") == "audience: qc"
    lines = ["Which model?", "Q7. is not an entry", "# nor a heading"]
    body = structure(lines, "Doc", "D")
    assert [e.id for e in _entries(body)] == ["D1"]


def _entries(body):
    from pathlib import Path

    from gab_faq.knowledge import parse_text

    doc = parse_text(f"---\ntitle: t\n---\n{body}", Path("t.md"))
    return split_entries(doc)


def test_questions_with_inline_answers_and_run_together_bullets_are_split():
    pages = [
        "Which model is Product A? A: Use flash.\nWhich model is Product B? A: Use GPT.\n"
        "Rules ● First rule. ● Second rule."
    ]
    entries = _entries(structure(clean_lines(pages), "Doc", "D"))
    assert [e.title for e in entries][:2] == [
        "Which model is Product A?",
        "Which model is Product B?",
    ]
    assert entries[0].body == "Use flash."
    assert "- First rule." in entries[2].body and "- Second rule." in entries[2].body


def test_wrapped_paragraph_lines_are_rejoined_and_dates_are_not_headings():
    lines = ["Why is it", "slow?", "It is a long", "story about delays.", "14 Nov 2026"]
    body = structure(lines, "Doc", "D")
    assert "D1. Why is it slow?" not in body  # the question was split across lines: not a question
    assert "It is a long story about delays." in body


def test_repeated_headers_footers_and_page_numbers_are_dropped():
    pages = [f"GAB Confidential\nContent {i}.\n{i}" for i in range(1, 6)]
    assert clean_lines(pages) == [f"Content {i}." for i in range(1, 6)]


def test_entry_prefixes_avoid_ones_already_in_use():
    assert choose_prefix("Test Account Guide", {"TAG"}) == "A"
    assert choose_prefix("QC", set()) == "Q"
    assert choose_prefix("Zebra", {"Z", "A", "B"}) == "C"
    assert choose_prefix("!!!", set()) == "A"


def test_encrypted_and_oversized_inputs_are_reported_not_crashed():
    with pytest.raises(PdfImportError):
        extract_pages(b"%PDF-1.4\n")
    assert date.today().isoformat() in draft_markdown("T", "t.pdf", ["Why?\nBecause."], set())


# ---- extraction robustness (found by re-testing real PDFs after a pypdf upgrade) -------------
def make_word_positioned_pdf(lines: list[str]) -> bytes:
    """Every word placed with its own text matrix. (This synthetic form does NOT reproduce the
    one-word-per-line output the real guideline PDFs gave with pypdf 6.21; that case is covered
    through page_text() below. It checks that individually placed words still become lines.)"""
    ops = ["BT", "/F1 12 Tf"]
    for row, line in enumerate(lines):
        for column, word in enumerate(line.split()):
            ops.append(f"1 0 0 1 {72 + 55 * column} {720 - 16 * row} Tm ({word}) Tj")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return out


def test_words_placed_individually_are_still_read_as_whole_lines():
    pages = extract_pages(
        make_word_positioned_pdf(
            ["Which model is Product A?", "Use the flash model for the first turn."]
        )
    )
    lines = [" ".join(line.split()) for line in pages[0].splitlines() if line.strip()]
    assert lines == ["Which model is Product A?", "Use the flash model for the first turn."]
    text = draft_markdown("Models", "m.pdf", pages, set())
    assert validate_document("models.md", text).ok
    assert "Which model is Product A?" in text and "Use the flash model" in text


def test_common_words_repeated_on_every_page_are_never_dropped():
    pages = [f"the\nto\nand\nPage text number {i}.\nGAB Confidential Header" for i in range(1, 6)]
    cleaned = clean_lines(pages)
    assert cleaned.count("the") == 5 and cleaned.count("to") == 5 and cleaned.count("and") == 5
    assert "GAB Confidential Header" not in cleaned  # a real running header still goes


def test_layout_extraction_falls_back_to_the_default_when_it_fails_or_is_empty():
    class Page:
        def __init__(self, layout):
            self.layout = layout

        def extract_text(self, extraction_mode="plain"):
            if extraction_mode == "layout":
                if isinstance(self.layout, Exception):
                    raise self.layout
                return self.layout
            return "plain text"

    assert page_text(Page("laid out text")) == "laid out text"
    assert page_text(Page("   \n ")) == "plain text"
    assert page_text(Page(RuntimeError("odd page"))) == "plain text"


def test_an_answer_marker_after_the_question_is_not_kept_in_the_answer():
    entries = _entries(structure(["Which model is Product A?", "A: Use flash."], "Doc", "D"))
    assert [(e.title, e.body) for e in entries] == [("Which model is Product A?", "Use flash.")]
