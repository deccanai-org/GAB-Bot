"""Repeatable acceptance gates. Full mode requires real embeddings and zero skipped tests."""

from __future__ import annotations

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def command(*arguments):
    result = subprocess.run([sys.executable, *arguments], cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)


def fetch_model(model_name, cache_dir):
    """Download the embedding model into cache_dir if missing; a no-op when already cached.

    The bot itself only ever loads the model with local_files_only=True, and models/ is not in
    git, so a fresh checkout (CI) has to fetch the weights before the real-embedding gates run.
    """
    from fastembed import TextEmbedding

    try:
        TextEmbedding(model_name=model_name, cache_dir=str(cache_dir), threads=1)
    except Exception as error:
        raise SystemExit(f"Could not download embedding model {model_name}: {error}") from error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full",
        action="store_true",
        help="Download/cache the model, prohibit skips, and grade retrieval",
    )
    args = parser.parse_args()
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    command("-m", "ruff", "check", ".")
    command("-m", "ruff", "format", "--check", ".")
    if args.full:
        from dataclasses import replace

        from gab_faq.config import load_settings
        from gab_faq.engine import build_engine
        from gab_faq.knowledge import KnowledgeBase

        settings = replace(load_settings(), engine="search")
        fetch_model(settings.search.model, settings.search.cache_dir)
        engine = build_engine(settings, KnowledgeBase(settings.knowledge_dir))
        if engine.inner.embedder is None:
            raise SystemExit("Full acceptance requires the real embedding model")
    report = artifacts / "tests.xml"
    command(
        "-m",
        "pytest",
        "-q",
        f"--junitxml={report}",
        "--cov=gab_faq",
        "--cov-branch",
        "--cov-report=term:skip-covered",
        f"--cov-report=json:{artifacts / 'coverage.json'}",
    )
    if args.full:
        tree = ET.parse(report)
        skipped = list(tree.iter("skipped"))
        if skipped:
            raise SystemExit(f"Full acceptance failed: {len(skipped)} skipped tests")
        command("scripts/load_check.py")
        command(
            "scripts/run_eval.py",
            "--engine",
            "search",
            "--min-pass",
            "0.9",
            "--report",
            str(artifacts / "eval-report.json"),
        )
    print(
        "Acceptance gates passed"
        + (" (full model validation)" if args.full else " (unit checks only)")
    )


if __name__ == "__main__":
    main()
