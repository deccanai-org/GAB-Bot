"""Sanitized persistence. Snapshots are atomically replaced; logs are append-only."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .redact import redact_secrets

log = logging.getLogger(__name__)


def sanitize(value):
    """Remove secrets at the persistence boundary, including nested request fields."""
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return value


def atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, value) -> None:
    atomic_write(path, json.dumps(sanitize(value), ensure_ascii=False, indent=2))


def csv_bytes(records: list[dict], fields: list[str]) -> bytes:
    """CSV output is sanitized independently of its caller; formulas remain plain text."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        row = sanitize(record)
        row = {
            key: (
                "'" + value
                if isinstance(value, str)
                and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
                else value
            )
            for key, value in row.items()
        }
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


class JsonLines:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, name: str, entry: dict) -> dict:
        clean = sanitize(entry)
        line = json.dumps(clean, ensure_ascii=False) + "\n"
        with self._lock:
            with (self.directory / name).open("a", encoding="utf-8") as handle:
                handle.write(line)
        return clean


class SecretFilter(logging.Filter):
    """Scrub formatted log messages and exception text before any handler sees them."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = redact_secrets(record.getMessage()), ()
        if record.exc_info:
            record.exc_text = redact_secrets(logging.Formatter().formatException(record.exc_info))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        fields = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            fields["exception"] = record.exc_text or self.formatException(record.exc_info)
        return json.dumps(sanitize(fields), ensure_ascii=False)


def configure_logging(log_file: Path | None = None) -> None:
    handlers = [logging.StreamHandler()]
    if log_file is not None:
        handlers.append(
            RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        )
    for handler in handlers:
        handler.addFilter(SecretFilter())
        if os.environ.get("GAB_ENVIRONMENT", "").strip().casefold() == "production":
            handler.setFormatter(JsonFormatter())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
