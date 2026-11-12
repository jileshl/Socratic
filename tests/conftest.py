"""Test setup: run offline and keep test output out of the real results folder."""

import os
import tempfile

os.environ.setdefault("EVAL_STUB", "1")
os.environ.setdefault("EVAL_RESULTS_DIR", tempfile.mkdtemp(prefix="socratic-test-results-"))
os.environ.setdefault("TEACHER_PIN", "test-pin")
# The guardrails' model calls (Llama Guard, the pasted-homework reader) never run in tests; tests that need them use fakes.
os.environ["GUARD_MODELS"] = "off"


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _offline_dense_search(monkeypatch):
    """Keep tests offline: the shared textbook retriever skips dense search.

    Dense search downloads an embedding model on first use. Retrieval tests that
    exercise dense search build their own HybridRetriever with a fake collection,
    so they are unaffected by this.
    """
    from socratic_tutor.tools import textbook_kb

    monkeypatch.setattr(textbook_kb.retriever, "search_dense", lambda query, top_k=5: [])


@pytest.fixture(autouse=True)
def _fresh_tool_budget():
    """Every test starts with fresh tool-hook counts (R4's per-turn budget).

    The counts live in one module-level dict, keyed by session id. Tests that call graph nodes directly never
    start a turn, so without this their tool calls would add up across the whole run, and after 20 of them
    every later test would see its tool calls blocked, depending on test order.
    """
    from socratic_tutor import tool_hooks

    # Empty the counts before the test (under the hooks' own lock, as start_turn does).
    with tool_hooks._COUNTS_LOCK:
        tool_hooks._TURN_COUNTS.clear()
    yield
