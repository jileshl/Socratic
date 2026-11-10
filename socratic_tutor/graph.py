"""LangGraph workflow definition for Socratic Tutor."""

from __future__ import annotations

import re
import uuid
from typing import Any
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langchain_core.messages import AnyMessage, AIMessage, HumanMessage

from socratic_tutor import config
from socratic_tutor.state import SocraticState
from socratic_tutor.policy import check_input_guardrails, check_answer_leak
from socratic_tutor.concept_graph import ConceptGraph
from socratic_tutor.learner_store import LearnerStore
from socratic_tutor.reflexion import ReflexionPlaybook
from socratic_tutor.tools import textbook_kb, math_tools, question_bank
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


CHAPTER_TITLE_TO_NUM: dict[str, str] = {
    "Light - Reflection and Refraction": "9",
    "Human Eye and the Colourful World": "10",
    "Electricity": "11",
}


def _resolve_chapter(state: SocraticState) -> str | None:
    """Resolve NCERT chapter number (e.g. '9', '10', '11') from state or active concept."""
    # 1. Direct from state if specified
    raw_chapter = state.get("chapter")
    if raw_chapter is not None:
        ch_str = str(raw_chapter).strip()
        if ch_str in CHAPTER_TITLE_TO_NUM:
            return CHAPTER_TITLE_TO_NUM[ch_str]
        m = re.search(r"\b(9|10|11)\b", ch_str)
        if m:
            return m.group(1)

    # 2. From active concept in ConceptGraph
    concept_id = state.get("current_concept_id")
    if concept_id:
        cg = ConceptGraph()
        concept = cg.concepts.get(concept_id, {})
        ch_title = concept.get("chapter")
        if ch_title in CHAPTER_TITLE_TO_NUM:
            return CHAPTER_TITLE_TO_NUM[ch_title]
        if ch_title:
            m = re.search(r"\b(9|10|11)\b", str(ch_title))
            if m:
                return m.group(1)

    # 3. From identified misconception
    miscon = state.get("identified_misconception")
    if isinstance(miscon, dict):
        ch_title = miscon.get("chapter")
        if ch_title in CHAPTER_TITLE_TO_NUM:
            return CHAPTER_TITLE_TO_NUM[ch_title]
        if ch_title:
            m = re.search(r"\b(9|10|11)\b", str(ch_title))
            if m:
                return m.group(1)

    return None


# --- Node Definitions ---

def node_input_guardrail(state: SocraticState) -> dict:
    query = state.get("query", "")
    guard_res = check_input_guardrails(query)

    # Reset per-turn fields at the start of each turn
    reset_state: dict[str, Any] = {
        "steps": ["input_guardrail"],
        "turn_steps": ["input_guardrail"],
        "query": guard_res["sanitized_query"],
        "response": "",
        "citations": [],
        "retrieved_sections": [],
        "identified_misconception": None,
        "effective_lesson_applied": None,
        "grade_result": None,
        "answer_leak_flag": False,
        "hint_tries": 0,
        "plan": [],
        "distress_detected": False,
        "teacher_alert_triggered": False,
    }

    if not guard_res["passed"]:
        if guard_res.get("is_distress"):
            # Teacher Rule 4: Academic distress protocol
            # Supportive de-escalation, down-scale to a micro-step, raise silent teacher alert
            supportive_reply = (
                "It is completely normal to feel stuck or frustrated when studying physics. "
                "Let's take a deep breath and take this one small step at a time. "
                "What specific part or formula are you looking at right now?"
            )
            reset_state.update({
                "injection_detected": False,
                "distress_detected": True,
                "teacher_alert_triggered": True,
                "response": supportive_reply,
            })
            return reset_state

        reset_state.update({
            "injection_detected": True,
            "distress_detected": False,
            "teacher_alert_triggered": False,
            "response": REFUSAL,
        })
        return reset_state

    reset_state.update({
        "injection_detected": False,
        "distress_detected": False,
    })
    return reset_state


