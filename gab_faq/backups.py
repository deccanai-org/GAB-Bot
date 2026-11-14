"""Consistent SQLite backups and verified restore into a fresh, offline directory."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .operations import ProcessOwner
from .storage import read_json, write_json

DATABASES = ("queries.sqlite3", "faq_state.sqlite3")


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def integrity(path: Path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError(f"Database integrity check failed: {path.name}")


def backup(directory: Path, destination: Path) -> Path:
    directory, destination = Path(directory), Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {"version": 1, "created": datetime.now(timezone.utc).isoformat(), "files": {}}
    for name in DATABASES:
        source = directory / name
        if not source.exists():
            continue
        target = destination / name
        with closing(
            sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
        ) as source_db:
            with closing(sqlite3.connect(target)) as target_db:
                source_db.backup(target_db)
        integrity(target)
        manifest["files"][name] = digest(target)
    panel = directory / "faq_panel_id.json"
    if panel.exists():
        shutil.copyfile(panel, destination / panel.name)
        manifest["files"][panel.name] = digest(destination / panel.name)
    if not manifest["files"]:
        raise ValueError("No bot state found to back up")
    write_json(destination / "manifest.json", manifest)
    return destination


def verify(source: Path) -> dict:
    source = Path(source)
    manifest = read_json(source / "manifest.json", None)
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or not manifest.get("files"):
        raise ValueError("Invalid or incomplete backup manifest")
    for name, checksum in manifest["files"].items():
        if name not in {*DATABASES, "faq_panel_id.json"} or digest(source / name) != checksum:
            raise ValueError("Backup checksum mismatch or unexpected file")
        if name in DATABASES:
            integrity(source / name)
    return manifest


def restore(source: Path, destination: Path):
    manifest = verify(source)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    owner = ProcessOwner(destination / "bot.owner.lock")
    try:
        if any(path.name != "bot.owner.lock" for path in destination.iterdir()):
            raise ValueError(
                "Restore destination must be empty; existing data is never overwritten"
            )
        for name in manifest["files"]:
            shutil.copyfile(Path(source) / name, destination / name)
    finally:
        owner.close()
