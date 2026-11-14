"""Contract tests for Socratic Tutor tools, solvers, and graph execution."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from socratic_tutor import config
from socratic_tutor.graph import build_graph
from socratic_tutor.tools import math_tools
from socratic_tutor.concept_graph import ConceptGraph
from socratic_tutor.learner_store import LearnerStore
from socratic_tutor.reflexion import ReflexionPlaybook


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
    # 14 since PR-2: the question setter's set waits on the approval gate's own thread, so the setter ends the run.
    assert len(g.edges) == 14

    mermaid = g.draw_mermaid()
    assert "question_setter --> __end__" in mermaid
    assert "teacher_approval_gate" not in mermaid
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
    # This message is SEVERE distress, so the student must get the guardrail's own reply, with the helpline,
    # not the generic "It is completely normal to feel stuck" text the graph used to put in its place.
    from socratic_tutor.policy import SEVERE_DISTRESS_REPLY
    assert t1_out["response"] == SEVERE_DISTRESS_REPLY
    assert t1_out["distress_level"] == "severe"

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


def test_node_tutor_passes_resolved_chapter_to_search_textbook(monkeypatch):
    """Verify that node_tutor resolves the student's chapter and passes it to search_textbook."""
    from socratic_tutor import graph

    search_calls = []

    def mock_search(query, chapter=None, top_k=4):
        search_calls.append({"query": query, "chapter": chapter, "top_k": top_k})
        return [{"section_id": "9.1", "title": "Reflection", "content": "Sample content"}]

    monkeypatch.setattr(graph.textbook_kb, "search_textbook", mock_search)
    monkeypatch.setattr(graph.tutor, "generate_hint", lambda **kwargs: "Look at the angle of incidence.")

    # 1. Resolved from concept_id (concept_reflection_laws is Chapter 9)
    state1 = {
        "session_id": "ses_test", "student_id": "stu_test", "mode": "practice",  # the facts R4's tool hooks need
        "query": "What is the law of reflection?",
        "current_concept_id": "concept_reflection_laws",
    }
    graph.node_tutor(state1)
    assert search_calls[-1]["chapter"] == "9"

    # 2. Direct from state["chapter"] = "11"
    state2 = {
        "session_id": "ses_test", "student_id": "stu_test", "mode": "practice",  # the facts R4's tool hooks need
        "query": "What is current?",
        "chapter": "11",
    }
    graph.node_tutor(state2)
    assert search_calls[-1]["chapter"] == "11"

    # 3. From identified_misconception
    state3 = {
        "session_id": "ses_test", "student_id": "stu_test", "mode": "practice",  # the facts R4's tool hooks need
        "query": "Why does eye lens change?",
        "identified_misconception": {"id": "M1", "chapter": "Human Eye and the Colourful World"},
    }
    graph.node_tutor(state3)
    assert search_calls[-1]["chapter"] == "10"

    # 4. A selected concept overrides a stale chapter left by the page that opened the tutor.
    state4 = {
        "session_id": "ses_test", "student_id": "stu_test", "mode": "practice",
        "query": "How does a concave lens correct short-sightedness?",
        "chapter": "9",
        "current_concept_id": "concept_myopia",
    }
    graph.node_tutor(state4)
    assert search_calls[-1]["chapter"] == "10"


def test_supervisor_selects_chapter_concept_when_unbound():
    """Verify starting in Chapter 10 without concept_id selects a Chapter 10 concept instead of Chapter 9 root."""
    from socratic_tutor import graph

    state = {
        "mode": "practice",
        "chapter": "10",
        "query": "Why is the sky blue?",
    }
    res = graph.node_supervisor(state)
    assert res["current_concept_id"] is not None
    cg = graph.ConceptGraph()
    assert cg.concepts[res["current_concept_id"]]["chapter"] == "Human Eye and the Colourful World"
    assert res["chapter"] == "10"


def test_supervisor_replaces_stale_chapter_for_pinned_concept():
    """Flashcard Ask Tutor keeps the selected concept and repairs the page's stale chapter context."""
    from socratic_tutor import graph

    res = graph.node_supervisor({
        "mode": "practice",
        "chapter": "9",
        "query": "How does a concave lens correct short-sightedness?",
        "current_concept_id": "concept_myopia",
        "concept_pinned": True,
        "detected_concept_id": "concept_myopia",
    })
    assert res["current_concept_id"] == "concept_myopia"
    assert res["chapter"] == "10"


