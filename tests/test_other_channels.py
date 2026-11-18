"""'Gigi in other channels': staff add a channel with a button and Gigi answers there when someone
@mentions it. The guarantee tested end to end: mention-only, never unprompted, saved across
restarts, and every step behind the private staff channel and role checks."""

import json
import logging
from types import SimpleNamespace

import discord
import pytest

from gab_faq import knowledge_updates as ku
from gab_faq.config import KnowledgeUpdatesSettings
from gab_faq.knowledge_store import SqliteKnowledgeStore, StoreError
from gab_faq.knowledge_updates import ChannelScope, DocumentOps, KnowledgeUpdates

from .test_discord_answers import BOT_USER, FakeBrain, FakeMessage, make
from .test_discord_answers import run as run_answers
from .test_knowledge_updates import Channel, Member, build, pi, run


def answerer_with_updates(tmp_path, **cfg):
    """The real FaqAnswerer, limited by config to #maitrix-qc, with the updates feature on."""
    brain = FakeBrain()
    answerer, guild, channels = make(
        tmp_path, brain, only_in=["maitrix-qc"], answer_channels=[], **cfg
    )
    store = SqliteKnowledgeStore(tmp_path / "scope.sqlite3")
    answerer.updates = KnowledgeUpdates(
        answerer.bot, KnowledgeUpdatesSettings(enabled=True), DocumentOps(store)
    )
    return answerer, guild, channels, brain, store


def ask(answerer, channel, guild, text="which model for product A?", mention=True):
    content = f"<@999> {text}" if mention else text
    message = FakeMessage(content, channel, guild, mentions=[BOT_USER] if mention else [])
    return run_answers(answerer.handle(message)), message


# ---- the guarantee, through the real answering code ------------------------------------------
def test_a_channel_added_with_the_button_answers_on_mention_and_never_unprompted(tmp_path):
    answerer, guild, ch, brain, store = answerer_with_updates(tmp_path)
    handled, _ = ask(answerer, ch.general, guild)
    assert handled is False and brain.calls == []  # outside the configured scope: ignored

    answerer.updates.scope.add(str(ch.general.id), "general", "Rae (discord:9)")
    handled, message = ask(answerer, ch.general, guild)
    assert handled is True and message.replies == ["Select Flash, then Model Locust."]
    assert brain.calls[-1][1] == "unknown"  # no special role: the shared FAQ, never QM-only text

    brain.calls.clear()
    handled, _ = ask(answerer, ch.general, guild, "anyone know the deadline?", mention=False)
    assert handled is False and brain.calls == []  # ordinary chatter is never answered
    handled, _ = ask(answerer, ch.ask, guild)  # a different channel that was never added
    assert handled is False and brain.calls == []

    answerer.updates.scope.remove(str(ch.general.id), "Rae (discord:9)")
    handled, _ = ask(answerer, ch.general, guild)
    assert handled is False  # turned off again


def test_the_channels_survive_a_restart(tmp_path):
    answerer, guild, ch, brain, store = answerer_with_updates(tmp_path)
    answerer.updates.scope.add(str(ch.general.id), "general", "Rae (discord:9)")
    reopened = ChannelScope(SqliteKnowledgeStore(tmp_path / "scope.sqlite3"))
    assert reopened.ids == frozenset()  # nothing loaded yet
    reopened.load()
    assert reopened.ids == frozenset({str(ch.general.id)})
    saved = json.loads(store.get_support("answer-channels.json"))["channels"][0]
    assert saved["name"] == "general" and saved["added_by"] == "Rae (discord:9)"
    assert any(
        r["action"] == "support" and r["actor"] == "Rae (discord:9)" for r in store.audit_log()
    )


def test_a_channel_or_its_parent_matches_so_threads_inside_are_covered(tmp_path):
    updates, _, _ = build(tmp_path)
    updates.scope.add("123", "help", "pm")
    assert updates.in_extra_scope("help-thread", "999", "123")  # a thread's parent key
    assert not updates.in_extra_scope("other", "456", "", None)


