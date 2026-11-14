"""Tools for the FAQ answering part. (The Discord bot itself runs with `python bot.py`.)

python -m gab_faq check   # check config.yaml and the FAQ files load (no API calls, no cost)
python -m gab_faq chat    # local FAQ lookup; no model API key
python -m gab_faq slack   # run the Slack bot (needs SLACK_BOT_TOKEN and SLACK_APP_TOKEN too)
"""

from __future__ import annotations

import argparse
import sys

from .config import load_environment, load_settings
from .engine import build_engine, describe
from .knowledge import KnowledgeBase
from .replies import QuestionLog, format_reply
from .storage import configure_logging


def chat(brain, environment: str) -> None:
    role = input("Your role? [a]nnotator / [q]c / [m] QM / [u]nknown: ").strip().lower()[:1]
    role = {"a": "annotator", "q": "qc", "m": "qm"}.get(role, "unknown")
    print(f"Role: {role}. Type a question (Ctrl+C to quit).\n")
    history: list[dict] = []
    while True:
        try:
            question = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not question:
            continue
        answer = brain.answer(question, role=role, history=history)
        print(f"\nbot> {format_reply(answer, '@escalation-contact', environment)}")
        print(
            f"     [outcome={answer.outcome} sources={answer.sources}"
            f"{' reason=' + answer.escalation_reason if answer.escalation_reason else ''}]\n"
        )
        history += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer.text},
        ]
        history = history[-4:]


def check(settings, knowledge: KnowledgeBase) -> int:
    d, s = settings.discord, settings.slack
    print(
        f"FAQ answering enabled: {settings.enabled}   Environment: {settings.environment}   "
        f"Engine: {describe(settings)}"
    )
    print(f"FAQ files loaded from {settings.knowledge_dir}:")
    for doc in knowledge.documents:
        print(
            f"  - {doc.path.name}: {doc.title} (audience={doc.audience}, phase={doc.phase}, updated={doc.updated})"
        )
    print(f"FAQ size: {len(knowledge.render()):,} characters")
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
    print(
        f"Slack answer channels: {', '.join(sorted(s.answer_channels)) or 'none (only @mentions)'}"
    )
    print("Secrets set (values not shown):")
    print(f"  DISCORD_TOKEN:     {bool(settings.discord_token)}")
    print(f"  SLACK tokens:      {bool(settings.slack_bot_token and settings.slack_app_token)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gab_faq")
    parser.add_argument("command", choices=["check", "chat", "slack"])
    args = parser.parse_args(argv)

    configure_logging()
    load_environment()
    settings = load_settings()
    knowledge = KnowledgeBase(settings.knowledge_dir)
    if args.command == "check":
        return check(settings, knowledge)

    brain = build_engine(settings, knowledge)
    if args.command == "chat":
        chat(brain, settings.environment)
    elif args.command == "slack":
        from . import slack_app

        slack_app.run(
            settings, brain, QuestionLog(settings.log_dir, environment=settings.environment)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
