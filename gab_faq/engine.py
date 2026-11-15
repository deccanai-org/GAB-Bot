"""Build the guarded Qwen LLM or explicitly selected local retrieval."""

from __future__ import annotations

from .config import Settings
from .knowledge import KnowledgeBase
from .model_limits import ModelQuota


def build_engine(settings: Settings, knowledge: KnowledgeBase):
    """The configured engine, always wrapped in GuardedEngine (guard.py): the access restrictions and
    contact routing apply whichever engine selects the sources."""
    from .guard import GuardedEngine

    inner = _build_inner(settings, knowledge)
    return GuardedEngine(
        inner,
        settings.support,
        max_history_messages=settings.max_history_messages,
        quota=ModelQuota(settings.log_dir / "model_usage.sqlite3", settings.model_limits),
        limits=settings.model_limits,
    )


def _build_inner(settings: Settings, knowledge: KnowledgeBase):
    if settings.engine == "qwen":
        from .qwen import Qwen

        return Qwen(
            knowledge,
            model=settings.model,
            limits=settings.model_limits,
            max_history_messages=settings.max_history_messages,
        )
    if settings.engine != "search":
        raise ValueError("Unsupported answer engine")
    from .search import FaqSearch

    return FaqSearch(knowledge, settings.search)


def describe(settings: Settings) -> str:
    if settings.engine == "qwen":
        return "Alibaba Qwen3-Omni-Flash (Singapore, text only)"
    return f"Local FAQ search ({settings.search.model})"
