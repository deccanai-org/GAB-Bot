"""Ticket persistence, restart recovery, fair polling, and large-history progress."""

from dataclasses import replace

from gab_faq.tickets import Ticket, TicketStore

from . import test_followup as f


def test_tickets_survive_restart_and_round_robin_large_queues(tmp_path):
    store = TicketStore(tmp_path)
    for i in range(60):
        store.record(Ticket(11, 100 + i, 42, 13, 500 + i, 1, "open"))
    first = store.pending(50)
    for ticket in first:
        store.touch(ticket, 10)
    restarted = TicketStore(tmp_path)
    assert [ticket.message_id for ticket in restarted.pending(10)] == list(range(150, 160))
    assert restarted.known(11, 100)


def test_old_history_does_not_reopen_resolved_or_reminded_tickets(tmp_path):
    store = TicketStore(tmp_path)
    ticket = Ticket(11, 100, 42, 13, 500, 1, "open")
    store.record(ticket)
    store.status(11, 100, "reminded")
    store.record(ticket)
    assert store.pending()[0].status == "reminded"
    store.status(11, 100, "answered")
    store.record(ticket)
    assert store.pending() == [] and store.known(11, 100)


def test_missing_staff_card_can_be_redelivered(tmp_path):
    store = TicketStore(tmp_path)
    store.record(Ticket(11, 100, 42, 13, 500, 1, "open"))
    store.status(11, 100, "missing")
    assert not store.known(11, 100)
    store.record(Ticket(11, 100, 42, 13, 501, 2, "open"))
    assert store.pending()[0].staff_message_id == 501
    assert store.pending()[0].status == "open"


def test_followup_indexes_questions_older_than_three_days(tmp_path):
    followup, unanswered = f.make(
        tmp_path, [f.card(11, 100, 60 * 24 * 5)], f.FakeChannel(11, "support")
    )
    f.run(followup.check_once())
    assert f.status_of(unanswered.messages[0]) == "reminded"
    assert followup.tickets.known(11, 100)


def test_index_migration_advances_across_batches_and_restarts(tmp_path):
    cards = [f.card(11, 100 + i, 1) for i in range(7)]
    followup, unanswered = f.make(tmp_path, cards, f.FakeChannel(11, "support"))
    followup.settings = replace(followup.settings, history_batch_size=3)
    f.run(followup.check_once())
    assert followup.tickets.counts()["open"] == 3
    replacement, _ = f.make(tmp_path, cards, f.FakeChannel(11, "support"))
    replacement.settings = replace(replacement.settings, history_batch_size=3)
    f.run(replacement.check_once())
    f.run(replacement.check_once())
    assert replacement.tickets.counts()["open"] == 7


def test_reminder_card_edit_failure_does_not_repeat_delivered_reminder(tmp_path):
    followup, unanswered = f.make(tmp_path, [f.card(11, 100, 90)], f.FakeChannel(11, "support"))
    original_edit = unanswered.messages[0].edit

    async def fail(**kwargs):
        raise f.discord.Forbidden(
            f.SimpleNamespace(status=403, reason="Forbidden"), "synthetic failure"
        )

    unanswered.messages[0].edit = fail
    f.run(followup.check_once())
    assert len(unanswered.sent) == 1
    unanswered.messages[0].edit = original_edit
    f.run(followup.check_once())
    assert len(unanswered.sent) == 1
    assert f.status_of(unanswered.messages[0]) == "reminded"


def test_reply_scan_moves_forward_past_the_first_page(tmp_path):
    messages = [f.FakeMessage(101 + i, f.ASKER, "follow-up") for i in range(5)]
    messages.append(
        f.FakeMessage(106, f.STAFF, "resolved", reference=f.SimpleNamespace(message_id=100))
    )
    followup, unanswered = f.make(
        tmp_path, [f.card(11, 100, 1)], f.FakeChannel(11, "support", messages)
    )
    followup.settings = replace(followup.settings, reply_batch_size=2)
    for _ in range(3):
        f.run(followup.check_once())
    assert f.status_of(unanswered.messages[0]) == "answered"
