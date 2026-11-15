"""Ask the real Qwen engine every paraphrased question in tests/eval/paraphrases.yaml and grade it.

    python scripts/run_live_eval.py --yes              # about 230 questions, about 7 minutes
    python scripts/run_live_eval.py --yes --limit 10   # a quick check that the key works

This SENDS approved FAQ excerpts and the test questions to Alibaba Cloud Model Studio and costs money
(about 1,700 input tokens a question). That is why it needs --yes, and why scripts/run_eval.py, the
routine check, is local-only. Requests are paced under Alibaba's account limit (60 requests and
100,000 tokens a minute). A throwaway quota database is used, so real user quotas are untouched.

Exits 1 if any off-topic question is answered from the FAQ, or the pass rate on answerable questions
is below --min-pass.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gab_faq.config import load_environment, load_settings  # noqa: E402
from gab_faq.engine import build_engine  # noqa: E402
from gab_faq.knowledge import KnowledgeBase  # noqa: E402
from gab_faq.model_limits import answer_as_user  # noqa: E402

TOKENS_PER_QUESTION = 1700  # measured: about 1,650 input and 11 output tokens


# Replies that publish no FAQ text or general guidance. The case files predate the "unrelated",
# "declined" and "clarification" outcomes, so these also count as safe for off-topic cases.
SAFE_FOR_NEGATIVES = frozenset(
    {"needs_human", "not_in_faq", "unrelated", "declined", "clarification", "small_talk"}
)


def passed(case: dict, answer) -> bool:
    if case.get("neg"):
        return answer.outcome in set(case["allow"]) | SAFE_FOR_NEGATIVES
    return answer.outcome == "answered" and bool(set(answer.sources or []) & set(case["ok"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="confirm sending FAQ text to Alibaba")
    parser.add_argument("--cases", default=str(ROOT / "tests" / "eval" / "paraphrases.yaml"))
    parser.add_argument("--limit", type=int, default=0, help="only the first N cases")
    parser.add_argument("--rpm", type=float, default=30, help="requests a minute (at most 55)")
    parser.add_argument("--min-pass", type=float, default=0.85)
    parser.add_argument("--report", default=str(ROOT / "live-eval-report.json"))
    args = parser.parse_args()

    cases = yaml.safe_load(Path(args.cases).read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[: args.limit]
    if not args.yes:
        print(
            f"This would send FAQ excerpts and {len(cases)} questions to Alibaba Cloud "
            f"(about {len(cases) * TOKENS_PER_QUESTION:,} input tokens). Re-run with --yes to do it."
        )
        return 2
    rpm = min(args.rpm, 55)

    load_environment()
    settings = load_settings()
    if not settings.dashscope_api_key_set:
        print("DASHSCOPE_API_KEY is not set (check .env).")
        return 2
    if not settings.external_questions_approved:
        # The engine would send nothing and hand every non-exact question to a person, so the
        # result would not measure Qwen at all. See docs/outbound-payload.md.
        print(
            "gab_faq.external_questions_approved is false: Qwen receives no questions, so a live "
            "evaluation would measure nothing. Approve outbound processing first."
        )
        return 2

    gate, last, interval = threading.Lock(), [0.0], 60.0 / rpm

    def paced() -> None:
        with gate:
            wait = last[0] + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            last[0] = time.monotonic()

    with TemporaryDirectory(prefix="gab-live-eval-") as state:
        settings = replace(settings, log_dir=Path(state))
        engine = build_engine(settings, KnowledgeBase(settings.knowledge_dir))

        def run(case):
            paced()
            started = time.monotonic()
            answer = answer_as_user(engine, f"eval:{case['id']}", case["q"], case["role"])
            return case, answer, time.monotonic() - started

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, cases))

    report, wrong_answers = [], []
    for case, answer, seconds in results:
        ok = passed(case, answer)
        report.append(
            {
                "id": case["id"],
                "question": case["q"],
                "role": case["role"],
                "negative": bool(case.get("neg")),
                "outcome": answer.outcome,
                "via": answer.via,
                "sources": answer.sources,
                "expected": case.get("ok") or case.get("allow"),
                "passed": ok,
                "seconds": round(seconds, 2),
            }
        )
        if not ok:
            print(f"[FAIL] {case['id']}: {case['q']}\n       -> {answer.outcome} {answer.sources}")
        if case.get("neg") and answer.outcome == "answered" and "answered" not in case["allow"]:
            wrong_answers.append(case["id"])
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")

    positives = [r for r in report if not r["negative"]]
    negatives = [r for r in report if r["negative"]]
    rate = sum(r["passed"] for r in positives) / max(1, len(positives))
    print(
        f"\nAnswerable questions correct: {sum(r['passed'] for r in positives)}/{len(positives)} "
        f"({rate:.0%}); off-topic handled safely: {sum(r['passed'] for r in negatives)}/{len(negatives)}"
    )
    print("How they were answered:", dict(Counter(r["via"] for r in report)))
    print("Answerable outcomes:", dict(Counter(r["outcome"] for r in positives)))
    print("Off-topic outcomes:", dict(Counter(r["outcome"] for r in negatives)))
    print(f"Report: {args.report}")
    if wrong_answers:
        print(f"Off-topic questions answered from the FAQ: {', '.join(wrong_answers)}")
        return 1
    if rate < args.min_pass:
        print(f"Pass rate below {args.min_pass:.0%}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
