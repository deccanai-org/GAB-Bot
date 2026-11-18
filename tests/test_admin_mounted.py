"""The admin web app mounted under a path prefix behind HTTPS, and the separate, secret-free
process that reads uploaded PDFs (used by the Discord upload channel and the web app alike)."""

import asyncio
import base64
import re
import sys
import time
from types import SimpleNamespace

import pytest
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer

pytest.importorskip("pypdf")

from gab_faq.admin import app as admin_app  # noqa: E402
from gab_faq.admin.app import MAX_REQUEST_BYTES, is_secure  # noqa: E402
from gab_faq.admin.pdf_import import (  # noqa: E402
    PdfImportError,
    extract_pages,
    extract_pages_isolated,
)
from gab_faq.knowledge_store import SqliteKnowledgeStore  # noqa: E402

from .test_admin import GUIDE_LINES, make_pdf  # noqa: E402

PASSWORD = "correct horse battery"
AUTH = {"Authorization": "Basic " + base64.b64encode(f"pm:{PASSWORD}".encode()).decode()}


@pytest.fixture(autouse=True)
def fresh_limiter():
    admin_app.FAILED_LOGINS.clear()


def big_pdf(extra_bytes: int) -> bytes:
    """A valid one-page PDF made big by a comment after the header (offsets computed after it)."""
    stream = (
        b"BT /F1 12 Tf 72 720 Td 16 TL "
        + b" ".join(b"(" + line.encode("latin-1") + b") Tj T*" for line in GUIDE_LINES)
        + b" ET"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n% " + b"x" * extra_bytes + b"\n"
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


def served(tmp_path, store=None, limit=MAX_REQUEST_BYTES):
    """The admin app mounted at /admin on a plain root application (what a reverse proxy or a
    host application would do), next to an unrelated open /health route."""
    store = store or SqliteKnowledgeStore(tmp_path / "k.sqlite3")
    sub = admin_app.create_app(store, "pm", PASSWORD, prefix="/admin", require_https=True)
    root = web.Application(client_max_size=limit) if limit else web.Application()

    async def live(request):
        return web.json_response({"alive": True})

    root.router.add_get("/health/live", live)
    root.router.add_get("/health/ready", live)
    root.add_subapp("/admin", sub)
    return TestServer(root), store


def run(coroutine):
    return asyncio.run(coroutine)


def authed(client, path, **kwargs):
    return client.get(path, headers=AUTH, allow_redirects=False, **kwargs)


def upload(client, pdf, title="Test Account Guide"):
    form = FormData()
    form.add_field("file", pdf, filename="guide.pdf", content_type="application/pdf")
    form.add_field("title", title)
    origin = f"http://{client.server.host}:{client.server.port}"
    return client.post(
        "/admin/upload", data=form, headers={**AUTH, "Origin": origin}, allow_redirects=False
    )


# ---- switching it on -------------------------------------------------------------------------
# ---- served by the bot's web server ----------------------------------------------------------
def test_an_open_route_stays_open_and_the_mounted_app_sits_behind_a_login(tmp_path):
    async def scenario():
        server, _ = served(tmp_path)
        async with TestClient(server) as client:
            for path in ("/health/live", "/health/ready"):
                assert (await client.get(path)).status == 200  # as before: no login
            assert (await client.get("/admin/")).status == 401
            assert (await authed(client, "/admin/")).status == 200
            for path in ("/", "/doc/x.md", "/upload", "/audit"):  # nothing at the root
                assert (await authed(client, path)).status == 404

    run(scenario())


def test_every_link_and_form_in_the_tab_stays_under_admin(tmp_path):
    async def scenario():
        server, store = served(tmp_path)
        store.create_draft("a.md", "---\ntitle: A\n---\nA1. Q?\nAnswer.\n", "pm")
        async with TestClient(server) as client:
            for path in ("/admin/", "/admin/upload", "/admin/doc/a.md", "/admin/audit"):
                page = await (await authed(client, path)).text()
                targets = re.findall(r'(?:href|action)="([^"]+)"', page)
                assert targets, path
                assert all(t.startswith("/admin") for t in targets), (path, targets)

    run(scenario())


def test_the_upload_tab_exists_and_is_in_the_navigation(tmp_path):
    async def scenario():
        server, _ = served(tmp_path)
        async with TestClient(server) as client:
            page = await (await authed(client, "/admin/upload")).text()
            assert 'action="/admin/upload"' in page and "enctype=" in page
            assert '<a href="/admin/upload" class=active>Upload</a>' in page
            assert "not live" in page  # says a draft is not used until published
            home = await (await authed(client, "/admin/")).text()
            assert 'href="/admin/upload"' in home

    run(scenario())


def test_a_pdf_bigger_than_aiohttps_default_limit_is_accepted_and_huge_ones_refused(tmp_path):
    async def scenario():
        server, store = served(tmp_path)
        async with TestClient(server) as client:
            response = await upload(client, big_pdf(2_000_000))  # > the default 1 MB
            assert response.status == 303, await response.text()
            assert response.headers["Location"].startswith("/admin/doc/")
            assert store.list_documents()[0].status == "draft"
            too_big = await upload(client, b"%PDF-1.4\n" + b"0" * (MAX_REQUEST_BYTES + 1000))
            assert too_big.status == 413

    run(scenario())


def test_without_the_larger_limit_the_server_would_refuse_normal_pdfs(tmp_path):
    """Why serve() passes client_max_size: aiohttp ignores a mounted app's own limit."""

    async def scenario():
        server, _ = served(tmp_path, limit=None)
        async with TestClient(server) as client:
            assert (await upload(client, big_pdf(2_000_000))).status == 413

    run(scenario())


def test_the_whole_workflow_works_under_the_prefix(tmp_path):
    async def scenario():
        server, store = served(tmp_path)
        async with TestClient(server) as client:
            created = await upload(client, make_pdf(GUIDE_LINES))
            draft = created.headers["Location"].split("?")[0]
            assert draft == "/admin/doc/test-account-guide.md"
            origin = f"http://{server.host}:{server.port}"
            headers = {**AUTH, "Origin": origin}
            done = await client.post(
                draft + "/publish", data={}, headers=headers, allow_redirects=False
            )
            assert done.status == 303 and done.headers["Location"].startswith(draft)
            assert [d.name for d in store.list_documents("current")] == ["test-account-guide.md"]
            bad = await client.post(
                "/admin/upload", data=b"nothing", headers=headers, allow_redirects=False
            )
            assert bad.status == 303 and bad.headers["Location"].startswith("/admin/upload?err=")

    run(scenario())


# ---- HTTPS only ------------------------------------------------------------------------------
def request(proto=None, scheme="http", remote="10.0.0.5"):
    headers = {"X-Forwarded-Proto": proto} if proto else {}
    return SimpleNamespace(headers=headers, scheme=scheme, remote=remote)


def test_https_is_required_except_through_a_loopback_port_forward():
    assert is_secure(request(proto="https"))
    assert is_secure(request(proto="https, http"))  # first hop wins
    assert is_secure(request(scheme="https"))
    assert is_secure(request(remote="127.0.0.1")) and is_secure(request(remote="::1"))
    assert not is_secure(request())
    assert not is_secure(request(proto="http"))
    assert not is_secure(request(remote="10.0.0.5", proto="ftp"))


def test_plain_http_from_another_machine_is_refused_before_the_password_is_checked(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(admin_app, "LOOPBACK", set())  # as if the client were not local

    async def scenario():
        server, _ = served(tmp_path)
        async with TestClient(server) as client:
            plain = await authed(client, "/admin/")
            assert plain.status == 403 and "HTTPS is required" in await plain.text()
            proxied = await client.get(
                "/admin/", headers={**AUTH, "X-Forwarded-Proto": "https"}, allow_redirects=False
            )
            assert proxied.status == 200
            assert (await client.get("/health/live")).status == 200  # probes are not affected

    run(scenario())


# ---- the bot must not be affected ------------------------------------------------------------
class SlowStore:
    """A database call that takes 1.5 s, blocking the calling thread like a real one."""

    def __init__(self, inner):
        self.inner = inner

    def list_documents(self, *args, **kwargs):
        time.sleep(1.5)
        return self.inner.list_documents(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_a_slow_database_call_does_not_stall_the_event_loop(tmp_path):
    async def scenario():
        inner = SqliteKnowledgeStore(tmp_path / "k.sqlite3")
        server, _ = served(tmp_path, store=SlowStore(inner))
        gaps: list[float] = []

        async def heartbeat():
            """Stands in for the Discord gateway: it must get the event loop every ~50 ms."""
            last = time.monotonic()
            while True:
                await asyncio.sleep(0.05)
                now = time.monotonic()
                gaps.append(now - last)
                last = now

        async with TestClient(server) as client:
            beat = asyncio.create_task(heartbeat())
            slow = asyncio.create_task(authed(client, "/admin/"))
            await asyncio.sleep(0.3)  # the admin request is now inside the 1.5 s database call
            assert (await client.get("/health/live")).status == 200
            assert (await slow).status == 200
            beat.cancel()
            assert max(gaps) < 0.6, f"the event loop was blocked for {max(gaps):.2f}s"

    run(scenario())


def test_a_failing_database_gives_a_plain_503_and_leaves_other_routes_alone(tmp_path):
    class Broken:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise ConnectionError("password authentication failed for user gab_admin")

            return fail

    async def scenario():
        server, _ = served(tmp_path, store=Broken())
        async with TestClient(server) as client:
            page = await authed(client, "/admin/")
            text = await page.text()
            assert page.status == 503 and "keeps answering" in text
            assert "password authentication" not in text and "Traceback" not in text
            assert (await client.get("/health/ready")).status == 200

    run(scenario())


# ---- reading PDFs in a separate, secret-free process -----------------------------------------
def worker(tmp_path, body):
    path = tmp_path / "worker.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_the_separate_reader_returns_exactly_what_an_in_process_read_would():
    pdf = make_pdf(GUIDE_LINES)
    assert extract_pages_isolated(pdf) == extract_pages(pdf)


def test_the_reader_process_gets_none_of_the_bots_secrets(tmp_path, monkeypatch):
    for name in (
        "DISCORD_TOKEN",
        "DASHSCOPE_API_KEY",
        "GAB_ADMIN_PASSWORD",
        "GAB_KNOWLEDGE_DB",
        "GAB_KNOWLEDGE_ADMIN_DB",
        "PGPASSWORD",
        "AWS_SECRET_ACCESS_KEY",
    ):
        monkeypatch.setenv(name, "must-not-reach-the-reader")
    script = worker(
        tmp_path,
        "import json, os, sys\n"
        "sys.stdin.buffer.read()\n"
        "sys.stdout.write(json.dumps({'pages': [json.dumps(sorted(os.environ))]}))\n",
    )
    seen = extract_pages_isolated(b"%PDF-1.4", worker=script)[0]
    assert "PATH" in seen or "Path" in seen  # it does get what Python needs to start
    for name in ("DISCORD_TOKEN", "DASHSCOPE", "PASSWORD", "KNOWLEDGE", "PGPASSWORD", "AWS_"):
        assert name not in seen, name


def test_a_reader_that_hangs_is_stopped(tmp_path):
    script = worker(tmp_path, "import time\ntime.sleep(60)\n")
    started = time.monotonic()
    with pytest.raises(PdfImportError, match="took too long"):
        extract_pages_isolated(b"%PDF-1.4", timeout=1, worker=script)
    assert time.monotonic() - started < 15


@pytest.mark.parametrize(
    "body,message",
    [
        ("import sys\nsys.exit(3)\n", "stopped unexpectedly"),
        ("print('this is not json')\n", "unreadable"),
        ("print('[1, 2]')\n", "unexpected"),
        ("print('{\"pages\": [1, 2]}')\n", "unexpected"),
        ('print(\'{"error": "The PDF is password protected."}\')\n', "password protected"),
    ],
)
def test_a_reader_that_fails_or_misbehaves_gives_a_clear_error(tmp_path, body, message):
    with pytest.raises(PdfImportError, match=message):
        extract_pages_isolated(b"%PDF-1.4", worker=worker(tmp_path, body))


def test_a_missing_reader_is_reported_not_raised_as_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "no-such-python"))
    with pytest.raises(PdfImportError, match="could not be started"):
        extract_pages_isolated(make_pdf(GUIDE_LINES))
