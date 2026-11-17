"""Query detection, sanitization, and transactional collection; no bot globals."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from fnmatch import fnmatchcase
from pathlib import Path

import discord

from ..redact import redact_secrets
from ..storage import atomic_write, csv_bytes, read_json, sanitize, write_json
from .settings import BotSettings

log = logging.getLogger(__name__)
CSV_FIELDS = [
    "message_id",
    "channel_id",
    "channel_name",
    "author_id",
    "author_name",
    "timestamp",
    "category",
    "content",
    "section",
]


def section(channel) -> str:
    if isinstance(channel, discord.Thread):
        channel = channel.parent
    return getattr(getattr(channel, "category", None), "name", "")


def watched(name: str, patterns) -> bool:
    """True when a channel or section name is in config.yaml channel_names. Entries may use * for
    any run of characters ("GAB Phase*" covers every phase); matching ignores case."""
    key = name.casefold()
    return key in patterns or any("*" in p and fnmatchcase(key, p) for p in patterns)


def all_text_channels(guild) -> list:
    return list(
        {
            channel.id: channel
            for channel in (
                list(guild.text_channels) + list(getattr(guild, "news_channels", []) or [])
            )
        }.values()
    )


def top_unique_recent_queries(records: list[dict], count: int) -> list[dict]:
    seen, result = set(), []
    for record in sorted(records, key=lambda item: item["timestamp"], reverse=True):
        key = " ".join(record.get("content", "").casefold().split())
        if len(key) < 2 or key in seen:
            continue
        seen.add(key)
        result.append(record)
        if len(result) >= count:
            break
    return result


class QueryStore:
    """SQLite is the source of truth; JSON/CSV remain compatible export snapshots.

    Each insertion is committed without rewriting the complete history. Old JSON data
    is migrated and scrubbed once, and writes never share a connection concurrently.
    """

    def __init__(self, directory: Path, is_query):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.directory / "queries.sqlite3", check_same_thread=False
        )
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS queries (message_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._connection.commit()
        self._closed = False
        self._dirty = True
        migrated = self._connection.execute(
            "SELECT 1 FROM metadata WHERE name='json_migrated'"
        ).fetchone()
        if not migrated:
            records = read_json(self.directory / "messages.json", [])
            if not isinstance(records, list):
                raise ValueError("messages.json must contain a list of query records")
            for record in records:
                if (
                    isinstance(record, dict)
                    and record.get("message_id")
                    and is_query(record.get("content", ""))
                ):
                    self.add(record)
            self._connection.execute("INSERT INTO metadata VALUES ('json_migrated', '1')")
            self._connection.commit()
        self.snapshot()

    def add(self, record: dict) -> bool:
        clean = sanitize(record)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO queries VALUES (?, ?)",
                (str(clean["message_id"]), json.dumps(clean, ensure_ascii=False)),
            )
            self._dirty = self._dirty or cursor.rowcount > 0
            return cursor.rowcount > 0

    def records(self) -> list[dict]:
        with self._lock:
            return [
                json.loads(row[0])
                for row in self._connection.execute("SELECT payload FROM queries ORDER BY rowid")
            ]

    def snapshot(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            records = self.records()
            write_json(self.directory / "messages.json", records)
            atomic_write(
                self.directory / "messages.csv", csv_bytes(records, CSV_FIELDS).decode("utf-8")
            )
            self._dirty = False

    def health(self) -> bool:
        with self._lock:
            if self._closed:
                return False
            try:
                with self._connection:
                    self._connection.execute(
                        "INSERT OR REPLACE INTO metadata VALUES ('health', datetime('now'))"
                    )
                return True
            except sqlite3.Error:
                log.exception("Query database write health check failed")
                return False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self.snapshot()
            finally:
                self._connection.close()
                self._closed = True


class QueryService:
    def __init__(self, settings: BotSettings):
        self.settings = settings
        self._patterns = [
            (
                category["name"],
                [
                    re.compile(re.escape(str(word)), re.IGNORECASE)
                    for word in category.get("keywords", [])
                ],
            )
            for category in settings.categories
        ]
        self._fallback = next(
            (
                item["name"]
                for item in reversed(settings.categories)
                if any(word in item["name"].casefold() for word in ("other", "misc"))
            ),
            settings.categories[-1]["name"],
        )
        self.store = QueryStore(settings.output_dir, self.is_query)

    def is_query(self, content: str) -> bool:
        return bool(
            content
            and (
                (self.settings.question_mark_counts and "?" in content)
                or any(phrase in content.casefold() for phrase in self.settings.query_phrases)
            )
        )

    def categorize(self, content: str) -> str:
        return next(
            (name for name, patterns in self._patterns if any(p.search(content) for p in patterns)),
            self._fallback,
        )

    def is_watched(self, channel) -> bool:
        if isinstance(channel, discord.Thread):
            return bool(channel.parent and self.is_watched(channel.parent))
        keys = [getattr(channel, "name", ""), section(channel)]
        return any(key and watched(key, self.settings.watched_names) for key in keys)

    def watched_channels(self, guild) -> list:
        return [channel for channel in all_text_channels(guild) if self.is_watched(channel)]

    def record(self, message) -> dict | None:
        if message.author.bot:
            return None
        content = redact_secrets(message.content or "")
        return sanitize(
            {
                "message_id": str(message.id),
                "channel_id": str(message.channel.id),
                "channel_name": getattr(message.channel, "name", str(message.channel.id)),
                "section": section(message.channel),
                "author_id": str(message.author.id),
                "author_name": str(message.author),
                "timestamp": message.created_at.isoformat(),
                "content": content,
                "category": self.categorize(content),
            }
        )

    def capture(self, message) -> bool:
        if not self.is_watched(message.channel) or not self.is_query(message.content or ""):
            return False
        record = self.record(message)
        if record is None or not self.store.add(record):
            return False
        log.info(
            "Collected query message=%s channel=%s category=%s",
            message.id,
            message.channel.id,
            record["category"],
        )
        return True
