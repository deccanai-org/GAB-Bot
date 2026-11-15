"""Local-only retrieval evaluation, separate from mock or live answer correctness."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gab_faq.knowledge import KnowledgeBase  # noqa: E402
from gab_faq.model_context import estimated_input_tokens, request_bytes  # noqa: E402
from gab_faq.qwen import Qwen  # noqa: E402
from gab_faq.retrieval import LocalRetriever, targeted_query  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "tests/eval/paraphrases.yaml")
    parser.add_argument(
        "--baseline", type=Path, default=ROOT / "artifacts/reliability-baseline.json"
    )
    parser.add_argument("--report", type=Path, default=ROOT / "docs/faq-retrieval-results.json")
    args = parser.parse_args()
    knowledge = KnowledgeBase(ROOT / "knowledge/current")
    model = Qwen(knowledge, quota_path=ROOT / "artifacts/local-eval-provider.sqlite3")
    retriever = LocalRetriever(knowledge)
    rows = []
    for case in yaml.safe_load(args.cases.read_text(encoding="utf-8")):
        question, role = case["q"], case.get("role", "unknown")
        evidence = retriever.retrieve(question, role)
        ids = [c.entry.id for c in evidence.candidates]
        second = retriever.retrieve(targeted_query(question), role)
        row = {
            "id": case["id"],
            "gold": case.get("ok", []),
            "negative": bool(case.get("neg")),
            "ranked_ids": ids,
            "second_local_ids": [c.entry.id for c in second.candidates],
        }
        try:
            request, entries = model.build_request(question, role)
            row.update(
                packed_ids=[e.id for e in entries],
                request_bytes=len(request_bytes(request)),
                estimated_input_tokens=estimated_input_tokens(request),
            )
        except ValueError as error:
            row.update(packed_ids=[], budget_or_evidence_error=type(error).__name__)
        rows.append(row)
    positive = [r for r in rows if r["gold"]]
    counts = [r["estimated_input_tokens"] for r in rows if "estimated_input_tokens" in r]
    summary = {
        "positive_cases": len(positive),
        "negative_cases": sum(r["negative"] for r in rows),
        "recall_at_1": sum(bool(set(r["gold"]) & set(r["ranked_ids"][:1])) for r in positive)
        / len(positive),
        "recall_at_6": sum(bool(set(r["gold"]) & set(r["ranked_ids"][:6])) for r in positive)
        / len(positive),
        "packed_recall": sum(bool(set(r["gold"]) & set(r["packed_ids"])) for r in positive)
        / len(positive),
        "two_local_queries_recall": sum(
            bool(set(r["gold"]) & set(r["ranked_ids"] + r["second_local_ids"])) for r in positive
        )
        / len(positive),
        "mean_packed_entries": statistics.mean(len(r["packed_ids"]) for r in rows),
        "mean_estimated_input_tokens": statistics.mean(counts) if counts else 0,
        "max_estimated_input_tokens": max(counts, default=0),
        "token_counts_are_estimates": True,
        "provider_calls": 0,
        "answer_correctness": "Not measured by retrieval recall; see mock regression results and existing local evaluation separately.",
    }
    report = {"summary": summary, "cases": rows}
    if args.baseline.exists():
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        gold = [r for r in baseline if r["gold"]]
        report["baseline"] = {
            "recall_at_1": sum(bool(set(r["gold"]) & set(r["top_ids"][:1])) for r in gold)
            / len(gold),
            "recall_at_6": sum(bool(set(r["gold"]) & set(r["top_ids"][:6])) for r in gold)
            / len(gold),
            "packed_recall": sum(bool(set(r["gold"]) & set(r["packed_ids"])) for r in gold)
            / len(gold),
            "mean_packed_entries": statistics.mean(len(r["packed_ids"]) for r in baseline),
        }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"after": summary, "before": report.get("baseline")}))


if __name__ == "__main__":
    main()