def test_output_guard_repairs_visible_cross_chapter_citation():
    """A correct Chapter 10 retrieval replaces a hallucinated Chapter 9 citation in the visible reply."""
    from socratic_tutor import graph

    out = graph.node_output_guardrail({
        "mode": "practice",
        "query": "How does a concave lens correct myopia?",
        "current_concept_id": "concept_myopia",
        "response": "How might divergence move the focus? [NCERT Sec 9.3.5]",
        "citations": ["10.2", "9.3.5"],
        "retrieved_sections": [
            {"section_id": "10.2", "content": "A concave lens corrects myopia."},
            {"section_id": "9.3.5", "content": "Lens ray diagrams."},
        ],
    })
    assert "9.3.5" not in out["response"]
    assert "NCERT Sec 10.2" in out["response"]
    assert out["citations"] == ["10.2"]


def test_diagnostician_misconception_routes_chapter_and_citations(monkeypatch):
    """Verify an identified Chapter 10 misconception routes chapter resolution and citations to Chapter 10."""
    from socratic_tutor import graph

    state = {
        "mode": "practice",
        "query": "Why is the sky blue?",
        "turn_steps": ["input_guardrail", "supervisor", "diagnostician"],
        "plan": ["diagnose", "hint", "verify"],
        "identified_misconception": {
            "id": "MISCON_EYE_10",
            "name": "The sky is blue because the atmosphere is blue",
            "chapter": "Human Eye and the Colourful World",
        },
    }
    sup_res = graph.node_supervisor(state)
    assert sup_res["current_concept_id"] == "concept_scattering"

    searched = []

    def mock_search(query, chapter=None, top_k=4):
        searched.append({"query": query, "chapter": chapter})
        return [{"section_id": "10.6.2", "title": "Why is the colour of the clear sky blue?", "content": "Fine particles scatter blue light."}]

    monkeypatch.setattr(graph.textbook_kb, "search_textbook", mock_search)
    tutor_state = {
        "session_id": "ses_test",
        "student_id": "stu_test",
        "mode": "practice",
        "query": "Why is the sky blue?",
        "current_concept_id": sup_res["current_concept_id"],
        "identified_misconception": state["identified_misconception"],
    }
    tut_res = graph.node_tutor(tutor_state)
    assert searched[-1]["chapter"] == "10"
    assert any("10." in c for c in tut_res["citations"])



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


def test_n1_quiz_result_filed_under_question_concept(monkeypatch, tmp_path):
    """Verify quiz results are filed under the question's own concept, not student's current concept (N1)."""
    from socratic_tutor.tools import question_bank
    from socratic_tutor import graph

    db_path = tmp_path / "learner_n1.sqlite"
    store = LearnerStore(db_path)
    monkeypatch.setattr(graph, "LearnerStore", lambda *args, **kwargs: store)

    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "qb_n1.db")
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
        "session_id": "sess_n1",
        "student_id": "stu_n1",
        "mode": "quiz",
        "current_question_id": qid,
        "current_concept_id": "concept_reflection_laws",  # Different from question's concept!
        "query": "3 A",
        "student_attempt": "3 A",
        "messages": [],
        "steps": [],
    }
    output = app.invoke(state)
    assert output["grade_result"]["is_correct"] is True

    # Check store: attempt must be recorded under concept_ohms_law, not concept_reflection_laws
    profile = store.get_profile("stu_n1")
    assert "concept_ohms_law" in profile["mastery_map"]
    assert "concept_reflection_laws" not in profile["mastery_map"]

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT concept_id, score FROM quiz_attempts WHERE student_id = 'stu_n1'").fetchone()
        assert row[0] == "concept_ohms_law"
        assert row[1] == 1.0