def node_supervisor(state: SocraticState) -> dict:
    student_id = state.get("student_id", "")
    session_id = state.get("session_id", "")
    store = LearnerStore()

    if student_id and session_id and not session_id.startswith("eval-") and not student_id.startswith("RT-"):
        try:
            store.register_session(student_id, session_id)
        except Exception:
            pass

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

    mode = state.get("mode", "practice")
    plan = state.get("plan", [])
    turn_steps = state.get("turn_steps", [])

    hint_step = state.get("hint_step", 1)
    last_concept = state.get("last_concept_id")
    if last_concept and current_concept and last_concept != current_concept:
        hint_step = 1

    # Hint progression: adjust once per turn at start of practice turn if stuck
    if mode == "practice" and not plan:
        if stuck and hint_step < config.MAX_HINT_STEPS:
            hint_step = min(hint_step + 1, config.MAX_HINT_STEPS)

    # Quiz Mode:
    if mode == "quiz":
        grade_res = state.get("grade_result")
        if grade_res is None:
            return {
                "steps": ["supervisor"],
                "turn_steps": turn_steps + ["supervisor"],
                "plan": ["grade", "replan"],
                "mastery_map": mastery,
                "current_concept_id": current_concept,
                "next_recommended_concept": next_concept,
                "teacher_alert_triggered": teacher_alert,
                "hint_step": hint_step,
            }
        else:
            # Grader finished! Supervisor saves quiz result and replans
            score = float(grade_res.get("score", 0.0))
            if student_id and current_concept and not grade_res.get("error"):
                quiz_res = store.record_quiz_result(student_id, current_concept, score)
                if quiz_res.get("teacher_alert_triggered"):
                    teacher_alert = True
                updated_profile = store.get_profile(student_id)
                mastery = dict(updated_profile.get("mastery_map", {}))
                failure_streaks = updated_profile.get("failure_streaks", {})
                concept_failures = failure_streaks.get(current_concept or "", 0)

            if score >= 0.7:
                next_concept = cg.next_recommended(mastery)
                current_concept = next_concept
                hint_step = 1
            elif concept_failures >= 3:
                prereqs = cg.get_prerequisites(current_concept)
                if prereqs:
                    next_concept = prereqs[0]
                    current_concept = next_concept
                    hint_step = 1

            return {
                "steps": ["supervisor"],
                "turn_steps": turn_steps + ["supervisor"],
                "plan": ["graded", "replanned"],
                "mastery_map": mastery,
                "current_concept_id": current_concept,
                "next_recommended_concept": next_concept,
                "teacher_alert_triggered": teacher_alert,
                "hint_step": hint_step,
                "last_concept_id": current_concept,
            }

    # Question Setter Mode:
    if state.get("teacher_approval_required"):
        return {
            "steps": ["supervisor"],
            "turn_steps": turn_steps + ["supervisor"],
            "plan": ["propose_question", "teacher_gate"],
            "mastery_map": mastery,
            "current_concept_id": current_concept,
            "next_recommended_concept": next_concept,
            "teacher_alert_triggered": teacher_alert,
            "hint_step": hint_step,
        }

    # Practice Mode:
    # 1. Has tutor produced a hint?
    if state.get("response") and ("tutor" in turn_steps or "hint" in plan):
        return {
            "steps": ["supervisor"],
            "turn_steps": turn_steps + ["supervisor"],
            "plan": ["verify"],
            "mastery_map": mastery,
            "current_concept_id": current_concept,
            "next_recommended_concept": next_concept,
            "teacher_alert_triggered": teacher_alert,
            "hint_step": hint_step,
            "last_concept_id": current_concept,
            "last_misconception_id": state.get("last_misconception_id"),
        }

    # 2. Has diagnostician produced a result?
    if "diagnostician" in turn_steps or "diagnose" in plan:
        diag = state.get("identified_misconception")
        miscon_id = diag.get("id") if (diag and isinstance(diag, dict)) else None
        last_miscon = state.get("last_misconception_id")

        # Raise hint ladder when the same concept and misconception returned (last hint didn't help)
        if miscon_id and last_miscon and miscon_id == last_miscon and last_concept == current_concept:
            if hint_step < config.MAX_HINT_STEPS:
                hint_step = min(hint_step + 1, config.MAX_HINT_STEPS)

        if miscon_id:
            if student_id:
                try:
                    store.record_misconception(student_id, miscon_id)
                except Exception:
                    pass
            new_plan = ["misconception_addressed", "hint", "verify"]
        else:
            # Replan when no misconception is found (contradicts initial hypothesis)
            new_plan = ["hint", "verify"]

        return {
            "steps": ["supervisor"],
            "turn_steps": turn_steps + ["supervisor"],
            "plan": new_plan,
            "mastery_map": mastery,
            "current_concept_id": current_concept,
            "next_recommended_concept": next_concept,
            "teacher_alert_triggered": teacher_alert,
            "hint_step": hint_step,
            "last_concept_id": current_concept,
            "last_misconception_id": miscon_id or last_miscon,
        }

    # First pass in practice mode:
    return {
        "steps": ["supervisor"],
        "turn_steps": turn_steps + ["supervisor"],
        "plan": ["diagnose", "hint", "verify"],
        "mastery_map": mastery,
        "current_concept_id": current_concept,
        "next_recommended_concept": next_concept,
        "teacher_alert_triggered": teacher_alert,
        "hint_step": hint_step,
        "last_concept_id": current_concept,
    }


