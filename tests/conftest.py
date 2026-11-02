"""Test setup: run offline and keep test output out of the real results folder."""

import os
import tempfile

os.environ.setdefault("EVAL_STUB", "1")
os.environ.setdefault("RESULTS_DIR", tempfile.mkdtemp(prefix="socratic-test-results-"))
os.environ.setdefault("TEACHER_PIN", "test-pin")