def test_n2_mastered_decided_by_updated_mastery_not_single_score(monkeypatch, tmp_path):
    """Verify advancement depends on updated rolling mastery >= 0.70, not a single score >= 0.7 (N2)."""
    from socratic_tutor.tools import question_bank
    from socratic_tutor import graph

    db_path = tmp_path / "learner_n2.sqlite"
    store = LearnerStore(db_path)
    monkeypatch.setattr(graph, "LearnerStore", lambda *args, **kwargs: store)

    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "qb_n2.db")
    question_bank._init_db()

    prop = question_bank.propose_question(
        concept_id="concept_reflection_laws",
        difficulty="easy",
        prompt="State reflection law",
        gold_answer="equal",
    )
    qid = prop["question_id"]
    question_bank.publish_approved_question(qid)

    # Student has two prior failures: scores [0.0, 0.0]
    store.record_quiz_result("stu_n2", "concept_reflection_laws", 0.0)
    store.record_quiz_result("stu_n2", "concept_reflection_laws", 0.0)

    app = build_graph()

    # Attempt 3: student gets 0.8 (single attempt >= 0.7, but window is [0.0, 0.0, 0.8] -> mastery = 0.27)
    state = {
        "session_id": "sess_n2",
        "student_id": "stu_n2",
        "mode": "quiz",
        "current_question_id": qid,
        "current_concept_id": "concept_reflection_laws",
        "query": "equal",
        "student_attempt": "equal",
        "messages": [],
        "steps": [],
    }
    monkeypatch.setattr(graph.grader, "grade_answer", lambda *a, **kw: {"is_correct": True, "score": 0.8, "feedback": "Good"})

    output = app.invoke(state)
    assert output["grade_result"]["score"] == 0.8
    # Should NOT advance because mastery = 0.27 < 0.70
    assert output["current_concept_id"] == "concept_reflection_laws"

    # Now record high scores to bring rolling mastery >= 0.70
    store.record_quiz_result("stu_n2", "concept_reflection_laws", 1.0)
    # Window is now [0.0, 0.8, 1.0] -> 0.60. Next attempt in graph with 1.0 makes window [0.8, 1.0, 1.0] -> 0.93
    monkeypatch.setattr(graph.grader, "grade_answer", lambda *a, **kw: {"is_correct": True, "score": 1.0, "feedback": "Great"})
    output2 = app.invoke(state)
    # Now mastery >= 0.70, so student advances to the next concept
    assert output2["current_concept_id"] == "concept_spherical_mirrors"


def test_n3_unapproved_question_does_not_run_replan(monkeypatch, tmp_path):
    """Verify that an unavailable question does not trigger replan (N3)."""
    from socratic_tutor import graph

    db_path = tmp_path / "learner_n3.sqlite"
    store = LearnerStore(db_path)
    monkeypatch.setattr(graph, "LearnerStore", lambda *args, **kwargs: store)

    # Student has 3 failures on concept_spherical_mirrors
    store.record_quiz_result("stu_n3", "concept_spherical_mirrors", 0.0)
    store.record_quiz_result("stu_n3", "concept_spherical_mirrors", 0.0)
    store.record_quiz_result("stu_n3", "concept_spherical_mirrors", 0.0)

    app = build_graph()
    state = {
        "session_id": "sess_n3",
        "student_id": "stu_n3",
        "mode": "quiz",
        "current_question_id": "nonexistent_question",
        "current_concept_id": "concept_spherical_mirrors",
        "query": "something",
        "student_attempt": "something",
        "messages": [],
        "steps": [],
    }
    output = app.invoke(state)
    assert output["grade_result"]["error"] == "unapproved_question"
    assert output["plan"] == ["grade_error"]
    # Does not run replan / fallback
    assert output["current_concept_id"] == "concept_spherical_mirrors"


def test_n4_hint_step_at_most_raises_once_per_turn(monkeypatch, tmp_path):
    """Verify that stuck check and repeated misconception do not both increment hint_step in one turn (N4)."""
    from socratic_tutor import graph

    db_path = tmp_path / "learner_n4.sqlite"
    store = LearnerStore(db_path)
    monkeypatch.setattr(graph, "LearnerStore", lambda *args, **kwargs: store)

    # Mock diagnostician to return MISCON_LIGHT_01
    monkeypatch.setattr(
        graph.diagnostician,
        "diagnose_response",
        lambda *a, **kw: {"identified_misconception_id": "MISCON_LIGHT_01", "name": "Angle error", "chapter": "Light - Reflection and Refraction"},
    )
    monkeypatch.setattr(graph.tutor, "generate_hint", lambda **kw: "Check the normal line.")

    # Student is stuck: 3 failures
    store.record_quiz_result("stu_n4", "concept_reflection_laws", 0.0)
    store.record_quiz_result("stu_n4", "concept_reflection_laws", 0.0)
    store.record_quiz_result("stu_n4", "concept_reflection_laws", 0.0)

    app = build_graph()
    state = {
        "session_id": "sess_n4",
        "student_id": "stu_n4",
        "mode": "practice",
        "current_concept_id": "concept_reflection_laws",
        "last_concept_id": "concept_reflection_laws",
        "last_misconception_id": "MISCON_LIGHT_01",  # Same misconception as diagnostician returns!
        "query": "What is the angle?",
        "messages": [],
        "steps": [],
        "hint_step": 1,
    }
    output = app.invoke(state)
    # Both triggers fired (stuck + repeat misconception), but hint_step must only increase by 1 (1 -> 2, not 3)
    assert output["hint_step"] == 2


