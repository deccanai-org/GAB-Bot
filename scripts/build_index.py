"""Precompute FAQ vectors during image creation; no provider credentials are used."""

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
        raise SystemExit("Cannot build FAQ index without the embedding model")
    print(f"Precomputed {len(engine.inner.entries)} approved FAQ vectors")


if __name__ == "__main__":
    main()
