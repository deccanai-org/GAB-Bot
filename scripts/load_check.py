"""Credential-free local search load check for the configured single-instance budget."""

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gab_faq.config import load_settings
from gab_faq.engine import build_engine
from gab_faq.knowledge import KnowledgeBase


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-p95", type=float, default=5)
    args = parser.parse_args()
    if min(args.requests, args.workers, args.max_p95) <= 0:
        parser.error("All limits must be positive")
    settings = replace(load_settings(), engine="search")
    engine = build_engine(settings, KnowledgeBase(settings.knowledge_dir))
    if engine.inner.embedder is None:
        raise SystemExit("Load check requires the real embedding model")
    questions = [
        "which model do i pick for product A?",
        "should I record my whole screen?",
        "how long do I have before a task expires?",
        "what is on the QC checklist?",
    ]

    def run(index):
        started = time.monotonic()
        answer = engine.answer(questions[index % len(questions)], role="annotator")
        if not answer.text:
            raise RuntimeError("Empty search result")
        return time.monotonic() - started

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        durations = sorted(pool.map(run, range(args.requests)))
    p95 = durations[min(len(durations) - 1, int(len(durations) * 0.95))]
    print(
        json.dumps(
            {
                "requests": args.requests,
                "workers": args.workers,
                "p50_seconds": statistics.median(durations),
                "p95_seconds": p95,
                "total_seconds": time.monotonic() - started,
            }
        )
    )
    if p95 > args.max_p95:
        raise SystemExit("Search latency exceeded the acceptance budget")


if __name__ == "__main__":
    main()
