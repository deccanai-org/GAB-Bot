"""Build a guarded search or Claude source-selection engine. Claude (Anthropic) is the only AI provider."""

from __future__ import annotations

from .config import Settings
from .knowledge import KnowledgeBase


def build_engine(settings: Settings, knowledge: KnowledgeBase):
    """The configured engine, always wrapped in GuardedEngine (guard.py): the access restrictions and
    contact routing apply whichever engine selects the sources."""
    from .guard import GuardedEngine

    inner = _build_inner(settings, knowledge)
    return GuardedEngine(
        inner, settings.support, max_history_messages=settings.max_history_messages
    )


def _build_inner(settings: Settings, knowledge: KnowledgeBase):
    if settings.engine == "claude":
        from .brain import Brain

        return Brain(
            knowledge,
            model=settings.model,
            effort=settings.effort,
            max_history_messages=settings.max_history_messages,
        )
    from .search import FaqSearch

    return FaqSearch(knowledge, settings.search)


def describe(settings: Settings) -> str:
    if settings.engine == "claude":
        return f"Claude ({settings.model})"
    return f"FAQ search ({settings.search.model})"