def node_diagnostician(state: SocraticState) -> dict:
    query = state.get("query", "")
    messages = state.get("messages", [])

    # Formulate contextual query using short-term conversational dialogue if available
    contextual_query = query
    if messages and len(messages) > 1:
        history_lines = [
            f"{'Student' if getattr(m, 'type', '') == 'human' else 'Tutor'}: {getattr(m, 'content', str(m))}"
            for m in messages[-4:]
            if getattr(m, 'content', None)
        ]
        if history_lines:
            contextual_query = "\n".join(history_lines)

    diag_res = diagnostician.diagnose_response(contextual_query)
    if not isinstance(diag_res, dict) or not (diag_res.get("identified_misconception_id") or diag_res.get("id")):
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
        "turn_steps": state.get("turn_steps", []) + ["diagnostician"],
        "identified_misconception": {"id": miscon_id, "name": miscon_name} if miscon_id else None,
        "effective_lesson_applied": effective_lesson,
    }


def node_tutor(state: SocraticState) -> dict:
    query = state.get("query", "")
    hint_tries = state.get("hint_tries", 0) + 1
    chapter = _resolve_chapter(state)
    passages = state.get("retrieved_sections") or textbook_kb.search_textbook(query, chapter=chapter, top_k=4)

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
        misconception=state.get("identified_misconception"),
        conversation_history=state.get("messages", []),
    )

    all_citations = _extract_section_ids(initial_citations, hint)

    return {
        "steps": ["tutor"],
        "turn_steps": state.get("turn_steps", []) + ["tutor"],
        "response": hint,
        "citations": all_citations,
        "retrieved_sections": passages,
        "hint_tries": hint_tries,
        "answer_leak_flag": False,
        "messages": [AIMessage(content=hint)],
    }


def node_output_guardrail(state: SocraticState) -> dict:
    response = state.get("response", "")
    expected_answer = None
    qid = state.get("current_question_id")
    if qid:
        q = question_bank.get_approved_question(qid)
        if q:
            expected_answer = q.get("gold_answer")

    leak = check_answer_leak(response, expected_answer)

    # Validate citations against retrieved sections (checking grounded in NCERT)
    retrieved = state.get("retrieved_sections", [])
    valid_secs = {str(p.get("section_id")) for p in retrieved if p.get("section_id")}
    citations = state.get("citations", [])
    validated_citations = [c for c in citations if not valid_secs or c in valid_secs]

    # Socratic Invariant: If leak occurs in practice mode
    if leak and state.get("mode", "practice") == "practice":
        hint_tries = state.get("hint_tries", 0)
        if hint_tries >= 2:
            scaffold = (
                "Let's focus on the underlying physical principle rather than the final calculated value. "
                "What does the textbook rule say about how these quantities are related?"
            )
            return {
                "steps": ["output_guardrail"],
                "turn_steps": state.get("turn_steps", []) + ["output_guardrail"],
                "response": scaffold,
                "citations": validated_citations,
                "answer_leak_flag": True,
            }
        return {
            "steps": ["output_guardrail"],
            "turn_steps": state.get("turn_steps", []) + ["output_guardrail"],
            "response": "",
            "citations": validated_citations,
            "answer_leak_flag": True,
        }

    return {
        "steps": ["output_guardrail"],
        "turn_steps": state.get("turn_steps", []) + ["output_guardrail"],
        "response": response,
        "citations": validated_citations,
        "answer_leak_flag": False,
    }