def test_diagnostician_stores_chapter_and_resolves_in_real_run(monkeypatch):
    """Verify node_diagnostician attaches chapter to identified_misconception so _resolve_chapter reaches branch 3."""
    from socratic_tutor import graph

    diag_output = graph.node_diagnostician({
        "query": "A ray strikes a plane mirror making 30° with the mirror surface.",
        "messages": [],
        "turn_steps": [],
    })
    miscon = diag_output["identified_misconception"]
    assert miscon is not None
    assert miscon.get("chapter") == "Light - Reflection and Refraction"

    resolved = graph._resolve_chapter({"identified_misconception": miscon})
    assert resolved == "9"


def test_node_tutor_rejects_cross_chapter_results_from_broad_fallback(monkeypatch):
    """The broad retry may run, but a Chapter 11 result cannot be cited for a Chapter 9 topic."""
    from socratic_tutor import graph

    calls = []

    def mock_search(query, chapter=None, top_k=4):
        calls.append({"query": query, "chapter": chapter})
        if chapter == "9":
            return []  # Filtered search finds nothing (e.g. cross-chapter question)
        return [{"section_id": "11.2", "title": "Ohm's Law", "content": "V = IR"}]

    monkeypatch.setattr(graph.textbook_kb, "search_textbook", mock_search)
    monkeypatch.setattr(graph.tutor, "generate_hint", lambda **kw: "Use Ohm's law.")

    state = {
        "session_id": "ses_test", "student_id": "stu_test", "mode": "practice",  # the facts R4's tool hooks need
        "query": "What is Ohm's law?",
        "current_concept_id": "concept_reflection_laws",  # Chapter 9
    }
    out = graph.node_tutor(state)
    assert len(calls) == 2
    assert calls[0]["chapter"] == "9"
    assert calls[1]["chapter"] is None
    assert "11.2" not in out["citations"]
    assert out["retrieved_sections"] == []


def test_reflexion_playbook_alignment_with_catalogue():
    """Verify all lessons in reflexion_playbook.json are aligned with data/misconceptions.json."""
    misconceptions_path = config.DATA_DIR / "misconceptions.json"
    with open(misconceptions_path, "r", encoding="utf-8") as f:
        catalog = json.load(f)
    catalog_ids = {m["id"] for m in catalog}

    playbook = ReflexionPlaybook()
    assert len(playbook.lessons) > 0

    for lesson in playbook.lessons:
        mid = lesson.get("misconception_id")
        assert mid in catalog_ids, f"Misconception {mid} not in catalog"

    # Specific assertions for the 4 corrected lessons
    elec_06 = [l for l in playbook.lessons if l.get("misconception_id") == "MISCON_ELEC_06"]
    assert elec_06, "Missing lesson for MISCON_ELEC_06"
    assert "series" in elec_06[0]["lesson"].lower() or "pipe" in elec_06[0]["lesson"].lower()

    elec_07 = [l for l in playbook.lessons if l.get("misconception_id") == "MISCON_ELEC_07"]
    assert elec_07, "Missing lesson for MISCON_ELEC_07"
    assert "parallel" in elec_07[0]["lesson"].lower() and "branch" in elec_07[0]["lesson"].lower()

    elec_08 = [l for l in playbook.lessons if l.get("misconception_id") == "MISCON_ELEC_08"]
    assert elec_08, "Missing lesson for MISCON_ELEC_08"
    assert "parallel" in elec_08[0]["lesson"].lower() and ("resistance" in elec_08[0]["lesson"].lower() or "lane" in elec_08[0]["lesson"].lower())

    eye_11 = [l for l in playbook.lessons if l.get("misconception_id") == "MISCON_EYE_11"]
    assert eye_11, "Missing lesson for MISCON_EYE_11"
    assert "myopia" in eye_11[0]["rationale"].lower() or "diverges" in eye_11[0]["lesson"].lower() or "retina" in eye_11[0]["lesson"].lower()


