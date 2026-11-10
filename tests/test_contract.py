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


def test_graph_draw_mermaid_shows_all_edges_and_supervisor_loop():
    """Verify that build_graph().get_graph().draw_mermaid() includes all edges with supervisor loops."""
    app = build_graph()
    g = app.get_graph()
    assert len(g.edges) == 15

    mermaid = g.draw_mermaid()
    assert "input_guardrail -.-> supervisor" in mermaid
    assert "input_guardrail -.-> __end__" in mermaid
    assert "supervisor -.-> grader" in mermaid
    assert "supervisor -.-> diagnostician" in mermaid
    assert "supervisor -.-> question_setter" in mermaid
    assert "supervisor -.-> tutor" in mermaid
    assert "diagnostician --> supervisor" in mermaid
    assert "grader --> supervisor" in mermaid
    assert "tutor --> supervisor" in mermaid
    assert "output_guardrail -.-> tutor" in mermaid
    assert "output_guardrail -.-> __end__" in mermaid


def test_graph_quiz_mode_uses_question_id_lookup(monkeypatch, tmp_path):
    """Verify end-to-end quiz turn routes to grader and looks up answer key via current_question_id."""
    from socratic_tutor.tools import question_bank

    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "qb.db")
    question_bank._init_db()

    proposed = question_bank.propose_question(
        concept_id="concept_ohms_law",
        difficulty="easy",
        prompt="12 V across 4 ohm: find current",
        gold_answer="3 A",
    )
    qid = proposed["question_id"]
    question_bank.publish_approved_question(qid)

    app = build_graph()
    state = {
        "session_id": "test_quiz_01",
        "student_id": "student_quiz_01",
        "mode": "quiz",
        "current_question_id": qid,
        "query": "3 A",
        "student_attempt": "3 A",
        "messages": [],
        "steps": [],
        "hint_step": 1,
    }
    output = app.invoke(state)
    assert "input_guardrail" in output["steps"]
    assert "supervisor" in output["steps"]
    assert "grader" in output["steps"]
    assert output["grade_result"]["is_correct"] is True
    assert output["grade_result"]["score"] == 1.0
    assert "gold_answer" not in output


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
    assert "supervisor" in output["steps"]
    assert "diagnostician" in output["steps"]
    assert "tutor" in output["steps"]
    assert "output_guardrail" in output["steps"]
    assert len(output.get("response", "")) > 0
    assert output.get("hint_tries") == 1
    assert "plan" in output


def test_graph_leak_retry_cycle(monkeypatch, tmp_path):
    """Verify that an answer leak in practice mode loops back to tutor for revision."""
    from socratic_tutor import graph
    from socratic_tutor.tools import question_bank

    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "qb_leak.db")
    question_bank._init_db()
    prop = question_bank.propose_question(
        concept_id="concept_mirror_formula",
        difficulty="medium",
        prompt="Where is the image formed?",
        gold_answer="-30 cm",
    )
    qid = prop["question_id"]
    question_bank.publish_approved_question(qid)

    tutor_calls = []

    def fake_generate_hint(*args, **kwargs):
        tutor_calls.append(len(tutor_calls) + 1)
        if len(tutor_calls) == 1:
            return "The image distance is exactly -30 cm (NCERT Section 9.2.4)."
        return "Think about the mirror formula relating u, v, and f (NCERT Section 9.2.4)."

    monkeypatch.setattr(graph.tutor, "generate_hint", fake_generate_hint)

    app = build_graph()
    state = {
        "session_id": "test_leak_01",
        "student_id": "student_leak_01",
        "mode": "practice",
        "current_question_id": qid,
        "query": "Where is the image formed?",
        "messages": [],
        "steps": [],
        "hint_step": 1,
    }
    output = app.invoke(state)
    assert len(tutor_calls) == 2
    assert output["hint_tries"] == 2
    assert "output_guardrail" in output["steps"]
    assert "Think about" in output["response"]
    assert output["answer_leak_flag"] is False