def node_grader(state: SocraticState) -> dict:
    attempt = state.get("student_attempt") or state.get("query", "")
    concept_id = state.get("current_concept_id", "")
    qid = state.get("current_question_id")

    q = question_bank.get_approved_question(qid) if qid else None
    if not q:
        feedback = "This question is not available yet."
        return {
            "steps": ["grader"],
            "turn_steps": state.get("turn_steps", []) + ["grader"],
            "grade_result": {"is_correct": False, "score": 0.0, "feedback": feedback, "error": "unapproved_question"},
            "response": feedback,
            "current_concept_id": concept_id or state.get("current_concept_id"),
            "teacher_alert_triggered": True,
        }

    gold_answer = q.get("gold_answer", "")
    if not concept_id and q.get("concept_id"):
        concept_id = q.get("concept_id")

    is_numeric = bool(re.search(r"\d", gold_answer))
    res = grader.grade_answer(attempt, gold_answer, is_numeric=is_numeric)

    feedback = res.get("feedback") or ("Correct! Well done." if res.get("is_correct") else "Not quite right. Let's review the concept.")

    return {
        "steps": ["grader"],
        "turn_steps": state.get("turn_steps", []) + ["grader"],
        "grade_result": res,
        "response": feedback,
        "current_concept_id": concept_id or state.get("current_concept_id"),
    }


def node_question_setter(state: SocraticState) -> dict:
    concept = state.get("current_concept_id", "concept_reflection_laws")
    res = question_setter.select_question(concept)
    return {
        "steps": ["question_setter"],
        "turn_steps": state.get("turn_steps", []) + ["question_setter"],
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
        "turn_steps": state.get("turn_steps", []) + ["teacher_approval_gate"],
        "teacher_approval_required": False,
        "response": "Question approved and published." if approved else "Question proposal rejected."
    }


# --- Routing Functions ---

def route_guardrail(state: SocraticState) -> str:
    if state.get("injection_detected") or state.get("distress_detected"):
        return END
    return "supervisor"


def route_supervisor(state: SocraticState) -> str:
    mode = state.get("mode", "practice")

    if mode == "quiz":
        if state.get("grade_result") is None:
            return "grader"
        return "output_guardrail"

    if state.get("teacher_approval_required"):
        return "question_setter"

    # Practice mode
    turn_steps = state.get("turn_steps", [])
    plan = state.get("plan", [])
    if "diagnostician" not in turn_steps and ("diagnose" in plan or not state.get("identified_misconception")):
        return "diagnostician"

    if "tutor" not in turn_steps or not state.get("response"):
        return "tutor"

    return "output_guardrail"


route_mode = route_supervisor  # Backward-compatibility alias


def route_output(state: SocraticState) -> str:
    if state.get("answer_leak_flag") and state.get("hint_tries", 0) < 2 and state.get("mode", "practice") == "practice":
        return "tutor"
    return END


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
    workflow.add_conditional_edges(
        "input_guardrail",
        route_guardrail,
        {"supervisor": "supervisor", END: END},
    )
    workflow.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {
            "diagnostician": "diagnostician",
            "tutor": "tutor",
            "grader": "grader",
            "question_setter": "question_setter",
            "output_guardrail": "output_guardrail",
        },
    )
    workflow.add_edge("diagnostician", "supervisor")
    workflow.add_edge("tutor", "supervisor")
    workflow.add_edge("grader", "supervisor")
    workflow.add_edge("question_setter", "teacher_approval_gate")
    workflow.add_edge("teacher_approval_gate", END)
    workflow.add_conditional_edges(
        "output_guardrail",
        route_output,
        {"tutor": "tutor", END: END},
    )

    return workflow.compile(checkpointer=checkpointer)
