"""Contract tests for Socratic Tutor tools, solvers, and graph execution."""

import json
import sqlite3
from datetime import datetime, timezone

import pytest
from socratic_tutor.graph import build_graph
from socratic_tutor.tools import math_tools
from socratic_tutor.concept_graph import ConceptGraph
from socratic_tutor.learner_store import LearnerStore


class _MemoryCheckpointer:
    def __init__(self, thread_ids: set[str]):
        self.thread_ids = set(thread_ids)

    def delete_thread(self, thread_id: str) -> None:
        self.thread_ids.discard(thread_id)


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


def test_learner_store_records_mastery_misconceptions_lessons_and_quizzes(tmp_path):
    store = LearnerStore(tmp_path / "learner.sqlite")
    store.update_mastery("student-1", "concept-mirror", 0.8)
    store.record_misconception("student-1", "MISCON_LIGHT_01")
    store.record_misconception("student-1", "MISCON_LIGHT_01", resolved=True)
    store.record_effective_lesson("student-1", "LESSON_MIRROR_RAYS")

    first = store.record_quiz_result("student-1", "concept-mirror", 0.5)
    store.record_quiz_result("student-1", "concept-mirror", 0.6)
    third = store.record_quiz_result("student-1", "concept-mirror", 0.4)
    profile = store.get_profile("student-1")

    assert profile["mastery_map"]["concept-mirror"] == 0.5
    assert profile["misconceptions"][0]["id"] == "MISCON_LIGHT_01"
    assert profile["misconceptions"][0]["resolved"] is True
    assert profile["effective_lessons"] == ["LESSON_MIRROR_RAYS"]
    assert len(profile["quiz_history"]) == 3
    assert first["failure_streak"] == 1
    assert third["teacher_alert_triggered"] is True


def test_learner_store_validates_scores_and_flags_long_problem_time(tmp_path):
    store = LearnerStore(tmp_path / "learner.sqlite")

    with pytest.raises(ValueError):
        store.update_mastery("student-1", "concept-mirror", 1.1)
    with pytest.raises(ValueError):
        store.record_quiz_result("student-1", "concept-mirror", -0.1)
    with pytest.raises(ValueError):
        store.record_quiz_result("student-1", "concept-mirror", 0.5, -1)

    result = store.record_quiz_result(
        "student-1", "concept-mirror", 0.8, duration_seconds=601
    )
    assert result["teacher_alert_triggered"] is True
    assert result["failure_streak"] == 0


def test_mastery_is_rolling_average_of_last_three_quiz_scores(tmp_path):
    store = LearnerStore(tmp_path / "learner.sqlite")

    store.record_quiz_result("student-1", "concept-mirror", 0.9)
    store.record_quiz_result("student-1", "concept-mirror", 0.1)
    result = store.record_quiz_result("student-1", "concept-mirror", 0.9)

    assert result["mastery"] == 0.63
    assert store.get_profile("student-1")["mastery_map"]["concept-mirror"] == 0.63


def test_failure_streak_is_per_concept_and_resets_after_passing_result(tmp_path):
    store = LearnerStore(tmp_path / "learner.sqlite")

    store.record_quiz_result("student-1", "concept-mirror", 0.5)
    store.record_quiz_result("student-1", "concept-ohms", 0.4)
    second_mirror_failure = store.record_quiz_result("student-1", "concept-mirror", 0.6)
    assert second_mirror_failure["failure_streak"] == 2
    assert second_mirror_failure["teacher_alert_triggered"] is False

    third_mirror_failure = store.record_quiz_result("student-1", "concept-mirror", 0.6)
    assert third_mirror_failure["failure_streak"] == 3
    assert third_mirror_failure["teacher_alert_triggered"] is True

    passed = store.record_quiz_result("student-1", "concept-mirror", 0.9)
    assert passed["failure_streak"] == 0
    assert passed["teacher_alert_triggered"] is False


def test_forget_me_deletes_profile_quizzes_and_registered_checkpoints(tmp_path):
    store = LearnerStore(tmp_path / "learner.sqlite")
    store.update_mastery("student-1", "concept-mirror", 0.8)
    store.record_quiz_result("student-1", "concept-mirror", 0.8)
    store.register_session("student-1", "session-1")
    checkpointer = _MemoryCheckpointer({"session-1", "other-session"})

    result = store.forget_me("student-1", checkpointer)

    assert result == {
        "deleted": True,
        "profile_deleted": True,
        "checkpoints_deleted": 1,
    }
    assert checkpointer.thread_ids == {"other-session"}
    assert store.get_profile("student-1")["mastery_map"] == {}
    assert store.get_profile("student-1")["quiz_history"] == []


def test_forget_me_requires_checkpointer_for_registered_sessions(tmp_path):
    store = LearnerStore(tmp_path / "learner.sqlite")
    store.update_mastery("student-1", "concept-mirror", 0.8)
    store.register_session("student-1", "session-1")

    with pytest.raises(ValueError):
        store.forget_me("student-1")

    assert store.get_profile("student-1")["mastery_map"]["concept-mirror"] == 0.8


def test_purge_expired_profiles_removes_only_inactive_learners(tmp_path):
    store = LearnerStore(tmp_path / "learner.sqlite")
    store.update_mastery("expired", "concept-mirror", 0.4)
    store.update_mastery("active", "concept-mirror", 0.8)
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE learners SET updated_at = '2025-01-01 00:00:00' WHERE student_id = 'expired'")
        conn.execute("UPDATE learners SET updated_at = '2025-12-30 00:00:00' WHERE student_id = 'active'")

    purged = store.purge_expired_profiles(
        inactive_days=90,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert purged == 1
    assert store.get_profile("expired")["mastery_map"] == {}
    assert store.get_profile("active")["mastery_map"]["concept-mirror"] == 0.8


def test_purge_expired_profiles_removes_session_only_learner_threads(tmp_path):
    store = LearnerStore(tmp_path / "learner.sqlite")
    store.register_session("chat-only", "chat-thread")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE learners SET updated_at = '2025-01-01 00:00:00' WHERE student_id = 'chat-only'")
    checkpointer = _MemoryCheckpointer({"chat-thread"})

    purged = store.purge_expired_profiles(
        inactive_days=90,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
        checkpointer=checkpointer,
    )

    assert purged == 1
    assert checkpointer.thread_ids == set()
    assert store.get_profile("chat-only")["mastery_map"] == {}


def test_concept_graph_prerequisite_and_recommendation_rules(tmp_path):
    path = tmp_path / "concepts.json"
    path.write_text(json.dumps({
        "concepts": [
            {"id": "reflection", "prerequisites": []},
            {"id": "mirror-rays", "prerequisites": ["reflection"]},
        ]
    }))
    graph = ConceptGraph(path)

    assert graph.get_prerequisites("mirror-rays") == ["reflection"]
    assert graph.can_advance("mirror-rays", {"reflection": 0.7}) is True
    assert graph.can_advance("mirror-rays", {"reflection": 0.69}) is False
    assert graph.next_recommended({}) == "reflection"
    assert graph.next_recommended({"reflection": 0.8}) == "mirror-rays"