def test_quiz_attempt_recorded_exactly_once(monkeypatch, tmp_path):
    """Verify that a single quiz answer produces exactly one quiz_attempts entry and increments failure streak once."""
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
        "session_id": "sess_single_attempt",
        "student_id": "stu_single",
        "mode": "quiz",
        "current_question_id": qid,
        "current_concept_id": "concept_ohms_law",
        "query": "10 A",  # Incorrect answer
        "student_attempt": "10 A",
        "messages": [],
        "steps": [],
    }

    output = app.invoke(state)
    assert output["grade_result"]["is_correct"] is False

    # Check store: exactly ONE attempt record must exist in quiz_attempts
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM quiz_attempts WHERE student_id = 'stu_single'").fetchone()[0]
        assert count == 1, f"Expected exactly 1 quiz attempt row, found {count}"

    # Check failure streak is exactly 1, not 2
    profile = store.get_profile("stu_single")
    streak = profile["failure_streaks"].get("concept_ohms_law", 0)
    assert streak == 1, f"Expected failure streak of 1, got {streak}"


def test_hint_ladder_progression_across_multiturn_practice(monkeypatch):
    """Verify that an ordinary learner progresses through hint levels 1, 2, and 3 across turns."""
    from socratic_tutor import graph
    from langgraph.checkpoint.memory import MemorySaver

    hints_called = []

    def mock_generate_hint(**kwargs):
        lvl = kwargs.get("hint_level", 1)
        hints_called.append(lvl)
        return f"Hint Level {lvl} guidance (Refer to Section 9.2)"

    monkeypatch.setattr(graph.tutor, "generate_hint", mock_generate_hint)

    checkpointer = MemorySaver()
    app = graph.build_graph(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": "thread_hint_progression"}}

    # Turn 1: First attempt
    res1 = app.invoke({
        "mode": "practice",
        "query": "I am not sure where the ray reflects from the mirror.",
        "current_concept_id": "concept_reflection_laws",
        "messages": [HumanMessage(content="I am not sure where the ray reflects.")],
        "steps": [],
    }, config=cfg)
    assert res1["hint_step"] == 1
    assert hints_called[-1] == 1

    # Turn 2: Second attempt (continuing on same concept)
    res2 = app.invoke({
        "mode": "practice",
        "query": "Still confused about the angle.",
        "current_concept_id": "concept_reflection_laws",
        "messages": [HumanMessage(content="Still confused about the angle.")],
        "steps": [],
    }, config=cfg)
    assert res2["hint_step"] == 2
    assert hints_called[-1] == 2

    # Turn 3: Third attempt (continuing on same concept)
    res3 = app.invoke({
        "mode": "practice",
        "query": "Can you give me the formula or ray rule?",
        "current_concept_id": "concept_reflection_laws",
        "messages": [HumanMessage(content="Can you give me the formula or ray rule?")],
        "steps": [],
    }, config=cfg)
    assert res3["hint_step"] == 3
    assert hints_called[-1] == 3

    # Turn 4: Fourth attempt caps at MAX_HINT_STEPS (3)
    res4 = app.invoke({
        "mode": "practice",
        "query": "Need more help.",
        "current_concept_id": "concept_reflection_laws",
        "messages": [HumanMessage(content="Need more help.")],
        "steps": [],
    }, config=cfg)
    assert res4["hint_step"] == 3

    # Turn 5: Student moves to a new concept -> resets to Level 1
    res5 = app.invoke({
        "mode": "practice",
        "query": "Now how does Ohm's law work?",
        "current_concept_id": "concept_ohms_law",
        "messages": [HumanMessage(content="Now how does Ohm's law work?")],
        "steps": [],
    }, config=cfg)
    assert res5["hint_step"] == 1
    assert hints_called[-1] == 1


def test_output_guardrail_uses_question_gold_answer_not_student_attempt(monkeypatch, tmp_path):
    """Verify output guardrail compares against protected gold answer from question_bank, not student_attempt."""
    from socratic_tutor.tools import question_bank
    from socratic_tutor import graph

    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "qb_guard.db")
    question_bank._init_db()

    prop = question_bank.propose_question(
        concept_id="concept_ohms_law",
        difficulty="easy",
        prompt="12 V across 4 ohm: find current",
        gold_answer="3 A",
    )
    qid = prop["question_id"]
    question_bank.publish_approved_question(qid)

    # Case 1: Tutor response leaks the gold answer "3 A"
    state_leak = {
        "mode": "practice",
        "current_question_id": qid,
        "student_attempt": "100 A",  # Wrong student attempt
        "response": "The current is 3 A according to Ohm's law.",
        "citations": [],
        "retrieved_sections": [],
        "hint_tries": 0,
    }
    out_leak = graph.node_output_guardrail(state_leak)
    assert out_leak["answer_leak_flag"] is True

    # Case 2: Tutor response echoes student attempt "100 A" but does NOT leak gold answer "3 A"
    state_no_leak = {
        "mode": "practice",
        "current_question_id": qid,
        "student_attempt": "100 A",
        "response": "You suggested 100 A. Let's look at the relation between V and R.",
        "citations": [],
        "retrieved_sections": [],
        "hint_tries": 0,
    }
    out_no_leak = graph.node_output_guardrail(state_no_leak)
    assert out_no_leak["answer_leak_flag"] is False


