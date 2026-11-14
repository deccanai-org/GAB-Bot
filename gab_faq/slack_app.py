"""Slack connector. Uses Socket Mode, so it needs no public URL or open port: the bot opens a
connection out to Slack, which works from a laptop, a Jenkins agent or any server.

When the bot answers:
- someone @mentions it in any channel it has been added to;
- someone DMs it (if gab_faq.slack.answer_in_dms is on);
- any new message in one of gab_faq.slack.answer_channels (by channel ID), and follow-ups in a thread there
  as long as the bot was the last to reply (once a human jumps in, the bot stays quiet unless
  @mentioned again).
It always replies in a thread, so channels stay tidy.
"""

from __future__ import annotations

import logging
import re

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .config import Settings
from .contracts import AnswerEngine
from .model_limits import answer_as_user
from .redact import redact_secrets
from .replies import QuestionLog, format_reply
from .routing import classify, hint_for

log = logging.getLogger(__name__)

THINKING_REACTION = "eyes"
GREETING = (
    "Hi! I answer questions about the GAB project's FAQ: model selection, screen recording, debug JSON, "
    "turn counts, QC checks and so on. Just ask your question."
)


def clean_text(text: str, bot_user_id: str) -> str:
    return re.sub(rf"<@{re.escape(bot_user_id)}(\|[^>]*)?>", "", text or "").strip()


def is_plain_user_message(event: dict) -> bool:
    """True for a normal message written by a person (not an edit, join, bot post, etc.)."""
    return not event.get("subtype") and not event.get("bot_id") and bool(event.get("user"))


def message_route(
    event: dict, bot_user_id: str, answer_channels: frozenset[str], answer_in_dms: bool = False
) -> str | None:
    """Decide what to do with a `message` event.

    Returns "answer" (answer it), "thread_followup" (answer only if the bot spoke last in the
    thread), or None (ignore). @mentions in channels are ignored here because Slack sends them
    as a separate `app_mention` event, which has its own handler.
    """
    if not is_plain_user_message(event):
        return None
    is_dm = event.get("channel_type") == "im"
    if is_dm:
        return "answer" if answer_in_dms else None
    if f"<@{bot_user_id}" in (event.get("text") or ""):
        return None  # handled by app_mention
    if (event.get("channel") or "").lower() in answer_channels:
        is_thread_reply = event.get("thread_ts") and event.get("thread_ts") != event.get("ts")
        return "thread_followup" if is_thread_reply else "answer"
    return None


def to_history(
    messages: list[dict], bot_user_id: str, current_ts: str, asker: str | None = None
) -> list[dict]:
    """Earlier thread/DM messages as conversation turns. With `asker`, only the asker's and this
    bot's messages are kept (least privilege: other people's messages are never passed on)."""
    history = []
    for m in messages:
        if m.get("ts") == current_ts:
            continue
        # This bot's own messages carry its user ID (or, for some posts, only a bot_id).
        is_bot = m.get("user") == bot_user_id or (bool(m.get("bot_id")) and not m.get("user"))
        if not is_bot and m.get("bot_id"):
            continue  # another bot's or app's message
        if asker is not None and not is_bot and m.get("user") != asker:
            continue
        history.append(
            {
                "role": "assistant" if is_bot else "user",
                "content": clean_text(m.get("text", ""), bot_user_id),
            }
        )
    return history


def build_app(settings: Settings, brain: AnswerEngine, question_log: QuestionLog) -> App:
    app = App(token=settings.slack_bot_token)
    auth = app.client.auth_test()
    bot_user_id = auth["user_id"]
    workspace_id = auth.get("team_id", "workspace")
    log.info("Slack bot connected as user %s", bot_user_id)

    def thread_messages(client, channel: str, thread_ts: str) -> list[dict]:
        resp = client.conversations_replies(channel=channel, ts=thread_ts, limit=50)
        return resp.get("messages", [])

    def handle(event: dict, client, require_bot_last: bool = False) -> None:
        channel = event["channel"]
        ts = event["ts"]
        is_dm = event.get("channel_type") == "im"
        if not is_dm and not settings.slack.in_scope(channel):
            return  # outside gab_faq.slack.only_in
        thread_ts = event.get("thread_ts")
        question = clean_text(event.get("text", ""), bot_user_id)

        history: list[dict] = []
        if thread_ts:
            msgs = thread_messages(client, channel, thread_ts)
            earlier = [m for m in msgs if m.get("ts") != ts]
            if require_bot_last and (not earlier or earlier[-1].get("user") != bot_user_id):
                return  # a human is handling this thread
            history = to_history(earlier, bot_user_id, ts, asker=event.get("user"))
        elif is_dm:
            resp = client.conversations_history(
                channel=channel, latest=ts, inclusive=False, limit=settings.max_history_messages
            )
            history = to_history(
                list(reversed(resp.get("messages", []))), bot_user_id, ts, asker=event.get("user")
            )

        reply_thread = thread_ts or (None if is_dm else ts)
        if not question:
            client.chat_postMessage(channel=channel, thread_ts=reply_thread, text=GREETING)
            return

        try:
            client.reactions_add(channel=channel, timestamp=ts, name=THINKING_REACTION)
        except Exception:
            pass  # reactions are a nicety; never fail the answer because of them

        role = settings.slack.role_for_channel(channel)
        answer = answer_as_user(
            brain, f"slack:{workspace_id}:{event['user']}", question, role, history
        )
        if answer.needs_escalation and not answer.route:  # routing is always decided by code
            answer.route = classify(question, settings.support)
            answer.route_hint = hint_for(question)
        # Slack: the contact is named, never pinged (contact mentions in config are Discord IDs).
        text = format_reply(
            answer,
            settings.slack.escalation_mention,
            settings.environment,
            support=settings.support,
            mentions_allowed=False,
        )
        client.chat_postMessage(channel=channel, thread_ts=reply_thread, text=text)

        try:
            client.reactions_remove(channel=channel, timestamp=ts, name=THINKING_REACTION)
        except Exception:
            pass
        question_log.record(
            platform="slack",
            channel=channel,
            user=event.get("user", ""),
            role=role,
            question=redact_secrets(question),
            answer=answer,
        )

    @app.event("app_mention")
    def on_mention(event, client):
        if event.get("bot_id"):
            return
        handle(event, client)

    @app.event("message")
    def on_message(event, client):
        route = message_route(
            event, bot_user_id, settings.slack.answer_channels, settings.slack.answer_in_dms
        )
        if route == "answer":
            handle(event, client)
        elif route == "thread_followup":
            handle(event, client, require_bot_last=True)

    @app.error
    def on_error(error, body):
        log.exception("Slack handler error: %s", error)

    return app


def run(settings: Settings, brain: AnswerEngine, question_log: QuestionLog) -> None:
    if not settings.slack_bot_token or not settings.slack_app_token:
        raise SystemExit("SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set to run the Slack bot.")
    app = build_app(settings, brain, question_log)
    SocketModeHandler(app, settings.slack_app_token).start()
