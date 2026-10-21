"""Contract tests for Socratic Tutor tools, solvers, and graph execution."""

import pytest
from socratic_tutor.graph import build_graph
from socratic_tutor.tools import math_tools
from socratic_tutor.concept_graph import ConceptGraph
from socratic_tutor.learner_store import LearnerStore


def test_mirror_formula_solver():
    """Verify solver accuracy: u=-30, f=-15 -> v=-30, m=-1.0"""
    res = math_tools.solve_mirror_formula(u=-30.0, f=-15.0)
    assert "error" not in res
    assert res["v"] == -30.0
    assert res["m"] == -1.0
    assert res["nature"] == "real and inverted"


def test_mirror_formula_object_at_focus():
    """Object at focal point should yield infinity / error message."""
    res = math_tools.solve_mirror_formula(u=-15.0, f=-15.0)
    assert "error" in res


def test_graph_compilation():
    """Ensure LangGraph StateGraph compiles and initializes properly."""
    app = build_graph()
    assert app is not None


def test_graph_basic_invocation():
    """Verify basic practice invocation runs without crashing."""
    app = build_graph()
    state = {
        "session_id": "test_01",
        "student_id": "student_test_01",
        "mode": "practice",
        "query": "Why is the image in a concave mirror upside down?",
        "messages": [],
        "steps": [],
        "mastery_map": {},
        "hint_step": 1
    }
    output = app.invoke(state)
    assert "input_guardrail" in output["steps"]
    assert "tutor" in output["steps"]
    assert len(output.get("response", "")) > 0
