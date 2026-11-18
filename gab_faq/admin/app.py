"""The admin web app (aiohttp, no extra web dependency). One shared PM login (HTTP Basic), every
change is written to the audit log with that user name. Run it with `python -m gab_faq.admin`."""

from __future__ import annotations

import asyncio
import hmac
import html
import re
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

from aiohttp import web

from ..knowledge_store import (
    MAX_PDF_BYTES,
    NAME_RE,
    SqliteKnowledgeStore,
    StoreError,
    check_pdf,
    slugify,
    validate_document,
)
from .pdf_import import PdfImportError, draft_markdown, extract_pages

STORE = web.AppKey("store", SqliteKnowledgeStore)
CONFIG = web.AppKey("config", dict)

STATUS_LABEL = {"current": "Live", "draft": "Draft", "archived": "Archived"}
FAILED_LOGINS: dict[str, list[float]] = {}
MAX_FAILURES, FAILURE_WINDOW = 5, 60

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1b1f24;--muted:#5b6670;--line:#d9dee4;--accent:#1f5fbf;
--ok:#18794e;--warn:#9a6700;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#14171a;--card:#1d2226;--text:#e6e9ec;
--muted:#9aa5af;--line:#333c43;--accent:#7aa7f0;--ok:#4cc38a;--warn:#e0a82e;--bad:#f08a80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 system-ui,Segoe UI,sans-serif}
header{display:flex;gap:16px;align-items:center;padding:12px 24px;background:var(--card);
border-bottom:1px solid var(--line)}header a{color:var(--text);text-decoration:none}
header .brand{font-weight:600}header span{margin-left:auto;color:var(--muted);font-size:13px}
main{max-width:1000px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:22px;margin:8px 0 14px}h2{font-size:17px;margin:0 0 10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;
margin-bottom:16px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px 10px;
border-bottom:1px solid var(--line);vertical-align:top;font-size:14px}
th{color:var(--muted);font-weight:600}a{color:var(--accent)}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;
border:1px solid var(--line)}.badge.current{color:var(--ok);border-color:var(--ok)}
.badge.draft{color:var(--warn);border-color:var(--warn)}.badge.archived{color:var(--muted)}
textarea{width:100%;min-height:420px;font:13px/1.45 ui-monospace,Consolas,monospace;
background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:6px;padding:10px}
input[type=text],input[type=file]{padding:6px;border:1px solid var(--line);border-radius:6px;
background:var(--bg);color:var(--text);max-width:100%}
button{padding:7px 14px;border-radius:6px;border:1px solid var(--accent);background:var(--accent);
color:#fff;font:inherit;cursor:pointer}button.secondary{background:transparent;color:var(--accent)}
button.danger{background:transparent;color:var(--bad);border-color:var(--bad)}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.muted{color:var(--muted)}
.msg{padding:10px 14px;border-radius:6px;margin-bottom:14px;border:1px solid var(--line)}
.msg.ok{border-color:var(--ok);color:var(--ok)}.msg.err{border-color:var(--bad);color:var(--bad)}
ul.problems li{color:var(--bad)}ul.warnings li{color:var(--warn)}
.note{font-size:13px;color:var(--muted)}label.check{display:flex;gap:8px;align-items:flex-start}
"""


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def render(request: web.Request, title: str, body: str, status: int = 200) -> web.Response:
    ok, err = request.query.get("ok", ""), request.query.get("err", "")
    flash = (f'<div class="msg ok">{esc(ok)}</div>' if ok else "") + (
        f'<div class="msg err">{esc(err)}</div>' if err else ""
    )
    user = request.get("user", "")
    page = (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{esc(title)} - GAB knowledge</title><style>{CSS}</style></head><body>"
        '<header><a class=brand href="/">GAB knowledge</a><a href="/">Documents</a>'
        f'<a href="/audit">Activity</a><span>Signed in as {esc(user)}</span></header>'
        f"<main>{flash}{body}</main></body></html>"
    )
    return web.Response(text=page, content_type="text/html", status=status)


def back(location: str, ok: str = "", err: str = "") -> web.HTTPSeeOther:
    query = f"?ok={quote(ok)}" if ok else (f"?err={quote(err)}" if err else "")
    return web.HTTPSeeOther(location + query)


@web.middleware
async def security(request: web.Request, handler):
    client = request.remote or "?"
    recent = [t for t in FAILED_LOGINS.get(client, []) if time.monotonic() - t < FAILURE_WINDOW]
    FAILED_LOGINS[client] = recent
    if len(recent) >= MAX_FAILURES:
        return web.Response(status=429, text="Too many failed sign-ins. Wait a minute.")
    user = _authenticate(request)
    if user is None:
        # A request with no credentials is the browser's normal first visit (it is answered with
        # the sign-in prompt); only credentials that were presented and are wrong count.
        if request.headers.get("Authorization"):
            recent.append(time.monotonic())
        return web.Response(
            status=401, text="Sign in required", headers={"WWW-Authenticate": 'Basic realm="GAB"'}
        )
    request["user"] = user
    if request.method not in ("GET", "HEAD"):
        origin = request.headers.get("Origin", "")
        if not origin or urlsplit(origin).netloc != request.host:
            return web.Response(status=403, text="Cross-site request refused.")
    try:
        response = await handler(request)
    except web.HTTPException as error:
        response = error
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if not response.headers.get("Content-Security-Policy"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
    if isinstance(response, web.HTTPException):
        raise response
    return response


def _authenticate(request: web.Request) -> str | None:
    import base64
    import binascii

    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return None
    try:
        user, _, password = base64.b64decode(header[6:], validate=True).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return None
    config = request.app[CONFIG]
    good_user = hmac.compare_digest(user.encode(), config["user"].encode())
    good_password = hmac.compare_digest(password.encode(), config["password"].encode())
    return user if good_user and good_password else None


def store_of(request: web.Request) -> SqliteKnowledgeStore:
    return request.app[STORE]


def doc_name(request: web.Request) -> str:
    name = request.match_info["name"]
    if not NAME_RE.match(name):
        raise web.HTTPNotFound()
    return name


def short_time(stamp: str) -> str:
    return stamp.replace("T", " ").replace("Z", " UTC")


# ---- pages -----------------------------------------------------------------------------------
async def index(request: web.Request) -> web.Response:
    store = store_of(request)
    docs = store.list_documents()
    rows = []
    for doc in docs:
        check = validate_document(doc.name, doc.text)  # entry count only; see doc_page for clashes
        rows.append(
            f'<tr><td><a href="/doc/{esc(doc.name)}">{esc(doc.title)}</a>'
            f'<div class="note">{esc(doc.name)}</div></td>'
            f'<td><span class="badge {esc(doc.status)}">{STATUS_LABEL[doc.status]}</span></td>'
            f"<td>{len(check.entry_ids)}</td>"
            f"<td>{'Yes' if doc.external_processing_approved else 'No'}</td>"
            f"<td>{esc(short_time(doc.updated_at))}<div class=note>{esc(doc.updated_by)}</div></td>"
            "</tr>"
        )
    table = (
        "<table><tr><th>Document</th><th>Status</th><th>Entries</th><th>Qwen allowed</th>"
        f"<th>Last change</th></tr>{''.join(rows)}</table>"
        if rows
        else '<p class="muted">No documents yet.</p>'
    )
    baked = request.app[CONFIG].get("baked_dir")
    seed = ""
    if not docs and baked and any(Path(baked).glob("*.md")):
        count = len(list(Path(baked).glob("*.md")))
        seed = (
            '<div class="card"><h2>Start from the built-in documents</h2>'
            f"<p>The bot currently answers from {count} documents built into its image. Import "
            "them here so you can manage them. Nothing changes for freelancers.</p>"
            '<form method=post action="/seed"><button>Import built-in documents</button></form>'
            "</div>"
        )
    body = (
        "<h1>Documents</h1>"
        f"{seed}"
        '<div class="card"><h2>Upload a PDF</h2>'
        '<p class="note">The text is extracted on this server and drafted into numbered FAQ '
        "entries. The draft is <b>not</b> live: you review and edit it, then publish.</p>"
        '<form method=post action="/upload" enctype="multipart/form-data" class="row">'
        '<input type=file name=file accept="application/pdf,.pdf" required>'
        '<input type=text name=title placeholder="Title (optional)" size=30>'
        "<button>Upload and draft</button></form></div>"
        f'<div class="card">{table}</div>'
        '<p class="note">Live documents are what the bot answers from. It picks up a change on '
        "its next question.</p>"
    )
    return render(request, "Documents", body)


async def doc_page(request: web.Request) -> web.Response:
    store, name = store_of(request), doc_name(request)
    doc = store.get_document(name)
    if not doc:
        raise web.HTTPNotFound()
    check = store.validate(name, doc.text)
    problems = "".join(f"<li>{esc(p)}</li>" for p in check.problems)
    warnings = "".join(f"<li>{esc(w)}</li>" for w in check.warnings)
    status = (
        f'<span class="badge {esc(doc.status)}">{STATUS_LABEL[doc.status]}</span> '
        f'<span class="muted">{len(check.entry_ids)} entries'
        f" · Qwen allowed: {'yes' if doc.external_processing_approved else 'no'}"
        f" · changed {esc(short_time(doc.updated_at))} by {esc(doc.updated_by)}</span>"
    )
    pdf = (
        f' · <a href="/pdf/{esc(doc.source_sha256)}">Source PDF ({esc(doc.source_filename)})</a>'
        if doc.source_sha256
        else ""
    )
    messages = ""
    if problems:
        messages += f'<ul class="problems">{problems}</ul>'
    if warnings:
        messages += f'<ul class="warnings">{warnings}</ul>'
    if not messages:
        messages = '<p class="muted">Checks passed.</p>'
    qwen_note = (
        "Allow this document to be sent to Qwen (Alibaba Cloud, Singapore) to compose answers. "
        "Leave unticked and a question that matches this document is handed to staff instead "
        "of answered."
    )
    actions = []
    if doc.status in ("draft", "archived"):
        actions.append(
            f'<form method=post action="/doc/{esc(name)}/publish" class="card">'
            f"<h2>{'Publish' if doc.status == 'draft' else 'Restore'}</h2>"
            f"<label class=check><input type=checkbox name=qwen value=1 "
            f"{'checked' if doc.external_processing_approved else ''}>"
            f"<span>{esc(qwen_note)}</span></label><p><button>"
            f"{'Publish to the bot' if doc.status == 'draft' else 'Restore to the bot'}"
            "</button></p></form>"
        )
    if doc.status == "current":
        flip = "0" if doc.external_processing_approved else "1"
        actions.append(
            '<div class="card"><h2>Live document</h2><div class=row>'
            f'<form method=post action="/doc/{esc(name)}/qwen">'
            f'<input type=hidden name=allow value="{flip}"><button class=secondary>'
            f"{'Stop' if flip == '0' else 'Start'} allowing Qwen</button></form>"
            f'<form method=post action="/doc/{esc(name)}/archive">'
            "<button class=secondary>Archive (take offline)</button></form></div></div>"
        )
    if doc.status != "current":
        actions.append(
            f'<form method=post action="/doc/{esc(name)}/delete" class="card">'
            "<h2>Delete permanently</h2>"
            f'<p class="note">Type <b>{esc(name)}</b> to confirm. Saved versions and the activity '
            "log are kept.</p>"
            "<div class=row><input type=text name=confirm autocomplete=off>"
            "<button class=danger>Delete</button></div></form>"
        )
    versions = store.history(name)
    version_rows = "".join(
        f"<tr><td>{esc(short_time(v['at']))}</td><td>{esc(v['by'])}</td><td>{esc(v['note'])}</td>"
        f"<td>{v['size']:,} chars</td><td>"
        f'<form method=post action="/doc/{esc(name)}/rollback">'
        f'<input type=hidden name=version value="{int(v["id"])}">'
        "<button class=secondary>Use this version</button></form></td></tr>"
        for v in versions
    )
    body = (
        f"<h1>{esc(doc.title)}</h1><p>{status}{pdf}</p>"
        f'<div class="card"><h2>Checks</h2>{messages}</div>'
        f'<form method=post action="/doc/{esc(name)}/save" class="card"><h2>Text</h2>'
        '<p class="note">Entries start on their own line like <code>A1. Question?</code> '
        "followed by the answer. Edit freely; nothing is live until it is published."
        f"{' Saving a live document updates the bot.' if doc.status == 'current' else ''}</p>"
        f"<textarea name=text spellcheck=false>{esc(doc.text)}</textarea>"
        "<p><button>Save</button></p></form>"
        f"{''.join(actions)}"
        f'<div class="card"><h2>History</h2><table><tr><th>When</th><th>Who</th><th>Change</th>'
        f"<th>Size</th><th></th></tr>{version_rows}</table></div>"
    )
    return render(request, doc.title, body)


async def audit_page(request: web.Request) -> web.Response:
    rows = "".join(
        f"<tr><td>{esc(short_time(r['at']))}</td><td>{esc(r['actor'])}</td>"
        f"<td>{esc(r['action'])}</td><td>{esc(r['target'])}</td><td>{esc(r['detail'])}</td></tr>"
        for r in store_of(request).audit_log(200)
    )
    return render(
        request,
        "Activity",
        "<h1>Activity</h1><div class=card><table><tr><th>When</th><th>Who</th><th>What</th>"
        f"<th>Document</th><th>Detail</th></tr>{rows}</table></div>",
    )


async def pdf_download(request: web.Request) -> web.Response:
    digest = request.match_info["sha"]
    found = store_of(request).get_pdf(digest) if re.fullmatch(r"[0-9a-f]{64}", digest) else None
    if not found:
        raise web.HTTPNotFound()
    filename, data = found
    safe = slugify(filename, "source")[:-3] + ".pdf"
    return web.Response(
        body=data,
        content_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe}"',
            "Content-Security-Policy": "sandbox",
        },
    )


# ---- actions ---------------------------------------------------------------------------------
async def upload(request: web.Request) -> web.Response:
    form = await request.post()
    file = form.get("file")
    if not isinstance(file, web.FileField):
        raise back("/", err="Choose a PDF file first.")
    data = file.file.read(MAX_PDF_BYTES + 1)
    actor, store = request["user"], store_of(request)
    try:
        check_pdf(data)
        pages = await asyncio.get_running_loop().run_in_executor(None, extract_pages, data)
        digest = store.put_pdf(data, file.filename or "document.pdf", actor)
        title = str(form.get("title") or "").strip() or Path(file.filename or "document").stem
        name = store.unique_name(slugify(title))
        text = draft_markdown(title[:120], file.filename or "document.pdf", pages, store.prefixes())
        store.create_draft(
            name, text, actor, source_sha256=digest, source_filename=file.filename or ""
        )
    except (PdfImportError, StoreError) as error:
        raise back("/", err=str(error)) from error
    raise back(f"/doc/{name}", ok="Draft created. Review it, then publish.")


async def seed(request: web.Request) -> web.Response:
    baked = request.app[CONFIG].get("baked_dir")
    if not baked:
        raise back("/", err="No built-in documents are configured.")
    imported = store_of(request).import_directory(Path(baked), request["user"])
    raise back("/", ok=f"Imported {len(imported)} documents.")


def guarded(action):
    async def handler(request: web.Request) -> web.Response:
        store, name = store_of(request), doc_name(request)
        try:
            message = await action(request, store, name, await request.post())
        except StoreError as error:
            raise back(f"/doc/{name}", err=str(error)) from error
        raise back(message[0], ok=message[1])

    return handler


async def do_save(request, store, name, form):
    store.save_text(name, str(form.get("text", "")).replace("\r\n", "\n"), request["user"])
    return f"/doc/{name}", "Saved."


async def do_publish(request, store, name, form):
    was = store.get_document(name)
    store.publish(name, request["user"], external_processing_approved=form.get("qwen") == "1")
    verb = "Restored" if was and was.status == "archived" else "Published"
    return f"/doc/{name}", f"{verb}. The bot uses it from its next question."


async def do_qwen(request, store, name, form):
    allow = form.get("allow") == "1"
    store.set_external_approval(name, allow, request["user"])
    return f"/doc/{name}", "Qwen is now allowed." if allow else "Qwen is no longer allowed."


async def do_archive(request, store, name, form):
    store.archive(name, request["user"])
    return f"/doc/{name}", "Archived. The bot no longer answers from it."


async def do_delete(request, store, name, form):
    if form.get("confirm") != name:
        raise StoreError("Type the file name exactly to confirm the deletion.")
    store.delete(name, request["user"])
    return "/", f"Deleted {name}."


async def do_rollback(request, store, name, form):
    try:
        version = int(form.get("version", ""))
    except ValueError as error:
        raise StoreError("Choose a version.") from error
    store.rollback(name, version, request["user"])
    return f"/doc/{name}", "Restored that version."


def create_app(
    store: SqliteKnowledgeStore, user: str, password: str, baked_dir: Path | None = None
) -> web.Application:
    app = web.Application(middlewares=[security], client_max_size=MAX_PDF_BYTES + 2_000_000)
    app[STORE] = store
    app[CONFIG] = {"user": user, "password": password, "baked_dir": baked_dir}
    app.add_routes(
        [
            web.get("/", index),
            web.get("/audit", audit_page),
            web.get("/doc/{name}", doc_page),
            web.get("/pdf/{sha}", pdf_download),
            web.post("/upload", upload),
            web.post("/seed", seed),
            web.post("/doc/{name}/save", guarded(do_save)),
            web.post("/doc/{name}/publish", guarded(do_publish)),
            web.post("/doc/{name}/qwen", guarded(do_qwen)),
            web.post("/doc/{name}/archive", guarded(do_archive)),
            web.post("/doc/{name}/delete", guarded(do_delete)),
            web.post("/doc/{name}/rollback", guarded(do_rollback)),
        ]
    )
    return app
