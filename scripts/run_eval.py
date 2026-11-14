"""Ask the real bot every question in tests/eval/questions.yaml and grade the answers.

    python scripts/run_eval.py              # uses gab_faq.engine from config.yaml (search is free)
    python scripts/run_eval.py --engine search   # no AI, no API key
    python scripts/run_eval.py --engine claude   # needs ANTHROPIC_API_KEY
    python scripts/run_eval.py --min-pass 0.9

Exits with an error (so a script or CI step can stop on it) if any "critical" case fails or the pass rate is
below --min-pass. Writes eval-report.json with every question, answer and verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dataclasses import replace  # noqa: E402

from gab_faq.config import load_environment, load_settings  # noqa: E402
from gab_faq.engine import build_engine, describe  # noqa: E402
from gab_faq.knowledge import KnowledgeBase  # noqa: E402


def grade(case: dict, outcome: str, text: str) -> list[str]:
    problems = []
    low = text.lower()
    allowed = case.get("outcome", [outcome])
    if outcome == "partial":
        # FAQ search showed its closest entry and flagged the question for the team: fine where an
        # answer is expected (if the content is right) and where "not in the FAQ" is expected.
        outcome = "answered" if "answered" in allowed else "not_in_faq"
    if outcome not in allowed:
        problems.append(f"outcome {outcome!r} not in {case['outcome']}")
    for phrase in case.get("must_include", []):
        if str(phrase).lower() not in low:
            problems.append(f"missing {phrase!r}")
    any_of = case.get("must_include_any", [])
    if any_of and not any(str(p).lower() in low for p in any_of):
        problems.append(f"none of {any_of}")
    for phrase in case.get("must_not_include", []):
        if str(phrase).lower() in low:
            problems.append(f"contains forbidden {phrase!r}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(ROOT / "tests" / "eval" / "questions.yaml"))
    parser.add_argument("--min-pass", type=float, default=0.9)
    parser.add_argument("--report", default=str(ROOT / "eval-report.json"))
    parser.add_argument("--engine", choices=["search", "claude"], help="override gab_faq.engine")
    args = parser.parse_args()

    load_environment()  # reads ANTHROPIC_API_KEY from .env
    settings = load_settings()
    if args.engine:
        settings = replace(settings, engine=args.engine)
    print(f"Engine: {describe(settings)}")
    brain = build_engine(settings, KnowledgeBase(settings.knowledge_dir))
    cases = yaml.safe_load(Path(args.cases).read_text())

    def run(case):
        ans = brain.answer(case["question"], role=case.get("role", "unknown"))
        return case, ans, grade(case, ans.outcome, ans.text)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, cases))

    report, passed, critical_failures = [], 0, []
    for case, ans, problems in results:
        ok = not problems
        passed += ok
        if not ok and case.get("critical"):
            critical_failures.append(case["id"])
        mark = "PASS" if ok else ("FAIL (critical)" if case.get("critical") else "FAIL")
        print(f"[{mark}] {case['id']}: {case['question']}")
        if not ok:
            print(f"    problems: {'; '.join(problems)}")
            print(f"    bot said ({ans.outcome}): {ans.text[:300]}")
        report.append(
            {
                "id": case["id"],
                "role": case.get("role"),
                "question": case["question"],
                "answer": ans.text,
                "outcome": ans.outcome,
                "sources": ans.sources,
                "via": ans.via,
                "passed": ok,
                "problems": problems,
            }
        )

    flagged = sum(1 for _c, ans, _p in results if ans.needs_escalation)
    print(
        f"\nFlagged for the team: {flagged}/{len(cases)} "
        f"({sum(1 for _c, a, _p in results if a.outcome == 'partial')} shown as 'not sure')"
    )
    rate = passed / len(cases)
    Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n{passed}/{len(cases)} passed ({rate:.0%}). Report: {args.report}")
    if critical_failures:
        print(f"Critical failures: {', '.join(critical_failures)}")
        return 1
    if rate < args.min_pass:
        print(f"Pass rate below {args.min_pass:.0%}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
