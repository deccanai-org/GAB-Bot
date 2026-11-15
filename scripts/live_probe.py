"""Run answer-mode probe cases through the real production path (live Qwen) and save the results.

    python scripts/live_probe.py cases.json results.json --yes [--rpm 15]

This SENDS the case questions and approved FAQ excerpts to Alibaba Cloud Model Studio and costs
money, so it needs --yes. Use synthetic questions only, never real freelancer messages.

cases.json: a list of {"id", "category", "question", "role", "history"?: [{role, content}], ...};
extra keys (expectations, notes) are copied to the results untouched.

Each case goes through the same GuardedEngine as Discord: guard, per-user quota (a throwaway store,
one quota user per case), retrieval, Qwen and code-owned routing. Results include the reply as
Discord would show it, the outcome and routing, the provider requests and tokens the case used,
and, when a model reply was rejected, the rejection reason and the raw reply for debugging.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gab_faq.config import load_environment, load_settings  # noqa: E402
from gab_faq.engine import build_engine  # noqa: E402
from gab_faq.knowledge import KnowledgeBase  # noqa: E402
from gab_faq.model_limits import answer_as_user  # noqa: E402
from gab_faq.replies import format_reply  # noqa: E402


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument("results", type=Path)
    parser.add_argument("--yes", action="store_true", help="confirm sending questions to Alibaba")
    parser.add_argument("--rpm", type=float, default=15, help="questions a minute (at most 30)")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if not args.yes:
        print(f"This would send {len(cases)} questions to Alibaba. Re-run with --yes.")
        return 2
    load_environment()
    settings = load_settings()
    if not (settings.engine == "qwen" and settings.external_questions_approved):
        print("Qwen is not enabled for questions (engine/external_questions_approved).")
        return 2
    if not settings.dashscope_api_key_set:
        print("DASHSCOPE_API_KEY is not set.")
        return 2
    os.environ["GAB_LOG_MODEL_OUTPUT"] = "1"  # raw replies of REJECTED answers, this process only
    capture = Capture()
    logging.getLogger("gab_faq").addHandler(capture)
    interval = 60.0 / min(args.rpm, 30)
    results = []
    with TemporaryDirectory(prefix="gab-live-probe-") as state:
        usage = Path(state) / "provider.sqlite3"
        settings = replace(settings, log_dir=Path(state), provider_usage_path=usage)
        engine = build_engine(settings, KnowledgeBase(settings.knowledge_dir))
        last = 0.0
        for number, case in enumerate(cases, 1):
            wait = last + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()
            capture.messages.clear()
            with closing(sqlite3.connect(usage)) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS provider_attempts (id TEXT PRIMARY KEY, started REAL, reserved INTEGER, input_tokens INTEGER, output_tokens INTEGER, status TEXT)"
                )
                before = db.execute("SELECT COUNT(*) FROM provider_attempts").fetchone()[0]
            started = time.monotonic()
            answer = answer_as_user(
                engine,
                f"probe:{case['id']}",
                case["question"],
                case.get("role", "unknown"),
                case.get("history") or [],
            )
            seconds = time.monotonic() - started
            with closing(sqlite3.connect(usage)) as db:
                rows = db.execute(
                    "SELECT status, input_tokens, output_tokens FROM provider_attempts "
                    "ORDER BY rowid LIMIT -1 OFFSET ?",
                    (before,),
                ).fetchall()
            contact = settings.support.contact(answer.route) if answer.route else None
            rejected = [m for m in capture.messages if "rejected:" in m]
            raw = [m.split(": ", 1)[1] for m in capture.messages if "raw reply" in m]
            results.append(
                {
                    **case,
                    "result": {
                        "outcome": answer.outcome,
                        "reply": format_reply(
                            answer, "", settings.environment, support=settings.support
                        ),
                        "sources": answer.sources,
                        "via": answer.via,
                        "escalated": answer.needs_escalation,
                        "route": answer.route,
                        "route_hint": answer.route_hint,
                        "staff": contact.name if contact else "",
                        "staff_mention": contact.mention if contact else "",
                        "escalation_reason": answer.escalation_reason,
                        "provider_requests": len(rows),
                        "http_status": [r[0] for r in rows],
                        "input_tokens": sum(r[1] or 0 for r in rows),
                        "output_tokens": sum(r[2] or 0 for r in rows),
                        "rejected_reason": rejected,
                        "rejected_raw_reply": raw,
                        "seconds": round(seconds, 2),
                    },
                }
            )
            print(
                f"[{number}/{len(cases)}] {case['id']}: {answer.outcome} via {answer.via}"
                f" ({len(rows)} requests)",
                flush=True,
            )
            args.results.write_text(
                json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
            )
    print(f"Results: {args.results}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
