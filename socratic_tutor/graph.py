"""LangGraph workflow definition for Socratic Tutor."""

from __future__ import annotations

import re
import uuid
from typing import Any
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command

from socratic_tutor import config
from socratic_tutor.state import SocraticState
from socratic_tutor.policy import check_input_guardrails, check_answer_leak
from socratic_tutor.concept_graph import ConceptGraph
from socratic_tutor.learner_store import LearnerStore
from socratic_tutor.reflexion import ReflexionPlaybook
from socratic_tutor.tools import textbook_kb, math_tools
from socratic_tutor.agents import diagnostician, tutor, grader, question_setter

REFUSAL = "I cannot fulfill this request as entered. Let's focus on our NCERT study goals."
_SECTION_RE = re.compile(r"(?<![\d.])(9|10|11)\.(\d{1,2})(?:\.(\d{1,2}))?(?![\d])")


def _extract_section_ids(*sources: Any) -> list[str]:
    """Extract standard NCERT section IDs (e.g. 9.2.4, 10.1, 11.6.2) from strings or lists."""
    found: list[str] = []
    for src in sources:
        if isinstance(src, (list, tuple, set)):
            for item in src:
                for match in _SECTION_RE.finditer(str(item)):
                    sec = ".".join(part for part in match.groups() if part)
                    if sec not in found:
                        found.append(sec)
        elif src:
            for match in _SECTION_RE.finditer(str(src)):
                sec = ".".join(part for part in match.groups() if part)
                if sec not in found:
                    found.append(sec)
    return found


# --- Node Definitions ---

def node_input_guardrail(state: SocraticState) -> dict:
    query = state.get("query", "")
    guard_res = check_input_guardrails(query)
    if not guard_res["passed"]:
        if guard_res.get("is_distress"):
            # Teacher Rule 4: Academic distress protocol
            # Supportive de-escalation, down-scale to a micro-step, raise silent teacher alert
            supportive_reply = (
                "It is completely normal to feel stuck or frustrated when studying physics. "
                "Let's take a deep breath and take this one small step at a time. "
                "What specific part or formula are you looking at right now?"
            )
            return {
                "steps": ["input_guardrail"],
                "query": guard_res["sanitized_query"],
                "injection_detected": False,
                "teacher_alert_triggered": True,
                "response": supportive_reply,
            }
        return {
            "steps": ["input_guardrail"],
            "query": guard_res["sanitized_query"],
            "injection_detected": True,
            "teacher_alert_triggered": False,
            "response": REFUSAL,
        }
    return {
        "steps": ["input_guardrail"],
        "query": guard_res["sanitized_query"],
        "injection_detected": False,
    }


def node_supervisor(state: SocraticState) -> dict:
    student_id = state.get("student_id", "")
    store = LearnerStore()
    profile = store.get_profile(student_id) if student_id else {"mastery_map": {}, "failure_streaks": {}, "stuck_counter": 0}

    mastery = dict(profile.get("mastery_map", {}))
    if state.get("mastery_map"):
        mastery.update(state["mastery_map"])

    cg = ConceptGraph()
    next_concept = cg.next_recommended(mastery)
    current_concept = state.get("current_concept_id") or next_concept

    # Teacher Rule 3: Flag stuck student after 3 consecutive failures
    failure_streaks = profile.get("failure_streaks", {})
    concept_failures = failure_streaks.get(current_concept or "", 0)
    stuck_counter = profile.get("stuck_counter", 0)
    stuck = (concept_failures >= 3) or (stuck_counter >= 3)
    teacher_alert = bool(stuck or state.get("teacher_alert_triggered", False))

    return {
        "steps": ["supervisor"],
        "mastery_map": mastery,
        "current_concept_id": current_concept,
        "next_recommended_concept": next_concept,
        "teacher_alert_triggered": teacher_alert,
    }


def node_diagnostician(state: SocraticState) -> dict:
    query = state.get("query", "")
    diag_res = diagnostician.diagnose_response(query)

    miscon_id = None
    miscon_name = None
    if isinstance(diag_res, dict):
        miscon_id = diag_res.get("identified_misconception_id") or diag_res.get("id")
        miscon_name = diag_res.get("identified_misconception_name") or diag_res.get("name")

    playbook = ReflexionPlaybook()
    effective_lesson = None
    if miscon_id:
        lessons = playbook.get_lessons_for_misconception(miscon_id)
        if lessons:
            effective_lesson = lessons[0]

    return {
        "steps": ["diagnostician"],
        "identified_misconception": {"id": miscon_id, "name": miscon_name} if miscon_id else None,
        "effective_lesson_applied": effective_lesson,
    }


