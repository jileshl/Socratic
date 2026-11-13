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
    import subprocess
    import sys
    from pathlib import Path

    _repo_root = Path(__file__).resolve().parent.parent
    _real_index = _repo_root / ".index"
    if not (_real_index / "chunks.json").exists() and (_repo_root / "data").is_dir():
        subprocess.run([sys.executable, "-m", "scripts.build_index", "--force"], cwd=_repo_root, check=True)

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