def test_question_setter_structured_calculation() -> None:
    """The setter's structured calculation is computed by math-tools (PR-2: through solver_key, decision I2)."""
    from socratic_tutor import solver_key

    # Optics: the mirror formula, with #53's flat shape and short formula name.
    mirror: dict = solver_key.solve_answer_key(
        "An object is placed 30 cm in front of a concave mirror of focal length 15 cm.",
        {"formula": "mirror", "u": -30, "f": -15, "find": "v", "length_unit": "cm"},
    )
    assert mirror["ok"] is True
    assert mirror["gold_answer"] == "-30 cm"

    # Electricity: parallel resistance.
    parallel: dict = solver_key.solve_answer_key(
        "Two resistors of 4 ohm and 6 ohm in parallel.",
        {"formula": "parallel", "resistors": [4, 6]},
    )
    assert parallel["ok"] is True
    assert parallel["gold_answer"] == "2.4 ohm"


def test_parallel_resistors_with_battery_voltage_not_counted() -> None:
    """The 12 V battery is not a resistor: the solver uses the calculation's resistors, never numbers read off the text."""
    from socratic_tutor import solver_key

    prompt: str = "Two resistors of 4 ohm and 6 ohm are connected in parallel to a 12 V battery. Find the equivalent resistance."
    keyed: dict = solver_key.solve_answer_key(prompt, {"formula": "parallel_resistance", "values": {"resistors": [4, 6]}})
    assert keyed["ok"] is True
    assert keyed["gold_answer"] == "2.4 ohm"
    # Without a calculation there is no key at all (PR-2, P2-4): nothing is read off the text by a regex any more.
    made: dict = solver_key.draft_from_model_reply("concept_resistors_parallel", "easy", {"question_text": prompt})
    assert made["ok"] is False


def test_lens_power_calculation_no_typeerror() -> None:
    """Lens power goes through solve_optics with its real arguments: no TypeError, P = 1/f = 2 D."""
    from socratic_tutor import solver_key

    prompt: str = "A convex lens has a focal length of 0.5 m. Find its power."
    keyed: dict = solver_key.solve_answer_key(
        prompt, {"formula": "lens_power", "values": {"f": 0.5}, "length_unit": "m", "find": "p"}
    )
    assert keyed["ok"] is True
    assert keyed["gold_answer"] == "2 D"


