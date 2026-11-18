"""The knowledge database: FAQ documents the GAB PM manages in the admin UI (gab_faq.admin).

Two sides use it:

  * The admin UI writes drafts, publishes, archives, deletes and rolls back (SqliteKnowledgeStore).
  * The bot only reads it. StoreSource copies the published documents into a local folder and the
    existing KnowledgeBase reads that folder exactly as before (same parsing, approval policy,
    secret scan and search index). So a database problem can never make the bot worse than "keeps
    answering from the last good files, or from the documents built into the image".

Only documents whose status is "current" are served. A draft or an archived document never is.
Nothing is ever sent to Qwen unless the PM ticked that document's external-processing approval.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .knowledge import FaqDocument, parse_text
from .redact import contains_secret
from .search import DIRECTIVE_RE, ENTRY_RE, HEADING_RE, split_entries
from .storage import atomic_write

log = logging.getLogger(__name__)

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\.md$")
STATUSES = ("draft", "current", "archived")
SUPPORT_FILES = ("entry-policy.yaml", "playground-videos.yaml")
MAX_TEXT_BYTES = 1_000_000
MAX_PDF_BYTES = 25 * 1024 * 1024


class StoreError(ValueError):
    """A change the store refuses (invalid document, wrong status, unknown name)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_pdf(data: bytes) -> None:
    """Refuse anything that is not a PDF of acceptable size before it is read or stored."""
    if len(data) > MAX_PDF_BYTES:
        raise StoreError("The PDF is larger than 25 MB.")
    if not data.startswith(b"%PDF-"):
        raise StoreError("That file is not a PDF.")


def slugify(text: str, fallback: str = "document") -> str:
    """A safe document file name ("My FAQ v2.pdf" -> "my-faq-v2.md")."""
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", text.strip())
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:58].strip("-")
    return f"{slug or fallback}.md"


@dataclass(frozen=True)
class Validation:
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    entry_ids: tuple[str, ...] = ()
    title: str = ""
    audience: str = ""

    @property
    def ok(self) -> bool:
        return not self.problems


def validate_document(
    name: str, text: str, other_entry_ids: dict[str, set[str]] | None = None
) -> Validation:
    """Everything that must be true before the bot may serve this text. `other_entry_ids` maps the
    other published documents to their entry IDs: IDs are global (entry-policy, videos and
    follow-ups refer to them), so two documents may not reuse one."""
    problems: list[str] = []
    warnings: list[str] = []
    if not NAME_RE.match(name):
        problems.append("The file name must be lowercase letters, digits and dashes, ending .md.")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        problems.append("The document is larger than 1 MB.")
    if problems:
        return Validation(tuple(problems))
    if text.startswith("---") and text.count("---") < 2:
        return Validation(("The header at the top is not closed: add a second --- line.",))
    try:
        doc = parse_text(text, Path(name))
    except ValueError as error:
        return Validation((str(error),))
    except Exception:  # a malformed header must be a message, never a crash
        return Validation(("The header between the --- lines could not be read.",))
    if not doc.approved:
        problems.append(
            "The header marks this file as archived/superseded/draft or approved: false, so the "
            "bot would ignore it. Remove that line (use Archive in the UI instead)."
        )
    if contains_secret(doc.body):
        problems.append(
            "The text contains what looks like a password, token or API key. Remove it first."
        )
    try:
        entries = split_entries(replace(doc, approved=True))
    except ValueError as error:
        return Validation(tuple(problems) + (str(error),))
    ids = [e.id for e in entries]
    if not entries:
        problems.append(
            "No numbered entries found. The bot answers from entries that start like "
            "'A1. How do I ...?' on their own line."
        )
    for ident in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"Entry ID {ident} appears more than once in this document.")
    for other, other_ids in sorted((other_entry_ids or {}).items()):
        clash = sorted(set(ids) & other_ids)
        if clash:
            problems.append(f"Entry ID(s) {', '.join(clash)} are already used in {other}.")
    outside = _lines_outside_entries(doc)
    if outside:
        warnings.append(
            f"{outside} line(s) sit outside a numbered entry. The bot ignores them: move them "
            "into an entry or delete them."
        )
    if not doc.updated:
        warnings.append("The header has no 'updated:' date.")
    return Validation(tuple(problems), tuple(warnings), tuple(ids), doc.title, doc.audience)


def _lines_outside_entries(doc: FaqDocument) -> int:
    seen_entry = False
    outside = 0
    for line in doc.body.splitlines():
        stripped = line.strip()
        if HEADING_RE.match(line):
            seen_entry = False
        elif ENTRY_RE.match(line):
            seen_entry = True
        elif stripped and not DIRECTIVE_RE.match(stripped) and not seen_entry:
            outside += 1
    return outside


