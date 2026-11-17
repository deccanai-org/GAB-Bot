import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gab_faq.knowledge import KnowledgeBase  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_provider_accounting(tmp_path, monkeypatch):
    monkeypatch.setenv("GAB_PROVIDER_USAGE_PATH", str(tmp_path / "provider.sqlite3"))


# Engine-mechanics tests use a frozen copy of the Phase 6 FAQ (see tests/fixtures/README.md), so they
# don't change whenever the live FAQ moves to a new phase. Content tests use `current_knowledge`.
PHASE6_KNOWLEDGE = ROOT / "tests" / "fixtures" / "knowledge-phase6"
CURRENT_KNOWLEDGE = ROOT / "knowledge" / "current"


@pytest.fixture
def knowledge():
    return KnowledgeBase(PHASE6_KNOWLEDGE)


@pytest.fixture
def current_knowledge():
    return KnowledgeBase(CURRENT_KNOWLEDGE)
