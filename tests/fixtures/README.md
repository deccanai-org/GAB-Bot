# Test fixtures

`knowledge-phase6/` is a frozen copy of the Phase 6.1/6.2 FAQ (`knowledge/current` as of
2026-11-16, before Phase 7). Tests of the answer engine's mechanics (retrieval, Qwen grounding,
video links, local search) run against it so they don't change every time the live FAQ moves to a
new phase. Tests of the *current* FAQ content live in `tests/test_knowledge.py` and read
`knowledge/current`.