def test_unmatched_conceptual_question_is_refused_not_proposed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A question the solver can't key (a text answer) is refused (PR-2, P2-4): nothing reaches the bank or the teacher."""
    from socratic_tutor import graph, solver_key
    from socratic_tutor.agents import question_setter
    from socratic_tutor.tools import question_bank, question_bank_server

    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "qb_unverified.db")
    question_bank._init_db()

    def known_concepts() -> list[str]:
        return ["concept_reflection_laws"]

    monkeypatch.setattr(question_bank_server, "load_concept_ids", known_concepts)

    prompt: str = "State the laws of reflection of light."
    raw_ans: str = "1. Angle of incidence equals angle of reflection. 2. Incident ray, normal, and reflected ray lie in same plane."
    text_reply: dict = {"concept_id": "concept_reflection_laws", "difficulty": "easy", "question_text": prompt, "gold_answer": raw_ans}

    # The solver itself refuses a text-only question: there is no calculation to key it with.
    made: dict = solver_key.draft_from_model_reply("concept_reflection_laws", "easy", text_reply)
    assert made["ok"] is False
    assert "without a calculation" in made["error"]

    # Through the graph node: the agent drops a reply without a calculation and, with no fallback question for
    # this concept, has nothing to offer. Nothing is saved, and the model's text key appears nowhere.
    def text_only_reply(*args: Any, **kwargs: Any) -> dict:
        return dict(text_reply)

    monkeypatch.setattr(graph.question_setter.llm, "chat_json", text_only_reply)
    monkeypatch.setattr(question_setter, "CONCEPT_FALLBACK_QUESTIONS", {})
    setter_state: dict = {"current_concept_id": "concept_reflection_laws", "turn_steps": [], "steps": []}
    setter_res: dict = graph.node_question_setter(setter_state)
    assert setter_res["proposed_set"]["ok"] is False
    assert len(setter_res["proposed_set"]["refused"]) == graph.QUESTION_SET_SIZE
    with sqlite3.connect(question_bank.DB_PATH) as connection:
        assert connection.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0
    assert raw_ans not in json.dumps(setter_res)


def test_parallel_resistors_fallback_split_into_two_single_value_questions() -> None:
    """Jilesh's fallback parallel questions are keyed by the solver as 2 ohm and 2 A, and grade as correct."""
    from socratic_tutor import solver_key
    from socratic_tutor.agents import question_setter, grader

    # Easy: equivalent resistance (2 ohm).
    q_easy: dict = question_setter.CONCEPT_FALLBACK_QUESTIONS["concept_resistors_parallel"][0]
    made_easy: dict = solver_key.draft_from_model_reply("concept_resistors_parallel", "easy", q_easy)
    assert made_easy["ok"] is True
    assert made_easy["draft"]["gold_answer"] == "2 ohm"
    assert grader.grade_answer("2 ohm", made_easy["draft"]["gold_answer"], is_numeric=True)["is_correct"] is True

    # Medium: branch current (2 A).
    q_med: dict = question_setter.CONCEPT_FALLBACK_QUESTIONS["concept_resistors_parallel"][1]
    made_med: dict = solver_key.draft_from_model_reply("concept_resistors_parallel", "medium", q_med)
    assert made_med["ok"] is True
    assert made_med["draft"]["gold_answer"] == "2 A"
    assert grader.grade_answer("2 A", made_med["draft"]["gold_answer"], is_numeric=True)["is_correct"] is True