def test_the_extras_are_read_at_start_up_and_a_broken_database_leaves_none_active(tmp_path, caplog):
    updates, store, _ = build(tmp_path)
    store.set_support(
        "answer-channels.json", json.dumps({"channels": [{"id": "77", "name": "x"}]}), "pm"
    )
    run(updates.start())
    assert updates.in_extra_scope("77")

    def down(*args, **kwargs):
        raise OSError("database down")

    updates.scope.store = SimpleNamespace(get_support=down)
    with caplog.at_level(logging.ERROR):
        run(updates.reload_scope())  # must not raise
    assert "Could not read the extra channels" in caplog.text


def test_bad_saved_data_is_ignored_not_trusted(tmp_path, caplog):
    updates, store, _ = build(tmp_path)
    store.set_support(
        "answer-channels.json",
        json.dumps({"channels": [{"id": "55", "name": "ok"}, {"id": "not-a-number"}, "junk", {}]}),
        "pm",
    )
    updates.scope.load()
    assert updates.scope.ids == frozenset({"55"})
    with pytest.raises(StoreError):
        store.set_support("answer-channels.json", "not json", "pm")
    with pytest.raises(StoreError):
        store.set_support("answer-channels.json", json.dumps({"channels": "x"}), "pm")


def test_the_number_of_extra_channels_is_limited(tmp_path):
    updates, _, _ = build(tmp_path)
    for i in range(ku.MAX_EXTRA_CHANNELS):
        updates.scope.add(str(1000 + i), f"c{i}", "pm")
    with pytest.raises(StoreError, match="At most"):
        updates.scope.add("9999", "one-too-many", "pm")
    with pytest.raises(StoreError, match="already answers"):
        updates.scope.add("1000", "c0", "pm")
    with pytest.raises(StoreError, match="not on"):
        updates.scope.remove("424242", "pm")


def test_a_failed_save_leaves_the_active_channels_unchanged(tmp_path, monkeypatch):
    updates, store, _ = build(tmp_path)
    updates.scope.add("1", "first", "pm")

    def refuse(*args, **kwargs):
        raise OSError("database full")

    monkeypatch.setattr(store, "set_support", refuse)
    with pytest.raises(OSError):
        updates.scope.add("2", "second", "pm")
    assert updates.scope.ids == frozenset({"1"})  # memory never runs ahead of the database
    with pytest.raises(OSError):
        updates.scope.remove("1", "pm")
    assert updates.scope.ids == frozenset({"1"})


# ---- the button flow -------------------------------------------------------------------------
class TextChannel(discord.TextChannel):
    """A real TextChannel type (the button checks for it) with the bits the flow reads."""

    def __init__(self, name, ident, can_post=True):
        self.name, self.id = name, ident
        self.guild = SimpleNamespace(default_role=object())
        self._can_post = can_post

    def permissions_for(self, member):
        return SimpleNamespace(view_channel=self._can_post, send_messages=self._can_post)


def guild_with(*channels):
    by_id = {c.id: c for c in channels}
    return SimpleNamespace(get_channel=by_id.get, me=SimpleNamespace())


def channel_press(updates, flow, **context):
    interaction = pi(**{k: v for k, v in context.items() if k != "guild"})
    interaction.guild = context.get("guild")
    run(flow(interaction))
    return interaction


def test_the_panel_has_the_other_channels_button(tmp_path):
    async def go():
        view = ku.PanelView(SimpleNamespace())
        labels = [b.label for b in view.children]
        assert "Gigi in other channels" in labels and len(labels) == 7
        assert len({b.custom_id for b in view.children}) == 7

    run(go())


def test_the_channel_screen_lists_what_is_on_and_offers_a_picker(tmp_path):
    updates, _, _ = build(tmp_path)
    first = channel_press(updates, updates.open_channels)
    sent = first.followup.send.await_args.kwargs
    assert sent["ephemeral"] is True and "None added yet" in sent["embed"].description
    assert "only when someone @mentions" in sent["embed"].description
    assert [type(c).__name__ for c in sent["view"].children] == ["ChannelSelect"]
    updates.scope.add("123", "help", "Rae (discord:9)")
    second = channel_press(updates, updates.open_channels)
    sent = second.followup.send.await_args.kwargs
    assert "<#123>" in sent["embed"].description and "Rae" in sent["embed"].description
    assert [type(c).__name__ for c in sent["view"].children] == ["ChannelSelect", "TurnOffSelect"]


