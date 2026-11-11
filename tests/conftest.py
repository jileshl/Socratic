"""Test setup: run offline and keep test output out of the real results folder."""

import os
import tempfile

os.environ.setdefault("EVAL_STUB", "1")
os.environ.setdefault("EVAL_RESULTS_DIR", tempfile.mkdtemp(prefix="socratic-test-results-"))
os.environ.setdefault("TEACHER_PIN", "test-pin")
# Tests write questions, approvals, learners and sessions. Keep them out of the app's real databases
# (they once showed up as "[TEST]" questions in the teacher's Recent decisions and the students' Quiz):
# point INDEX_DIR at a temporary folder, with a copy of the read-only search index if one is built.
if "INDEX_DIR" not in os.environ:
    import shutil
    from pathlib import Path

    _real_index = Path(__file__).resolve().parent.parent / ".index"
    _test_index = Path(tempfile.mkdtemp(prefix="socratic-test-index-"))
    for _name in ("chunks.json", "exemplars.json"):
        if (_real_index / _name).exists():
            shutil.copy2(_real_index / _name, _test_index / _name)
    if (_real_index / "chroma").is_dir():
        shutil.copytree(_real_index / "chroma", _test_index / "chroma")
    os.environ["INDEX_DIR"] = str(_test_index)
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