def test_two_practice_turns_run_diagnostician_both_times(monkeypatch):
    """Verify that the diagnostician runs on both turn 1 and turn 2 in a persistent thread (Bug 1)."""
    from langgraph.checkpoint.memory import InMemorySaver
    from socratic_tutor import graph

    diagnostician_calls = []

    def fake_diagnose(*args, **kwargs):
        diagnostician_calls.append(len(diagnostician_calls) + 1)
        return {"identified_misconception_id": "MISCON_LIGHT_01", "name": "Focal length confusion"}

    def fake_hint(*args, **kwargs):
        return "Consider the focal length and sign convention."

    monkeypatch.setattr(graph.diagnostician, "diagnose_response", fake_diagnose)
    monkeypatch.setattr(graph.tutor, "generate_hint", fake_hint)

    app = build_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "thread_multi_turn"}}

    # Turn 1
    t1_out = app.invoke({
        "session_id": "sess_multi",
        "student_id": "stu_multi",
        "mode": "practice",
        "query": "Why does the image invert?",
        "messages": [],
        "steps": [],
    }, config=cfg)
    assert len(diagnostician_calls) == 1
    assert "diagnostician" in t1_out["turn_steps"]

    # Turn 2 in the same thread
    t2_out = app.invoke({
        "session_id": "sess_multi",
        "student_id": "stu_multi",
        "mode": "practice",
        "query": "What about when object is inside focus?",
        "messages": [],
        "steps": [],
    }, config=cfg)
    assert len(diagnostician_calls) == 2
    assert "diagnostician" in t2_out["turn_steps"]


def test_grader_refuses_to_grade_unapproved_or_rejected_question(monkeypatch, tmp_path):
    """Verify grader rejects unapproved/pending questions and flags teacher alert (Bug 3)."""
    from socratic_tutor.tools import question_bank

    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "qb_unapproved.db")
    question_bank._init_db()

    prop = question_bank.propose_question(
        concept_id="concept_ohms_law",
        difficulty="easy",
        prompt="10 V across 2 ohm: find current",
        gold_answer="5 A",
    )
    qid = prop["question_id"]
    # Intentionally do not publish/approve qid

    app = build_graph()
    state = {
        "session_id": "test_unapproved_01",
        "student_id": "student_unapproved_01",
        "mode": "quiz",
        "current_question_id": qid,
        "query": "5 A",
        "student_attempt": "5 A",
        "messages": [],
        "steps": [],
    }
    output = app.invoke(state)
    assert "This question is not available yet" in output["response"]
    assert output["grade_result"]["error"] == "unapproved_question"
    assert output["teacher_alert_triggered"] is True


def test_quiz_attempt_recorded_exactly_once(monkeypatch, tmp_path):
    """Verify one quiz turn records exactly one attempt row in the learner store (Bug 4)."""
    from socratic_tutor.tools import question_bank
    from socratic_tutor import graph

    db_path = tmp_path / "learner_single.sqlite"
    store = LearnerStore(db_path)
    monkeypatch.setattr(graph, "LearnerStore", lambda *args, **kwargs: store)

    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "qb_single.db")
    question_bank._init_db()
    prop = question_bank.propose_question(
        concept_id="concept_ohms_law",
        difficulty="easy",
        prompt="12 V across 4 ohm: find current",
        gold_answer="3 A",
    )
    qid = prop["question_id"]
    question_bank.publish_approved_question(qid)

    app = build_graph()
    state = {
        "session_id": "sess_single_quiz",
        "student_id": "stu_single_quiz",
        "mode": "quiz",
        "current_question_id": qid,
        "query": "3 A",
        "student_attempt": "3 A",
        "messages": [],
        "steps": [],
    }
    output = app.invoke(state)
    profile = store.get_profile("stu_single_quiz")
    assert len(profile["quiz_history"]) == 1
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM quiz_attempts WHERE student_id = 'stu_single_quiz'").fetchone()[0]
    assert count == 1


def test_distress_turn_followed_by_normal_turn_reply_not_empty():
    """Verify academic distress turn followed by normal practice turn does not return empty reply (Bug 7)."""
    from langgraph.checkpoint.memory import InMemorySaver

    app = build_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "thread_distress_recovery"}}

    # Turn 1: Distress
    t1_out = app.invoke({
        "session_id": "sess_distress",
        "student_id": "stu_distress",
        "mode": "practice",
        "query": "I am so depressed and want to hurt myself",
        "messages": [],
        "steps": [],
    }, config=cfg)
    assert t1_out["teacher_alert_triggered"] is True
    assert t1_out["distress_detected"] is True
    assert "It is completely normal to feel stuck" in t1_out["response"]

    # Turn 2: Normal follow-up
    t2_out = app.invoke({
        "session_id": "sess_distress",
        "student_id": "stu_distress",
        "mode": "practice",
        "query": "Why is the image inverted?",
        "messages": [],
        "steps": [],
    }, config=cfg)
    assert t2_out["distress_detected"] is False
    assert len(t2_out["response"]) > 0
    assert "tutor" in t2_out["turn_steps"]


