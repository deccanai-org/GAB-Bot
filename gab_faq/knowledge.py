"""Loads the FAQ files the bot answers from.

Only files in knowledge/current/ are loaded. Older phases live in knowledge/archive/ and are never
shown to freelancers, so the bot can't hand out an out-of-date model name.

Each file is Markdown with a small header ("front matter") between --- lines, e.g.:

    ---
    title: Phase 5 FAQ - Annotation
    audience: annotator        # annotator | qc | all
    phase: 5
    updated: 2026-11-08
    ---

The ops team can edit these files while the bot is running; the bot picks up changes on the next
question.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from .redact import contains_secret
from .tutorials import TutorialVideo, load_tutorials

log = logging.getLogger(__name__)

VALID_AUDIENCES = {"annotator", "qc", "qm", "all"}
# Documents only Queue Managers may see. They are left out of the prompt entirely for everyone else,
# so the bot cannot leak them no matter how a question is phrased.
INTERNAL_AUDIENCES = {"qm"}


@dataclass(frozen=True)
class FaqDocument:
    path: Path
    title: str
    audience: str
    phase: str
    updated: str
    body: str
    # Only approved documents are ever served: "status: archived" or "approved: false" in the
    # header keeps a file out of every answer (see KnowledgeBase.reload_if_changed).
    approved: bool = True
    tutorials: tuple[TutorialVideo, ...] = ()
    source: str = ""
    version: str = ""
    status: str = "current"
    external_processing_approved: bool = False
    entry_metadata: dict = field(default_factory=dict)


def parse_document(path: Path) -> FaqDocument:
    return parse_text(path.read_text(encoding="utf-8"), path)


def parse_text(text: str, path: Path) -> FaqDocument:
    """Parse one FAQ file's text; `path` only supplies the name and the entry source labels."""
    meta: dict = {}
    body = text
    if text.startswith("---"):
        _, header, body = text.split("---", 2)
        try:
            meta = yaml.safe_load(header) or {}
        except yaml.YAMLError as e:
            raise ValueError(
                f"{path.name}: the header between the --- lines is not valid. If a value contains "
                f"quotes or a colon, wrap the whole value in single quotes. Details: {e}"
            ) from e
    audience = str(meta.get("audience", "all")).lower()
    if audience not in VALID_AUDIENCES:
        raise ValueError(
            f"{path.name}: audience must be one of {sorted(VALID_AUDIENCES)}, got {audience!r}"
        )
    return FaqDocument(
        path=path,
        title=str(meta.get("title", path.stem)),
        audience=audience,
        phase=str(meta.get("phase", "")),
        updated=str(meta.get("updated", "")),
        body=body.strip(),
        approved=meta.get("approved", True) is not False
        and str(meta.get("status", "")).strip().lower() not in {"archived", "superseded", "draft"},
        source=str(meta.get("source", path.name)),
        version=str(meta.get("version", meta.get("phase", ""))),
        status=str(meta.get("status", "current")),
        external_processing_approved=meta.get("external_processing_approved") is True,
    )


class KnowledgeBase:
    """Holds the current FAQ text and reloads it when a file changes."""

    def __init__(self, directory: Path, source=None):
        """`source` (optional, see knowledge_store.StoreSource) fills `directory` from the
        knowledge database; with none, `directory` is edited by hand as before."""
        self.directory = Path(directory)
        self.source = source
        self._lock = threading.Lock()
        self._signature: tuple | None = None
        self.documents: list[FaqDocument] = []
        self.reload_if_changed()

    def _current_signature(self) -> tuple:
        files = sorted(self.directory.glob("*.md"))
        catalog = self.directory / "playground-videos.yaml"
        if catalog.exists():
            files.append(catalog)
        policy = self.directory / "entry-policy.yaml"
        if policy.exists():
            files.append(policy)
        return tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in files)

    def reload_if_changed(self) -> bool:
        with self._lock:
            if self.source is not None:
                self.source.sync(self.directory)  # never raises: keeps the last good files
            signature = self._current_signature()
            if signature == self._signature:
                return False
            if not signature:
                raise FileNotFoundError(f"No FAQ files (*.md) found in {self.directory}")
            tutorials = load_tutorials(self.directory / "playground-videos.yaml")
            policy_path = self.directory / "entry-policy.yaml"
            policy = (
                yaml.safe_load(policy_path.read_text(encoding="utf-8"))
                if policy_path.exists()
                else {}
            ) or {}
            if not isinstance(policy, dict):
                raise ValueError("entry-policy.yaml must contain a mapping")
            docs = []
            for p in sorted(self.directory.glob("*.md")):
                doc = parse_document(p)
                if not doc.approved:
                    log.warning(
                        "FAQ file %s is archived or not approved: not used for answers", p.name
                    )
                elif contains_secret(doc.body):
                    log.error(
                        "FAQ file %s contains what looks like a password, token or API key: NOT "
                        "used for answers until it is removed",
                        p.name,
                    )
                else:
                    approval = policy.get("documents", {}).get(p.name, {})
                    docs.append(
                        replace(
                            doc,
                            tutorials=tutorials,
                            external_processing_approved=approval.get(
                                "external_processing_approved", doc.external_processing_approved
                            )
                            is True,
                            entry_metadata=policy.get("entries", {}),
                        )
                    )
            if not docs:
                raise FileNotFoundError(f"No approved FAQ files (*.md) in {self.directory}")
            self.documents = docs
            self._signature = signature
            return True

    def documents_for(self, role: str) -> list[FaqDocument]:
        """Annotators, QC reviewers and unknown askers see every document except internal (QM)
        ones; QMs see everything."""
        if role == "qm":
            return list(self.documents)
        return [d for d in self.documents if d.audience not in INTERNAL_AUDIENCES]

    def render(self, role: str = "unknown") -> str:
        """The FAQ as one block of text for the model. Sorted by file name so it is identical on
        every request for the same kind of asker (which keeps prompt caching effective)."""
        parts = []
        for doc in self.documents_for(role):
            parts.append(
                f'<faq_document title="{doc.title}" audience="{doc.audience}" '
                f'phase="{doc.phase}" updated="{doc.updated}">\n{doc.body}\n</faq_document>'
            )
        return "\n\n".join(parts)


def build_knowledge(settings) -> KnowledgeBase:
    """The FAQ the bot answers from: the knowledge database when one is configured
    (gab_faq.knowledge_store in config.yaml or GAB_KNOWLEDGE_DB), else knowledge/current/."""
    if settings.knowledge_store is None:
        return KnowledgeBase(settings.knowledge_dir)
    from .knowledge_store import ReconnectingStore, SqliteKnowledgeStore, StoreSource

    path = settings.knowledge_store
    source = StoreSource(
        ReconnectingStore(lambda: SqliteKnowledgeStore(path, readonly=True)),
        baked_dir=settings.knowledge_dir,
    )
    return KnowledgeBase(settings.knowledge_live_dir, source=source)
