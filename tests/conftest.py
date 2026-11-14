import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gab_faq.knowledge import KnowledgeBase  # noqa: E402


@pytest.fixture
def knowledge():
    return KnowledgeBase(ROOT / "knowledge" / "current")
