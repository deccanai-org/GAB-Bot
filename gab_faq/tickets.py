"""Durable Discord follow-up index, independent of message-history scan windows."""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Ticket:
    channel_id: int
    message_id: int
    asker_id: int
    staff_channel_id: int
    staff_message_id: int
    posted_at: float
    status: str


class TicketStore:
    def __init__(self, directory: Path):
        self.path = Path(directory) / "faq_state.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tickets (
                    channel_id TEXT NOT NULL, message_id TEXT NOT NULL, asker_id TEXT NOT NULL,
                    staff_channel_id TEXT NOT NULL, staff_message_id TEXT NOT NULL,
                    posted_at REAL NOT NULL, status TEXT NOT NULL, checked_at REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(channel_id, message_id));
                CREATE INDEX IF NOT EXISTS ticket_work ON tickets(status, checked_at);
                CREATE TABLE IF NOT EXISTS cursors (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    @contextmanager
    def _connect(self):
        with self._lock:
            db = sqlite3.connect(self.path, timeout=10)
            try:
                with db:
                    yield db
            finally:
                db.close()

    def record(self, ticket: Ticket):
        if ticket.status not in {"open", "reminded", "answered", "missing"}:
            raise ValueError("Invalid ticket status")
        with self._connect() as db:
            db.execute(
                """INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(channel_id,message_id) DO UPDATE SET
                  status=CASE WHEN tickets.status='answered' THEN tickets.status
                    WHEN tickets.status='reminded' AND excluded.status='open' THEN 'reminded'
                    ELSE excluded.status END,
                  staff_channel_id=excluded.staff_channel_id, staff_message_id=excluded.staff_message_id
                """,
                (
                    str(ticket.channel_id),
                    str(ticket.message_id),
                    str(ticket.asker_id),
                    str(ticket.staff_channel_id),
                    str(ticket.staff_message_id),
                    ticket.posted_at,
                    ticket.status,
                ),
            )

    def known(self, channel_id: int, message_id: int) -> bool:
        with self._connect() as db:
            return (
                db.execute(
                    "SELECT 1 FROM tickets WHERE channel_id=? AND message_id=? AND status!='missing'",
                    (str(channel_id), str(message_id)),
                ).fetchone()
                is not None
            )

    def pending(self, limit=50) -> list[Ticket]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT channel_id,message_id,asker_id,staff_channel_id,
                staff_message_id,posted_at,status FROM tickets WHERE status IN ('open','reminded')
                ORDER BY checked_at,posted_at LIMIT ?""",
                (limit,),
            ).fetchall()
        return [Ticket(*(int(value) for value in row[:5]), row[5], row[6]) for row in rows]

    def touch(self, ticket: Ticket, now: float):
        with self._connect() as db:
            db.execute(
                "UPDATE tickets SET checked_at=? WHERE channel_id=? AND message_id=?",
                (now, str(ticket.channel_id), str(ticket.message_id)),
            )

    def status(self, channel_id: int, message_id: int, status: str):
        if status not in {"open", "reminded", "answered", "missing"}:
            raise ValueError("Invalid ticket status")
        with self._connect() as db:
            db.execute(
                "UPDATE tickets SET status=? WHERE channel_id=? AND message_id=?",
                (status, str(channel_id), str(message_id)),
            )

    def cursor(self, key: str) -> int | None:
        with self._connect() as db:
            row = db.execute("SELECT value FROM cursors WHERE key=?", (key,)).fetchone()
        return int(row[0]) if row else None

    def advance(self, key: str, value: int):
        with self._connect() as db:
            db.execute(
                """INSERT INTO cursors VALUES (?,?) ON CONFLICT(key) DO UPDATE
                SET value=excluded.value WHERE CAST(excluded.value AS INTEGER)>CAST(cursors.value AS INTEGER)""",
                (key, str(value)),
            )

    def counts(self) -> dict[str, int]:
        with self._connect() as db:
            return dict(db.execute("SELECT status,COUNT(*) FROM tickets GROUP BY status"))

    def health(self) -> bool:
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO cursors VALUES ('health:probe', ?)", (str(time.time()),)
                )
            return True
        except sqlite3.Error:
            return False
