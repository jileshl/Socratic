"""Contract tests for Socratic Tutor tools, solvers, and graph execution."""

import pytest
from socratic_tutor.graph import build_graph
from socratic_tutor.tools import math_tools
from socratic_tutor.concept_graph import ConceptGraph
from socratic_tutor.learner_store import LearnerStore


def test_mirror_formula_solver():
    """Verify solver accuracy: u=-30, f=-15 -> v=-30, m=-1.0 (real and inverted).

    Updated for the shared result shape: v, m and the nature now come from three calls.
    """
    res = math_tools.solve_mirror_formula("cm", u=-30.0, f=-15.0)
    assert "error" not in res
    assert res["solved_for"] == "v"
    assert res["value"] == pytest.approx(-30.0)
    mag = math_tools.solve_mirror_magnification("cm", v=res["value"], u=-30.0)
    assert mag["value"] == pytest.approx(-1.0)
    nature = math_tools.describe_image(mag["value"])
    assert nature["value"].startswith("real and inverted")


def test_mirror_formula_object_at_focus():
    """Object at focal point should yield infinity / error message."""
    res = math_tools.solve_mirror_formula("cm", u=-15.0, f=-15.0)
    assert "error" in res
    assert "infinity" in res["error"]


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
