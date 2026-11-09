"""Test setup: run offline and keep test output out of the real results folder."""

import os
import tempfile

os.environ.setdefault("EVAL_STUB", "1")
os.environ.setdefault("EVAL_RESULTS_DIR", tempfile.mkdtemp(prefix="socratic-test-results-"))
os.environ.setdefault("TEACHER_PIN", "test-pin")


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