def node_tutor(state: SocraticState) -> dict:
    query = state.get("query", "")
    passages = textbook_kb.search_textbook(query, top_k=4)

    initial_citations = []
    for p in passages:
        sec = p.get("section_id")
        if sec and sec not in initial_citations:
            initial_citations.append(sec)

    hint_step = state.get("hint_step", 1)

    # Teacher Rule 2: Parallel resistor remediation path
    remediation = None
    query_lower = query.lower()
    if "parallel" in query_lower and any(w in query_lower for w in ("resistor", "resistance", "current")):
        if state.get("teacher_alert_triggered") or hint_step >= 2:
            remediation = "parallel_resistors"

    lesson = state.get("effective_lesson_applied")
    hint = tutor.generate_hint(
        student_query=query,
        ncert_passages=passages,
        hint_level=hint_step,
        approved_lesson=lesson,
        remediation=remediation,
    )

    all_citations = _extract_section_ids(initial_citations, hint)

    return {
        "steps": ["tutor"],
        "response": hint,
        "citations": all_citations,
        "retrieved_sections": passages,
    }


def node_output_guardrail(state: SocraticState) -> dict:
    response = state.get("response", "")
    expected_answer = state.get("student_attempt") or None
    leak = check_answer_leak(response, expected_answer)

    # Socratic Invariant: If leak occurs in practice mode, replace with scaffolding prompt
    if leak and state.get("mode", "practice") == "practice":
        scaffold = (
            "Let's focus on the underlying physical principle rather than the final calculated value. "
            "What does the textbook rule say about how these quantities are related?"
        )
        return {
            "steps": ["output_guardrail"],
            "response": scaffold,
            "answer_leak_flag": True,
        }

    return {
        "steps": ["output_guardrail"],
        "response": response,
        "answer_leak_flag": False,
    }


def node_grader(state: SocraticState) -> dict:
    attempt = state.get("student_attempt") or state.get("query", "")
    gold_answer = state.get("gold_answer", "")

    is_numeric = bool(re.search(r"\d", gold_answer))
    res = grader.grade_answer(attempt, gold_answer, is_numeric=is_numeric)

    score = float(res.get("score", 0.0))
    student_id = state.get("student_id", "")
    concept_id = state.get("current_concept_id", "")

    alert_stuck = False
    if student_id and concept_id:
        store = LearnerStore()
        quiz_res = store.record_quiz_result(student_id, concept_id, score)
        alert_stuck = quiz_res.get("alert_stuck", False)

    feedback = res.get("feedback") or ("Correct! Well done." if res.get("is_correct") else "Not quite right. Let's review the concept.")

    return {
        "steps": ["grader"],
        "grade_result": res,
        "response": feedback,
        "teacher_alert_triggered": alert_stuck or state.get("teacher_alert_triggered", False),
    }


def node_question_setter(state: SocraticState) -> dict:
    concept = state.get("current_concept_id", "concept_reflection_laws")
    res = question_setter.select_question(concept)
    return {
        "steps": ["question_setter"],
        "teacher_approval_required": True,
        "teacher_approval_payload": {
            "set_id": f"set_{uuid.uuid4().hex[:8]}",
            "concept": concept,
            "prompt": res.get("question_text", "State the laws of reflection."),
            "gold_answer": res.get("gold_answer", "")
        }
    }


def node_teacher_approval_gate(state: SocraticState) -> dict:
    payload = state.get("teacher_approval_payload", {})
    decision = interrupt({"payload": payload, "prompt": "Approve new question for shared bank?"})
    approved = isinstance(decision, dict) and decision.get("action") == "approve"
    return {
        "steps": ["teacher_approval_gate"],
        "teacher_approval_required": False,
        "response": "Question approved and published." if approved else "Question proposal rejected."
    }


# --- Routing Functions ---

def route_guardrail(state: SocraticState) -> str:
    if state.get("injection_detected") or state.get("teacher_alert_triggered"):
        return END
    return "supervisor"


def route_mode(state: SocraticState) -> str:
    mode = state.get("mode", "practice")
    if mode == "quiz":
        return "grader"
    if state.get("teacher_approval_required"):
        return "question_setter"
    return "diagnostician"


# --- Graph Construction ---

def build_graph(checkpointer=None):
    workflow = StateGraph(SocraticState)

    workflow.add_node("input_guardrail", node_input_guardrail)
    workflow.add_node("supervisor", node_supervisor)
    workflow.add_node("diagnostician", node_diagnostician)
    workflow.add_node("tutor", node_tutor)
    workflow.add_node("output_guardrail", node_output_guardrail)
    workflow.add_node("grader", node_grader)
    workflow.add_node("question_setter", node_question_setter)
    workflow.add_node("teacher_approval_gate", node_teacher_approval_gate)

    workflow.add_edge(START, "input_guardrail")
    workflow.add_conditional_edges("input_guardrail", route_guardrail)
    workflow.add_conditional_edges("supervisor", route_mode)
    workflow.add_edge("diagnostician", "tutor")
    workflow.add_edge("tutor", "output_guardrail")
    workflow.add_edge("output_guardrail", END)
    workflow.add_edge("grader", END)
    workflow.add_edge("question_setter", "teacher_approval_gate")
    workflow.add_edge("teacher_approval_gate", END)

    return workflow.compile(checkpointer=checkpointer)
