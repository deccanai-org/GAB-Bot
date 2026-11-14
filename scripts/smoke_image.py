"""Offline image acceptance: load the baked model and answer without credentials."""

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gab_faq.config import load_settings
from gab_faq.engine import build_engine
from gab_faq.knowledge import KnowledgeBase


def main():
    settings = replace(load_settings(), engine="search")
    engine = build_engine(settings, KnowledgeBase(settings.knowledge_dir))
    if engine.inner.embedder is None:
        raise SystemExit("Image acceptance failed: baked embedding model unavailable")
    if not engine.inner.cache_loaded:
        raise SystemExit(
            "Image acceptance failed: precomputed FAQ index unavailable to runtime user"
        )
    answer = engine.answer("which model do i pick for product A?", role="annotator")
    if "Locust" not in answer.text or "A1" not in answer.sources:
        raise SystemExit("Image acceptance failed: representative FAQ lookup is incorrect")
    print("Offline image acceptance passed")


if __name__ == "__main__":
    main()