def test_replan_moves_student_to_next_concept(monkeypatch, tmp_path):
    """Verify replan updates current_concept_id when a concept is mastered (Bug 8)."""
    from socratic_tutor.tools import question_bank
    from socratic_tutor import graph

    db_path = tmp_path / "learner_replan.sqlite"
    store = LearnerStore(db_path)
    monkeypatch.setattr(graph, "LearnerStore", lambda *args, **kwargs: store)

    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "qb_replan.db")
    question_bank._init_db()
    prop = question_bank.propose_question(
        concept_id="concept_reflection_laws",
        difficulty="easy",
        prompt="Object distance is 10 cm, find image distance in plane mirror",
        gold_answer="10 cm",
    )
    qid = prop["question_id"]
    question_bank.publish_approved_question(qid)

    app = build_graph()
    state = {
        "session_id": "sess_replan",
        "student_id": "stu_replan",
        "mode": "quiz",
        "current_question_id": qid,
        "current_concept_id": "concept_reflection_laws",
        "query": "10 cm",
        "student_attempt": "10 cm",
        "messages": [],
        "steps": [],
    }
    output = app.invoke(state)
    assert output["grade_result"]["is_correct"] is True
    assert output["grade_result"]["score"] == 1.0
    # Next concept should advance past concept_reflection_laws
    assert output["current_concept_id"] != "concept_reflection_laws"
    assert output["current_concept_id"] == output["next_recommended_concept"]


def test_hint_ladder_progression_and_reset_on_concept_change(monkeypatch):
    """Verify hint ladder progresses 1 -> 2 -> 3 when same misconception recurs, then resets to 1 on new concept (Bug 6)."""
    from langgraph.checkpoint.memory import InMemorySaver
    from socratic_tutor import graph

    current_diag = {"identified_misconception_id": "MISCON_LIGHT_01", "name": "Focal length confusion"}

    def fake_diagnose(*args, **kwargs):
        return current_diag

    hints_received = []

    def fake_hint(*args, **kwargs):
        hints_received.append(kwargs.get("hint_level"))
        return f"Hint level {kwargs.get('hint_level')} content"

    monkeypatch.setattr(graph.diagnostician, "diagnose_response", fake_diagnose)
    monkeypatch.setattr(graph.tutor, "generate_hint", fake_hint)

    app = build_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "thread_ladder_test"}}

    # Turn 1: concept A, initial misconception -> hint level 1
    t1 = app.invoke({
        "session_id": "sess_ladder",
        "student_id": "stu_ladder",
        "mode": "practice",
        "current_concept_id": "concept_reflection_laws",
        "query": "Question 1 on reflection",
        "messages": [],
        "steps": [],
    }, config=cfg)
    assert t1["hint_step"] == 1
    assert hints_received[-1] == 1

    # Turn 2: same concept A, same misconception recurs -> hint level 2
    t2 = app.invoke({
        "session_id": "sess_ladder",
        "student_id": "stu_ladder",
        "mode": "practice",
        "current_concept_id": "concept_reflection_laws",
        "query": "Still confused on reflection",
        "messages": [],
        "steps": [],
    }, config=cfg)
    assert t2["hint_step"] == 2
    assert hints_received[-1] == 2

    # Turn 3: same concept A, same misconception recurs -> hint level 3
    t3 = app.invoke({
        "session_id": "sess_ladder",
        "student_id": "stu_ladder",
        "mode": "practice",
        "current_concept_id": "concept_reflection_laws",
        "query": "Still stuck on reflection",
        "messages": [],
        "steps": [],
    }, config=cfg)
    assert t3["hint_step"] == 3
    assert hints_received[-1] == 3

    # Turn 4: concept changes to concept_refraction_laws -> resets to 1
    current_diag = {"identified_misconception_id": "MISCON_OPTICS_02", "name": "Snell law confusion"}
    t4 = app.invoke({
        "session_id": "sess_ladder",
        "student_id": "stu_ladder",
        "mode": "practice",
        "current_concept_id": "concept_refraction_laws",
        "query": "Now starting refraction",
        "messages": [],
        "steps": [],
    }, config=cfg)
    assert t4["hint_step"] == 1
    assert hints_received[-1] == 1


