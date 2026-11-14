import json

import pytest

from gab_faq.backups import backup, restore, verify
from gab_faq.discord_bot.queries import QueryStore
from gab_faq.tickets import Ticket, TicketStore


def test_online_backup_and_restore_recovers_queries_tickets_and_panel(tmp_path):
    source = tmp_path / "source"
    queries = QueryStore(source, lambda _: True)
    try:
        queries.add({"message_id": "1", "content": "question?"})
        TicketStore(source).record(Ticket(1, 2, 3, 4, 5, 1, "open"))
        (source / "faq_panel_id.json").write_text(json.dumps({"1": "99"}))
        snapshot = backup(source, tmp_path / "snapshot")
        verify(snapshot)
        recovered = tmp_path / "recovered"
        restore(snapshot, recovered)
        replacement = QueryStore(recovered, lambda _: True)
        try:
            assert replacement.records()[0]["content"] == "question?"
            assert TicketStore(recovered).known(1, 2)
            assert json.loads((recovered / "faq_panel_id.json").read_text()) == {"1": "99"}
        finally:
            replacement.close()
    finally:
        queries.close()


def test_corrupt_backup_and_existing_restore_target_are_rejected(tmp_path):
    source = tmp_path / "source"
    queries = QueryStore(source, lambda _: True)
    queries.close()
    snapshot = backup(source, tmp_path / "snapshot")
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep.txt").write_text("keep")
    with pytest.raises(ValueError, match="empty"):
        restore(snapshot, existing)
    assert (existing / "keep.txt").read_text() == "keep"
    (snapshot / "queries.sqlite3").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        verify(snapshot)
