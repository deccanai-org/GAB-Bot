"""Create the knowledge schema (if needed) and import knowledge/current/ FAQs.

Usage (password stays in the environment, never on the command line):

  set GAB_KNOWLEDGE_ADMIN_DB=postgresql://user:***@host:5432/dbname
  python scripts/init_knowledge_db.py

Re-running is safe: existing document names are left alone; only missing FAQs are added.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gab_faq.knowledge_store import open_store, redact_location  # noqa: E402


def main() -> int:
    url = (os.environ.get("GAB_KNOWLEDGE_ADMIN_DB") or os.environ.get("GAB_KNOWLEDGE_DB") or "").strip()
    if not url:
        print(
            "Set GAB_KNOWLEDGE_ADMIN_DB (writer) or GAB_KNOWLEDGE_DB to a postgresql:// URL.",
            file=sys.stderr,
        )
        return 2
    knowledge_dir = ROOT / "knowledge" / "current"
    if not knowledge_dir.is_dir():
        print(f"Missing FAQ directory: {knowledge_dir}", file=sys.stderr)
        return 2

    print(f"Opening store at {redact_location(url)} …")
    store = open_store(url, readonly=False)
    try:
        before = store.counts()
        imported = store.import_directory(knowledge_dir, actor="init_knowledge_db")
        after = store.counts()
        print(f"Schema ready. Counts before={before} after={after}")
        print(f"Imported {len(imported)} document(s): {', '.join(imported) or '(none new)'}")
        current = [d.name for d in store.list_documents("current")]
        print(f"Published (current) docs ({len(current)}): {', '.join(current)}")
        print(f"Revision: {store.revision()}")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
