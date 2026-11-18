"""Gigi command line. The Discord bot itself runs with `python bot.py`.

    gigi check                          config, FAQ files and Qwen readiness (no API calls, no cost)
    gigi ask "How do I reset before Product B?" --role annotator [--json]
    gigi chat --role qc                 interactive; earlier turns are used as thread context
    gigi ping                           one live Qwen request: key, endpoint and TLS (tiny cost)
    gigi slack                          run the Slack bot (needs SLACK_BOT_TOKEN and SLACK_APP_TOKEN)

`gigi` is installed by `pip install -e .` in the repository; `python -m gab_faq ...` is the same.
Questions go through exactly the same path as Discord (guard, per-user quota, retrieval, Qwen,
code-owned routing). The CLI's quota user is "cli:<name>"; --fresh-quota uses a throwaway quota
store so testing never uses a real person's allowance. Shared provider limits always apply.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from .config import CONFIG_PATH, load_environment, load_settings
from .engine import build_engine, describe
from .knowledge import KnowledgeBase, build_knowledge
from .knowledge_store import redact_location
from .model_limits import answer_as_user
from .replies import QuestionLog, format_reply
from .storage import configure_logging

ROLES = ("annotator", "qc", "qm", "unknown")
PING_QUESTION = "Explain the Gemini debug JSON requirements for Phase 6.1."


def qwen_status(settings) -> list[str]:
    if settings.engine != "qwen":
        return [f"  engine is {settings.engine!r}: no model calls"]
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    return [
        f"  model:                      {settings.model} (Alibaba Model Studio, Singapore)",
        f"  questions sent to Qwen:     {settings.external_questions_approved}"
        + ("" if settings.external_questions_approved else "  (off: GAB questions go to people)"),
        f"  thread history sent:        {settings.external_history_approved}",
        f"  thinking enabled:           {settings.enable_thinking}",
        f"  DASHSCOPE_API_KEY set:      {bool(key)}"
        + (f" (starts with sk-: {key.startswith('sk-')})" if key else ""),
        f"  budget:                     ~{settings.model_limits.max_input_tokens} input / "
        f"{settings.model_limits.max_output_tokens} output tokens, "
        f"{settings.model_limits.provider_calls_per_question} calls per question",
    ]


def check(settings, knowledge: KnowledgeBase) -> int:
    d, s = settings.discord, settings.slack
    print(
        f"FAQ answering enabled: {settings.enabled}   Environment: {settings.environment}   "
        f"Engine: {describe(settings)}"
    )
    if settings.knowledge_store:
        print(
            f"Knowledge database: {redact_location(settings.knowledge_store)} "
            f"(built-in fallback: {settings.knowledge_dir})"
        )
    print(f"FAQ files loaded from {knowledge.directory}:")
    for doc in knowledge.documents:
        print(
            f"  - {doc.path.name}: {doc.title} (audience={doc.audience}, phase={doc.phase}, updated={doc.updated})"
        )
    print(f"FAQ size: {len(knowledge.render()):,} characters")
    print("Qwen:")
    print("\n".join(qwen_status(settings)))
    print("Discord:")
    print(f"  only in:             {', '.join(sorted(d.only_in)) or 'anywhere'}")
    print(
        f"  answer channels:     {', '.join(sorted(d.answer_channels)) or 'none (only @mentions)'}"
    )
    print(f"  answers DMs:         {d.answer_in_dms}")
    print(
        f"  annotator / QC / QM channels: {sorted(d.annotator_channels)} / {sorted(d.qc_channels)} / {sorted(d.qm_channels)}"
    )
    print(f"  unanswered channel:  {d.unanswered_channel or 'none (log file only)'}")
    print("Staff routing (mentions built from stored IDs):")
    for category, contact in settings.support.contacts.items():
        print(f"  {category:18s} {contact.name:14s} {contact.mention or '(no ping)'}")
    print(
        f"Slack answer channels: {', '.join(sorted(s.answer_channels)) or 'none (only @mentions)'}"
    )
    print("Secrets set (values not shown):")
    print(f"  DASHSCOPE_API_KEY: {settings.dashscope_api_key_set}")
    print(f"  DISCORD_TOKEN:     {bool(settings.discord_token)}")
    print(f"  SLACK tokens:      {bool(settings.slack_bot_token and settings.slack_app_token)}")
    return 0


def result(settings, answer, seconds: float) -> dict:
    contact = settings.support.contact(answer.route) if answer.route else None
    return {
        "outcome": answer.outcome,
        "reply": format_reply(answer, "", settings.environment, support=settings.support),
        "sources": answer.sources,
        "via": answer.via,
        "escalated": answer.needs_escalation,
        "route": answer.route,
        "route_hint": answer.route_hint,
        "staff": contact.name if contact else "",
        "staff_mention": contact.mention if contact else "",
        "escalation_reason": answer.escalation_reason,
        "seconds": round(seconds, 2),
    }


def show(data: dict) -> None:
    print(f"\nbot> {data['reply']}")
    meta = f"outcome={data['outcome']} via={data['via']!r} sources={data['sources']}"
    if data["route"]:
        meta += f" staff={data['staff']} {data['staff_mention']}".rstrip()
    print(f"     [{meta} {data['seconds']}s]\n")


def answer_once(settings, brain, user, question, role, history):
    started = time.monotonic()
    answer = answer_as_user(brain, user, question, role, history)
    return answer, result(settings, answer, time.monotonic() - started)


def ask(settings, brain, args) -> int:
    history = []
    if args.history:
        history = json.loads(Path(args.history).read_text(encoding="utf-8"))
        if not isinstance(history, list):
            raise SystemExit("--history must be a JSON list of {role, content} messages")
    _, data = answer_once(settings, brain, args.user, args.question, args.role, history)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        show(data)
    return 0


def chat(settings, brain, args) -> int:
    print(f"Role: {args.role}. Ask a question; empty line or Ctrl+C to quit.\n")
    history: list[dict] = []
    while True:
        try:
            question = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not question:
            return 0
        answer, data = answer_once(settings, brain, args.user, question, args.role, history)
        show(data)
        history = (
            history
            + [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer.text},
            ]
        )[-4:]


def ping(settings, knowledge) -> int:
    """One real request through the production path, recorded in a throwaway usage store."""
    if settings.engine != "qwen":
        raise SystemExit("ping needs engine: qwen")
    if not settings.external_questions_approved:
        raise SystemExit("Qwen is off (external_questions_approved: false); nothing would be sent.")
    with tempfile.TemporaryDirectory(prefix="gigi-ping-") as state:
        usage = Path(state) / "provider.sqlite3"
        test = replace(settings, log_dir=Path(state), provider_usage_path=usage)
        brain = build_engine(test, knowledge)
        brain.inner.local_answers = False  # force a provider request
        started = time.monotonic()
        answer = answer_as_user(brain, "cli:ping", PING_QUESTION, "annotator")
        seconds = time.monotonic() - started
        with closing(sqlite3.connect(usage)) as db:
            rows = db.execute(
                "SELECT status, input_tokens, output_tokens FROM provider_attempts ORDER BY started"
            ).fetchall()
    statuses = [row[0] for row in rows]
    connected = "200" in statuses
    accepted = connected and answer.outcome not in {"error", "limited"}
    print(
        f"Connection to Qwen: {'OK' if connected else 'FAILED'}   requests: {len(rows)}   {seconds:.1f}s"
    )
    print(f"  HTTP status per request: {statuses or ['none sent']}")
    tokens = [(row[1], row[2]) for row in rows if row[1] is not None]
    if tokens:
        print(f"  tokens (input, output) reported by Alibaba: {tokens}")
    print(
        f"Reply passed validation: {'yes' if accepted else 'NO'} ({answer.outcome}, {answer.via})"
    )
    if answer.escalation_reason:
        print(f"  reason: {answer.escalation_reason}")
    if "401" in statuses or "403" in statuses:
        print("  The key was rejected: check DASHSCOPE_API_KEY (Singapore region key).")
    return 0 if accepted else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gigi", description="Gigi, the GAB FAQ assistant.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="check config, FAQ files and Qwen readiness (no API calls)")
    for name, text in (("ask", "ask one question"), ("chat", "interactive questions")):
        command = sub.add_parser(name, help=text)
        if name == "ask":
            command.add_argument("question")
            command.add_argument("--json", action="store_true", help="machine-readable output")
            command.add_argument("--history", help="JSON file with earlier {role, content} turns")
        command.add_argument("--role", choices=ROLES, default="unknown")
        command.add_argument(
            "--user", default=f"cli:{getpass.getuser()}", help="quota identity (default cli:you)"
        )
        command.add_argument(
            "--fresh-quota",
            action="store_true",
            help="use a throwaway per-user quota store (testing only)",
        )
    sub.add_parser("ping", help="one live Qwen request to verify key, endpoint and TLS")
    sub.add_parser("slack", help="run the Slack bot")
    args = parser.parse_args(argv)

    configure_logging()
    if not CONFIG_PATH.exists():
        raise SystemExit(
            f"{CONFIG_PATH} not found. Install the CLI from the repository with `pip install -e .`."
        )
    load_environment()
    settings = load_settings()
    knowledge = build_knowledge(settings)
    if args.command == "check":
        return check(settings, knowledge)
    if settings.engine == "qwen" and not settings.dashscope_api_key_set:
        raise SystemExit("Qwen requires DASHSCOPE_API_KEY in .env or deployment secrets.")
    if args.command == "ping":
        return ping(settings, knowledge)
    if args.command == "slack":
        from . import slack_app

        brain = build_engine(settings, knowledge)
        slack_app.run(
            settings, brain, QuestionLog(settings.log_dir, environment=settings.environment)
        )
        return 0
    with tempfile.TemporaryDirectory(prefix="gigi-quota-") as throwaway:
        if args.fresh_quota:
            settings = replace(settings, log_dir=Path(throwaway))
        brain = build_engine(settings, knowledge)
        return ask(settings, brain, args) if args.command == "ask" else chat(settings, brain, args)


if __name__ == "__main__":
    sys.exit(main())