def test_replan_falls_back_to_prerequisite_after_three_failures(monkeypatch, tmp_path):
    """Verify supervisor falls back to prerequisite concept after 3 consecutive failures (Bug 8)."""
    from socratic_tutor.tools import question_bank
    from socratic_tutor import graph

    db_path = tmp_path / "learner_fallback.sqlite"
    store = LearnerStore(db_path)
    monkeypatch.setattr(graph, "LearnerStore", lambda *args, **kwargs: store)

    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "qb_fallback.db")
    question_bank._init_db()
    prop = question_bank.propose_question(
        concept_id="concept_spherical_mirrors",
        difficulty="medium",
        prompt="Radius is 20 cm, find focal length",
        gold_answer="10 cm",
    )
    qid = prop["question_id"]
    question_bank.publish_approved_question(qid)

    app = build_graph()

    # Student fails twice first in store
    store.record_quiz_result("stu_fallback", "concept_spherical_mirrors", 0.0)
    store.record_quiz_result("stu_fallback", "concept_spherical_mirrors", 0.0)

    # 3rd failure through the graph
    state = {
        "session_id": "sess_fallback",
        "student_id": "stu_fallback",
        "mode": "quiz",
        "current_question_id": qid,
        "current_concept_id": "concept_spherical_mirrors",
        "query": "99 cm",
        "student_attempt": "99 cm",
        "messages": [],
        "steps": [],
    }
    output = app.invoke(state)
    assert output["grade_result"]["is_correct"] is False
    assert output["grade_result"]["score"] == 0.0
    # Prerequisite for concept_spherical_mirrors is concept_reflection_laws
    assert output["current_concept_id"] == "concept_reflection_laws"
    assert output["teacher_alert_triggered"] is True


def test_graph_leak_retry_max_tries_falls_back_to_scaffold(monkeypatch, tmp_path):
    """Verify that when tutor leaks repeatedly, graph uses scaffold after 2 attempts (Bug 2)."""
    from socratic_tutor import graph
    from socratic_tutor.tools import question_bank

    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "qb_leak_scaffold.db")
    question_bank._init_db()
    prop = question_bank.propose_question(
        concept_id="concept_mirror_formula",
        difficulty="medium",
        prompt="Where is the image formed?",
        gold_answer="-30 cm",
    )
    qid = prop["question_id"]
    question_bank.publish_approved_question(qid)

    tutor_calls = []

    def always_leaking_hint(*args, **kwargs):
        tutor_calls.append(len(tutor_calls) + 1)
        return "The answer is definitely -30 cm (NCERT Section 9.2.4)."

    monkeypatch.setattr(graph.tutor, "generate_hint", always_leaking_hint)

    app = build_graph()
    state = {
        "session_id": "test_leak_max",
        "student_id": "student_leak_max",
        "mode": "practice",
        "current_question_id": qid,
        "query": "Where is the image formed?",
        "messages": [],
        "steps": [],
        "hint_step": 1,
    }
    output = app.invoke(state)
    assert len(tutor_calls) == 2
    assert output["hint_tries"] == 2
    assert "Let's focus on the underlying physical principle" in output["response"]
    assert output["answer_leak_flag"] is True



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


def test_centralized_prompts_registry():
    from socratic_tutor import prompts
    from socratic_tutor.agents import diagnostician, tutor, grader, question_setter

    assert prompts.PROMPT_VERSION
    for role in ("diagnostician", "tutor", "grader", "question_setter"):
        prompt = prompts.get_prompt(role)
        assert isinstance(prompt, str) and len(prompt) > 20

    assert diagnostician.DIAGNOSTICIAN_PROMPT == prompts.DIAGNOSTICIAN_PROMPT
    assert tutor.TUTOR_PROMPT == prompts.TUTOR_PROMPT
    assert grader.GRADER_PROMPT == prompts.GRADER_PROMPT
    assert question_setter.QUESTION_SETTER_PROMPT == prompts.QUESTION_SETTER_PROMPT

