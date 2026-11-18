"""python -m gab_faq.admin: start the admin UI.

    GAB_ADMIN_PASSWORD='a long password' python -m gab_faq.admin --import-builtin

The password is read from the environment only (never a command-line argument). The UI listens on
127.0.0.1 unless you pass --behind-tls-proxy, which says an HTTPS reverse proxy sits in front: the
login is HTTP Basic, so it must never cross a network unencrypted.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from aiohttp import web

from ..knowledge_store import SqliteKnowledgeStore
from .app import create_app

ROOT = Path(__file__).resolve().parent.parent.parent
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
MIN_PASSWORD = 12


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--store",
        type=Path,
        default=Path(os.environ.get("GAB_KNOWLEDGE_DB") or ROOT / "output" / "knowledge.sqlite3"),
        help="knowledge database file (default: output/knowledge.sqlite3 or GAB_KNOWLEDGE_DB)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument(
        "--builtin", type=Path, default=ROOT / "knowledge" / "current", help="built-in documents"
    )
    parser.add_argument(
        "--import-builtin",
        action="store_true",
        help="import the built-in documents into an empty store before starting",
    )
    parser.add_argument("--behind-tls-proxy", action="store_true")
    args = parser.parse_args(argv)

    password = os.environ.get("GAB_ADMIN_PASSWORD", "")
    if len(password) < MIN_PASSWORD:
        print(
            f"Set GAB_ADMIN_PASSWORD (at least {MIN_PASSWORD} characters) in the environment.",
            file=sys.stderr,
        )
        return 2
    if args.host not in LOOPBACK and not args.behind_tls_proxy:
        print(
            "Refusing to listen beyond this computer without HTTPS: put a TLS reverse proxy in "
            "front and pass --behind-tls-proxy, or use --host 127.0.0.1.",
            file=sys.stderr,
        )
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = SqliteKnowledgeStore(args.store)
    if args.import_builtin:
        imported = store.import_directory(args.builtin, actor="import")
        logging.info("Imported %d built-in documents", len(imported))
    app = create_app(
        store, os.environ.get("GAB_ADMIN_USER", "pm"), password, baked_dir=args.builtin
    )
    logging.info("Knowledge database: %s", args.store)
    web.run_app(app, host=args.host, port=args.port, print=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