@dataclass(frozen=True)
class StoredDocument:
    name: str
    status: str
    text: str
    external_processing_approved: bool
    source_sha256: str
    source_filename: str
    updated_at: str
    updated_by: str

    @property
    def title(self) -> str:
        try:
            return parse_text(self.text, Path(self.name)).title
        except Exception:
            return self.name


_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
    name TEXT PRIMARY KEY, status TEXT NOT NULL, text TEXT NOT NULL,
    external_processing_approved INTEGER NOT NULL DEFAULT 0,
    source_sha256 TEXT NOT NULL DEFAULT '', source_filename TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS versions(
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, status TEXT NOT NULL,
    text TEXT NOT NULL, external_processing_approved INTEGER NOT NULL,
    at TEXT NOT NULL, by TEXT NOT NULL, note TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS versions_name ON versions(name, id);
CREATE TABLE IF NOT EXISTS pdfs(
    sha256 TEXT PRIMARY KEY, filename TEXT NOT NULL, size INTEGER NOT NULL, data BLOB NOT NULL,
    uploaded_at TEXT NOT NULL, uploaded_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS support(
    name TEXT PRIMARY KEY, text TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL,
    action TEXT NOT NULL, target TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_DOC_COLUMNS = (
    "name, status, text, external_processing_approved, source_sha256, source_filename, "
    "updated_at, updated_by"
)


class SqliteKnowledgeStore:
    """SQLite implementation. A production database (Postgres, MongoDB) needs only this same set
    of methods. `readonly=True` is what the bot uses: it can never change a document."""

    def __init__(self, path: Path, readonly: bool = False):
        self.path = Path(path)
        self.readonly = readonly
        self._lock = threading.RLock()
        if readonly:
            self._db = sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro",
                uri=True,
                check_same_thread=False,
                timeout=5,
            )
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
            self._db.executescript(_SCHEMA)
            self._db.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('revision', '0')")
            self._db.commit()
        self._db.row_factory = sqlite3.Row

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---- reading -------------------------------------------------------------------------------
    def revision(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()
            return int(row["value"]) if row else 0

    def _doc(self, row) -> StoredDocument:
        return StoredDocument(
            row["name"],
            row["status"],
            row["text"],
            bool(row["external_processing_approved"]),
            row["source_sha256"],
            row["source_filename"],
            row["updated_at"],
            row["updated_by"],
        )

    def list_documents(self, status: str | None = None) -> list[StoredDocument]:
        with self._lock:
            sql = f"SELECT {_DOC_COLUMNS} FROM documents"
            args: tuple = ()
            if status:
                sql += " WHERE status=?"
                args = (status,)
            return [self._doc(r) for r in self._db.execute(sql + " ORDER BY name", args)]

    def get_document(self, name: str) -> StoredDocument | None:
        with self._lock:
            row = self._db.execute(
                f"SELECT {_DOC_COLUMNS} FROM documents WHERE name=?", (name,)
            ).fetchone()
            return self._doc(row) if row else None

    def history(self, name: str, limit: int = 30) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, status, external_processing_approved, at, by, note, length(text) "
                "AS size FROM versions WHERE name=? ORDER BY id DESC LIMIT ?",
                (name, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def audit_log(self, limit: int = 100, target: str | None = None) -> list[dict]:
        with self._lock:
            sql, args = "SELECT at, actor, action, target, detail FROM audit", ()
            if target:
                sql, args = sql + " WHERE target=?", (target,)
            rows = self._db.execute(sql + " ORDER BY id DESC LIMIT ?", args + (limit,))
            return [dict(r) for r in rows.fetchall()]

    def counts(self) -> dict[str, int]:
        with self._lock:
            found = dict(self._db.execute("SELECT status, COUNT(*) FROM documents GROUP BY status"))
        return {status: found.get(status, 0) for status in STATUSES}

    def get_support(self, name: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT text FROM support WHERE name=?", (name,)).fetchone()
            return row["text"] if row else None

    def get_pdf(self, sha256: str) -> tuple[str, bytes] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT filename, data FROM pdfs WHERE sha256=?", (sha256,)
            ).fetchone()
            return (row["filename"], bytes(row["data"])) if row else None

    def entry_ids_of_current(self, except_name: str | None = None) -> dict[str, set[str]]:
        """Entry IDs of every published document (for the cross-document uniqueness check)."""
        result: dict[str, set[str]] = {}
        for doc in self.list_documents("current"):
            if doc.name == except_name:
                continue
            try:
                parsed = parse_text(doc.text, Path(doc.name))
                result[doc.name] = {e.id for e in split_entries(replace(parsed, approved=True))}
            except Exception:
                continue
        return result

    def prefixes(self) -> set[str]:
        """Entry-ID letter prefixes in use by any document (drafts and archived ones too), so a
        new draft can pick one that will not clash when published."""
        found: set[str] = set()
        for doc in self.list_documents():
            found.update(re.findall(r"(?m)^([A-Z]{1,3})\d+[a-z]?\.\s", doc.text))
        return found

    def validate(self, name: str, text: str) -> Validation:
        return validate_document(name, text, self.entry_ids_of_current(except_name=name))

    # ---- writing (admin UI only) ---------------------------------------------------------------
    def _writable(self) -> None:
        if self.readonly:
            raise StoreError("This store was opened read-only.")

    def _audit(self, actor: str, action: str, target: str, detail: str = "") -> None:
        self._db.execute(
            "INSERT INTO audit(at, actor, action, target, detail) VALUES(?,?,?,?,?)",
            (now_iso(), actor, action, target, detail[:500]),
        )

    def _bump(self) -> None:
        self._db.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key='revision'")

    def _snapshot(self, name: str, actor: str, note: str) -> None:
        self._db.execute(
            "INSERT INTO versions(name, status, text, external_processing_approved, at, by, note) "
            "SELECT name, status, text, external_processing_approved, ?, ?, ? FROM documents "
            "WHERE name=?",
            (now_iso(), actor, note, name),
        )

    def put_pdf(self, data: bytes, filename: str, actor: str) -> str:
        self._writable()
        check_pdf(data)
        digest = hashlib.sha256(data).hexdigest()
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO pdfs(sha256, filename, size, data, uploaded_at, "
                "uploaded_by) VALUES(?,?,?,?,?,?)",
                (digest, Path(filename).name[:200], len(data), data, now_iso(), actor),
            )
            self._audit(actor, "upload-pdf", digest[:12], Path(filename).name)
        return digest

    def create_draft(
        self,
        name: str,
        text: str,
        actor: str,
        source_sha256: str = "",
        source_filename: str = "",
        status: str = "draft",
    ) -> StoredDocument:
        self._writable()
        if not NAME_RE.match(name):
            raise StoreError("The file name must be lowercase letters, digits and dashes (.md).")
        if status not in ("draft", "current"):
            raise StoreError("A new document starts as a draft or is imported as current.")
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise StoreError("The document is larger than 1 MB.")
        with self._lock, self._db:
            if self.get_document(name):
                raise StoreError(f"{name} already exists.")
            stamp = now_iso()
            self._db.execute(
                f"INSERT INTO documents({_DOC_COLUMNS}, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (name, status, text, 0, source_sha256, source_filename[:200], stamp, actor, stamp),
            )
            self._snapshot(name, actor, "created")
            self._audit(actor, "create", name, source_filename or status)
            if status == "current":
                self._bump()
        return self.get_document(name)  # type: ignore[return-value]

    def unique_name(self, wanted: str) -> str:
        stem = wanted[:-3]
        name, number = wanted, 2
        while self.get_document(name):
            name = f"{stem[:55]}-{number}.md"
            number += 1
        return name

    def save_text(self, name: str, text: str, actor: str, note: str = "edited") -> StoredDocument:
        """Save new text. A draft is saved as is (work in progress); a published document is
        validated first, so the bot can never be handed broken text."""
        self._writable()
        with self._lock, self._db:
            doc = self._need(name)
            if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
                raise StoreError("The document is larger than 1 MB.")
            if doc.status == "current":
                check = self.validate(name, text)
                if not check.ok:
                    raise StoreError("Not saved: " + " ".join(check.problems))
            self._db.execute(
                "UPDATE documents SET text=?, updated_at=?, updated_by=? WHERE name=?",
                (text, now_iso(), actor, name),
            )
            self._snapshot(name, actor, note)
            self._audit(actor, "edit" if note == "edited" else note, name)
            if doc.status == "current":
                self._bump()
        return self.get_document(name)  # type: ignore[return-value]

    def publish(
        self, name: str, actor: str, external_processing_approved: bool = False
    ) -> StoredDocument:
        """Make a draft or archived document live. The Qwen approval is an explicit argument,
        never defaulted on."""
        self._writable()
        with self._lock, self._db:
            doc = self._need(name)
            check = self.validate(name, doc.text)
            if not check.ok:
                raise StoreError("Cannot publish: " + " ".join(check.problems))
            self._db.execute(
                "UPDATE documents SET status='current', external_processing_approved=?, "
                "updated_at=?, updated_by=? WHERE name=?",
                (int(bool(external_processing_approved)), now_iso(), actor, name),
            )
            self._snapshot(name, actor, "published")
            self._audit(
                actor,
                "publish",
                name,
                "approved for Qwen" if external_processing_approved else "not sent to Qwen",
            )
            self._bump()
        return self.get_document(name)  # type: ignore[return-value]

    def set_external_approval(self, name: str, approved: bool, actor: str) -> StoredDocument:
        self._writable()
        with self._lock, self._db:
            doc = self._need(name)
            self._db.execute(
                "UPDATE documents SET external_processing_approved=?, updated_at=?, "
                "updated_by=? WHERE name=?",
                (int(bool(approved)), now_iso(), actor, name),
            )
            self._snapshot(name, actor, "qwen approval " + ("on" if approved else "off"))
            self._audit(actor, "qwen-approval", name, "on" if approved else "off")
            if doc.status == "current":
                self._bump()
        return self.get_document(name)  # type: ignore[return-value]

    def archive(self, name: str, actor: str) -> StoredDocument:
        """Take a document out of the bot's answers. It stays here and can be restored."""
        self._writable()
        with self._lock, self._db:
            doc = self._need(name)
            if doc.status != "current":
                raise StoreError(f"{name} is not published.")
            if len(self.list_documents("current")) <= 1:
                raise StoreError(
                    "This is the last published document. The bot needs at least one: publish "
                    "another first."
                )
            self._db.execute(
                "UPDATE documents SET status='archived', updated_at=?, updated_by=? WHERE name=?",
                (now_iso(), actor, name),
            )
            self._snapshot(name, actor, "archived")
            self._audit(actor, "archive", name)
            self._bump()
        return self.get_document(name)  # type: ignore[return-value]

    def delete(self, name: str, actor: str) -> None:
        """Permanently remove a draft or archived document (a published one must be archived
        first). Its saved versions and the audit trail stay."""
        self._writable()
        with self._lock, self._db:
            doc = self._need(name)
            if doc.status == "current":
                raise StoreError("Archive a published document before deleting it.")
            self._snapshot(name, actor, "deleted")
            self._db.execute("DELETE FROM documents WHERE name=?", (name,))
            self._audit(actor, "delete", name)

    def rollback(self, name: str, version_id: int, actor: str) -> StoredDocument:
        self._writable()
        with self._lock:
            row = self._db.execute(
                "SELECT text FROM versions WHERE id=? AND name=?", (version_id, name)
            ).fetchone()
        if not row:
            raise StoreError("That version does not exist.")
        return self.save_text(name, row["text"], actor, note=f"restored version {version_id}")

    def set_support(self, name: str, text: str, actor: str) -> None:
        self._writable()
        if name not in SUPPORT_FILES:
            raise StoreError(f"Unknown support file {name}.")
        if name == "entry-policy.yaml":
            data = yaml.safe_load(text) or {}
            if not isinstance(data, dict):
                raise StoreError("entry-policy.yaml must contain a mapping.")
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO support(name, text, updated_at, updated_by) VALUES(?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET text=excluded.text, "
                "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
                (name, text, now_iso(), actor),
            )
            self._audit(actor, "support", name)
            self._bump()

    def _need(self, name: str) -> StoredDocument:
        doc = self.get_document(name)
        if not doc:
            raise StoreError(f"{name} does not exist.")
        return doc

    def import_directory(self, directory: Path, actor: str = "import") -> list[str]:
        """Load the built-in documents (knowledge/current/) as published documents, once. Names
        already in the store are left alone. The built-in approval flags are kept."""
        self._writable()
        directory = Path(directory)
        policy_path = directory / "entry-policy.yaml"
        policy = (
            yaml.safe_load(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
        ) or {}
        approvals = policy.get("documents", {}) if isinstance(policy, dict) else {}
        imported = []
        for path in sorted(directory.glob("*.md")):
            if self.get_document(path.name):
                continue
            text = path.read_text(encoding="utf-8")
            try:
                parsed = parse_text(text, path)
            except ValueError:
                continue
            if not parsed.approved:
                continue
            self.create_draft(path.name, text, actor, source_filename=path.name, status="current")
            if (approvals.get(path.name) or {}).get("external_processing_approved") is True:
                self._db.execute(
                    "UPDATE documents SET external_processing_approved=1 WHERE name=?",
                    (path.name,),
                )
                self._db.commit()
            imported.append(path.name)
        for name in SUPPORT_FILES:
            file = directory / name
            if file.exists() and self.get_support(name) is None:
                self.set_support(name, file.read_text(encoding="utf-8"), actor)
        if imported:
            with self._lock, self._db:
                self._bump()
        return imported


class StoreSource:
    """Keeps the bot's local FAQ folder equal to the database's published documents.

    `sync` never raises. If the database is unreachable the folder is left as it is (and filled
    from `baked_dir`, the documents built into the image, if it is empty); a document that fails
    validation is skipped and its previous file kept.
    """

    def __init__(
        self,
        store,
        baked_dir: Path,
        poll_seconds: float = 5.0,
        retry_seconds: float = 30.0,
        clock=time.monotonic,
    ):
        self.store = store
        self.baked_dir = Path(baked_dir)
        self.poll_seconds = poll_seconds
        self.retry_seconds = retry_seconds
        self._clock = clock
        self._revision: int | None = None
        self._next_check = 0.0
        self._failing = False

    def sync(self, live_dir: Path) -> bool:
        if self._clock() < self._next_check:
            return False
        try:
            changed = self._sync(Path(live_dir))
        except Exception:
            if not self._failing:
                log.exception("Knowledge database unavailable; the bot keeps its current FAQ")
            self._failing = True
            self._next_check = self._clock() + self.retry_seconds
            return self._seed_if_empty(Path(live_dir))
        if self._failing:
            log.info("Knowledge database is reachable again")
        self._failing = False
        self._next_check = self._clock() + self.poll_seconds
        return changed

    def _seed_if_empty(self, live_dir: Path) -> bool:
        if any(live_dir.glob("*.md")) or not self.baked_dir.is_dir():
            return False
        live_dir.mkdir(parents=True, exist_ok=True)
        for source in list(self.baked_dir.glob("*.md")) + [
            self.baked_dir / n for n in SUPPORT_FILES if (self.baked_dir / n).exists()
        ]:
            shutil.copy2(source, live_dir / source.name)
        log.warning("Serving the FAQ built into the image (no published documents available)")
        return True

    def _sync(self, live_dir: Path) -> bool:
        revision = self.store.revision()
        if revision == self._revision and any(live_dir.glob("*.md")):
            return False
        published = self.store.list_documents("current")
        if not published:
            self._revision = revision
            return self._seed_if_empty(live_dir)
        live_dir.mkdir(parents=True, exist_ok=True)
        valid: dict[str, StoredDocument] = {}
        ids: dict[str, set[str]] = {}
        for doc in published:
            check = validate_document(doc.name, doc.text, ids)
            if not check.ok:
                log.error("Published document %s is invalid and was skipped: %s", doc.name, check)
                continue
            valid[doc.name] = doc
            ids[doc.name] = set(check.entry_ids)
        if not valid:
            log.error("No published document passed validation; the bot keeps its current FAQ")
            self._revision = revision
            return False
        changed = False
        for doc in valid.values():
            changed |= _write_if_different(live_dir / doc.name, doc.text)
        for stale in live_dir.glob("*.md"):
            if stale.name not in valid and not _skipped_but_present(stale.name, published):
                stale.unlink()
                changed = True
        policy = yaml.safe_load(self.store.get_support("entry-policy.yaml") or "") or {}
        if not isinstance(policy, dict):
            policy = {}
        policy["documents"] = {
            name: {"external_processing_approved": doc.external_processing_approved}
            for name, doc in valid.items()
        }
        changed |= _write_if_different(
            live_dir / "entry-policy.yaml",
            yaml.safe_dump(policy, sort_keys=False, allow_unicode=True, width=1000),
        )
        videos = self.store.get_support("playground-videos.yaml")
        if videos is None and (self.baked_dir / "playground-videos.yaml").exists():
            videos = (self.baked_dir / "playground-videos.yaml").read_text(encoding="utf-8")
        if videos is not None:
            changed |= _write_if_different(live_dir / "playground-videos.yaml", videos)
        self._revision = revision
        return changed


def _skipped_but_present(name: str, published: list[StoredDocument]) -> bool:
    """A published document that failed validation keeps its previous file (last good)."""
    return any(d.name == name for d in published)


def _write_if_different(path: Path, text: str) -> bool:
    """Rewriting identical text would change the file time and make the bot rebuild its index."""
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    atomic_write(path, text)
    return True


class ReconnectingStore:
    """Opens the store on first use and again after a failure, so a database that is missing or
    down when the bot starts is not a startup error (StoreSource.sync handles the exception)."""

    def __init__(self, factory):
        self._factory = factory
        self._store = None

    def __getattr__(self, name):
        if self._store is None:
            self._store = self._factory()
        try:
            return getattr(self._store, name)
        except sqlite3.Error:
            self._store = None
            raise