def test_choosing_a_channel_asks_to_confirm_then_turns_gigi_on(tmp_path):
    updates, store, _ = build(tmp_path)
    help_channel = TextChannel("gab-help", 555)
    guild = guild_with(help_channel)
    picked = SimpleNamespace(id=555)
    asked = pi(guild=guild)
    run(updates.choose_channel(asked, picked))
    shown = asked.edit_original_response.await_args.kwargs
    assert "Turn Gigi on in #gab-help?" == shown["embed"].title
    assert (
        "@mentioning" in shown["embed"].description
        and "will not answer anything else" in shown["embed"].description
    )
    assert [b.label for b in shown["view"].children] == ["Turn on", "Cancel"]
    assert updates.scope.ids == frozenset()  # nothing yet

    turn_on = pi(guild=guild)
    run(shown["view"].children[0].callback(turn_on))
    assert updates.scope.ids == frozenset({"555"})
    done = turn_on.edit_original_response.await_args.kwargs
    assert "now answers in #gab-help when someone @mentions it" in done["content"]
    assert store.audit_log(1)[0]["actor"] == "Rae (discord:99)"

    cancel = pi(guild=guild)
    run(shown["view"].children[1].callback(cancel))  # Cancel goes back to the channel list
    assert (
        "Gigi in other channels" == cancel.edit_original_response.await_args.kwargs["embed"].title
    )


def test_unsuitable_channels_are_refused_with_a_reason(tmp_path):
    updates, _, _ = build(tmp_path)
    staff = TextChannel("gigi-updates", CHANNEL_ID_FOR_UPDATES)
    muted = TextChannel("locked", 556, can_post=False)
    voice = SimpleNamespace(id=557)  # not a text channel
    open_one = TextChannel("open", 558)
    updates.scope.add("558", "open", "pm")
    guild = guild_with(staff, muted, open_one)
    cases = (
        (SimpleNamespace(id=CHANNEL_ID_FOR_UPDATES), "this staff channel"),
        (SimpleNamespace(id=556), "cannot see or post in #locked"),
        (SimpleNamespace(id=557), "text channels"),
        (SimpleNamespace(id=558), "already answers in #open"),
        (SimpleNamespace(id=999), "text channels"),
    )
    for picked, expected in cases:
        interaction = pi(guild=guild)
        run(updates.choose_channel(interaction, picked))
        said = interaction.response.send_message.await_args
        assert expected in said.args[0] and said.kwargs["ephemeral"] is True, expected
    assert updates.scope.ids == frozenset({"558"})
    assert voice


CHANNEL_ID_FOR_UPDATES = 4242  # the id the shared Channel() fake uses for #gigi-updates


def test_gigi_can_be_turned_off_again_from_the_list(tmp_path):
    updates, _, _ = build(tmp_path)
    updates.scope.add("123", "help", "pm")
    interaction = pi()
    run(updates.disable_channel(interaction, "123"))
    assert updates.scope.ids == frozenset()
    kwargs = interaction.edit_original_response.await_args.kwargs
    assert "no longer answers in #help" in kwargs["content"]
    again = pi()
    run(updates.disable_channel(again, "123"))
    assert "Not done" in again.followup.send.await_args.args[0]


def test_every_other_channels_step_refuses_the_wrong_place_and_the_wrong_person(tmp_path):
    updates, store, _ = build(tmp_path, allowed_roles=("PM",))
    help_channel = TextChannel("gab-help", 555)
    guild = guild_with(help_channel)
    flows = {
        "open_channels": lambda i: updates.open_channels(i),
        "choose_channel": lambda i: updates.choose_channel(i, SimpleNamespace(id=555)),
        "enable_channel": lambda i: updates.enable_channel(i, "555", "gab-help"),
        "disable_channel": lambda i: updates.disable_channel(i, "555"),
    }
    contexts = (
        {"channel": Channel(name="general", ident=1), "user": Member(roles=["PM"])},
        {"channel": Channel(public=True), "user": Member(roles=["PM"])},
        {"user": Member(roles=["Annotator"])},
    )
    for name, flow in flows.items():
        for context in contexts:
            interaction = pi(guild=guild, **context)
            run(flow(interaction))
            interaction.response.send_message.assert_awaited_once()
            assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True, name
    assert updates.scope.ids == frozenset()
    assert store.get_support("answer-channels.json") is None