def test_skip_proposing_when_no_question_or_fallback_for_concept(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The model fails and the concept has no fallback: nothing is proposed, and the run ends at the setter."""
    from socratic_tutor import graph
    from socratic_tutor.tools import question_bank, question_bank_server

    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "qb_skip.db")
    question_bank._init_db()

    def known_concepts() -> list[str]:
        return ["concept_non_existent_placeholder"]

    monkeypatch.setattr(question_bank_server, "load_concept_ids", known_concepts)

    def failed_call(*args: Any, **kwargs: Any) -> dict:
        return {"error": "LLM generation unavailable"}

    monkeypatch.setattr(graph.question_setter.llm, "chat_json", failed_call)

    state: dict = {"current_concept_id": "concept_non_existent_placeholder", "turn_steps": [], "steps": []}
    setter_out: dict = graph.node_question_setter(state)
    assert setter_out["teacher_approval_required"] is False
    assert setter_out["proposed_set"]["ok"] is False
    assert setter_out["proposed_set"]["set_id"] == ""
    # The graph has no gate node of its own any more: the setter ends the run.
    assert "teacher_approval_gate" not in build_graph().get_graph().nodes


# ---- Hint ladder and topic: the hint grows only when the student asks for more help; a new question can move topic ----

def _practice_app(monkeypatch, diagnose=None):
    from langgraph.checkpoint.memory import InMemorySaver
    from socratic_tutor import graph

    levels: list[int] = []

    def fake_hint(**kwargs):
        levels.append(kwargs.get("hint_level", 1))
        return f"Hint level {levels[-1]}: which way does the ray go after it reflects? (Section 9.2)"

    monkeypatch.setattr(graph.tutor, "generate_hint", fake_hint)
    monkeypatch.setattr(graph.diagnostician, "diagnose_response", diagnose or (lambda *a, **k: None))
    monkeypatch.setattr(graph.textbook_kb, "search_textbook", lambda *a, **k: [{"section_id": "9.2.1", "title": "Concave mirror", "content": "Rays reflect."}])
    return graph.build_graph(checkpointer=InMemorySaver())


def _turn(app, thread, message, **extra):
    from langchain_core.messages import HumanMessage

    state = {"session_id": "ses_ladder2", "student_id": "stu_ladder2", "mode": "practice", "query": message,
             "messages": [HumanMessage(content=message)], "steps": [], "concept_pinned": False}
    state.update(extra)
    return app.invoke(state, config={"configurable": {"thread_id": thread}})


def test_hint_grows_only_when_the_student_asks_for_more_help(monkeypatch):
    app = _practice_app(monkeypatch)
    first = _turn(app, "t_help", "Why is the image in a concave mirror upside down?",
                  current_concept_id="concept_concave_ray_diagrams", concept_pinned=True)
    assert first["hint_step"] == 1
    # Thanks, or the student's own explanation, keeps the level (Jilesh: "the hint increases without the student asking")
    assert _turn(app, "t_help", "Okay, thanks.")["hint_step"] == 1
    assert _turn(app, "t_help", "The focal length is negative and the image is virtual and upright.")["hint_step"] == 1
    # Asking for more help raises it, one step per turn, up to the biggest hint
    assert _turn(app, "t_help", "Can I have another hint?")["hint_step"] == 2
    assert _turn(app, "t_help", "Just tell me the answer please")["hint_step"] == 3
    assert _turn(app, "t_help", "Still confused")["hint_step"] == 3


def test_asks_for_more_help_phrases():
    from socratic_tutor.graph import asks_for_more_help

    for yes in ("Can I have another hint?", "I don't understand. Can you explain it differently?", "I’m done.",
                "Still confused about the angle.", "Need more help.", "just tell me the answer"):
        assert asks_for_more_help(yes), yes
    for no in ("Okay, thanks.", "Is it because the rays cross after reflecting?", "I think I've got it: the image is upright."):
        assert not asks_for_more_help(no), no


def test_a_new_question_in_another_chapter_moves_the_topic_unless_it_was_picked(monkeypatch):
    sky = {"id": "MISCON_EYE_10", "name": "The sky is blue because the atmosphere is blue", "chapter": "Human Eye and the Colourful World"}
    app = _practice_app(monkeypatch, diagnose=lambda q, *a, **k: sky if "sky" in q.lower() else None)
    _turn(app, "t_topic", "Why is the image in a concave mirror upside down?",
          current_concept_id="concept_concave_ray_diagrams", concept_pinned=True)
    _turn(app, "t_topic", "Can I have another hint?")
    moved = _turn(app, "t_topic", "Why is the sky blue?")
    assert moved["current_concept_id"] == "concept_scattering"
    assert moved["hint_step"] == 1  # a new topic starts at the smallest hint

    # A topic the student picked (Practise it) holds for that turn
    app2 = _practice_app(monkeypatch, diagnose=lambda q, *a, **k: sky)
    held = _turn(app2, "t_pick", "Help me practise concave mirrors. Why is the sky blue?",
                 current_concept_id="concept_concave_ray_diagrams", concept_pinned=True)
    assert held["current_concept_id"] == "concept_concave_ray_diagrams"


def test_picking_another_chapter_moves_the_carried_topic():
    from socratic_tutor import graph

    res = graph.node_supervisor({"mode": "practice", "chapter": "11", "concept_pinned": False,
                                 "current_concept_id": "concept_concave_ray_diagrams", "query": "Why does a heater wire get hot?"})
    cg = graph.ConceptGraph()
    assert cg.concepts[res["current_concept_id"]]["chapter"] == "Electricity"
