"""LangGraph workflow definition for Socratic Tutor."""

from __future__ import annotations

import re
import uuid
import json
import hashlib
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
        "hint_raised_this_turn": False,
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
    hint_raised = state.get("hint_raised_this_turn", False)
    last_concept = state.get("last_concept_id")
    if last_concept and current_concept and last_concept != current_concept:
        hint_step = 1

    last_qid = state.get("last_question_id")
    qid = state.get("current_question_id")
    if last_qid and qid and last_qid != qid:
        hint_step = 1

    # Hint progression: adjust once per turn at start of practice turn if continuing on same concept/question or stuck
    if mode == "practice" and not plan:
        is_continuing_practice = bool(last_concept and last_concept == current_concept)
        if (stuck or is_continuing_practice) and not hint_raised and hint_step < config.MAX_HINT_STEPS:
            hint_step = min(hint_step + 1, config.MAX_HINT_STEPS)
            hint_raised = True

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
                "hint_raised_this_turn": hint_raised,
            }
        else:
            # N3: If grader encountered an error (e.g. unapproved question), do not run replan
            if grade_res.get("error"):
                return {
                    "steps": ["supervisor"],
                    "turn_steps": turn_steps + ["supervisor"],
                    "plan": ["grade_error"],
                    "mastery_map": mastery,
                    "current_concept_id": current_concept,
                    "next_recommended_concept": next_concept,
                    "teacher_alert_triggered": True,
                    "hint_step": hint_step,
                    "hint_raised_this_turn": hint_raised,
                    "last_concept_id": current_concept,
                    "last_question_id": qid,
                }

            # Grader finished! Supervisor saves quiz result and replans
            score = float(grade_res.get("score", 0.0))
            # N1: quiz results filed under the question's own concept, not the student's current concept
            quiz_concept = grade_res.get("concept_id")
            if not quiz_concept:
                qid = state.get("current_question_id")
                if qid:
                    q = question_bank.get_approved_question(qid)
                    if q and q.get("concept_id"):
                        quiz_concept = q.get("concept_id")
            quiz_concept = quiz_concept or current_concept

            concept_failures = 0
            if student_id and quiz_concept:
                quiz_res = store.record_quiz_result(student_id, quiz_concept, score)
                if quiz_res.get("teacher_alert_triggered"):
                    teacher_alert = True
                updated_profile = store.get_profile(student_id)
                mastery = dict(updated_profile.get("mastery_map", {}))
                failure_streaks = updated_profile.get("failure_streaks", {})
                concept_failures = failure_streaks.get(quiz_concept or "", 0)

            # N2: 'mastered' is decided by updated mastery, not by a single answer
            concept_mastery = mastery.get(quiz_concept)
            if concept_mastery is not None:
                is_mastered = concept_mastery >= config.PASSING_MASTERY_THRESHOLD
            else:
                is_mastered = score >= config.PASSING_MASTERY_THRESHOLD

            if is_mastered:
                if student_id:
                    miscon = state.get("identified_misconception")
                    if miscon and isinstance(miscon, dict) and miscon.get("id"):
                        try:
                            store.record_misconception(student_id, miscon["id"], resolved=True)
                        except Exception:
                            pass
                    lesson = state.get("effective_lesson_applied")
                    if lesson:
                        try:
                            lesson_id = lesson if isinstance(lesson, str) else str(lesson.get("lesson_id", lesson))
                            store.record_effective_lesson(student_id, lesson_id)
                        except Exception:
                            pass

                next_concept = cg.next_recommended(mastery)
                current_concept = next_concept
                hint_step = 1
            elif concept_failures >= 3:
                prereqs = cg.get_prerequisites(quiz_concept)
                if prereqs:
                    next_concept = prereqs[0]
                    current_concept = next_concept
                    hint_step = 1
            else:
                current_concept = quiz_concept

            return {
                "steps": ["supervisor"],
                "turn_steps": turn_steps + ["supervisor"],
                "plan": ["graded", "replanned"],
                "mastery_map": mastery,
                "current_concept_id": current_concept,
                "next_recommended_concept": next_concept,
                "teacher_alert_triggered": teacher_alert,
                "hint_step": hint_step,
                "hint_raised_this_turn": hint_raised,
                "last_concept_id": current_concept,
                "last_question_id": qid,
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
            "hint_raised_this_turn": hint_raised,
            "last_concept_id": current_concept,
            "last_question_id": qid,
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
            "hint_raised_this_turn": hint_raised,
            "last_concept_id": current_concept,
            "last_question_id": qid,
            "last_misconception_id": state.get("last_misconception_id"),
        }

    # 2. Has diagnostician produced a result?
    if "diagnostician" in turn_steps or "diagnose" in plan:
        diag = state.get("identified_misconception")
        miscon_id = diag.get("id") if (diag and isinstance(diag, dict)) else None
        last_miscon = state.get("last_misconception_id")

        # Raise hint ladder when the same concept and misconception returned (last hint didn't help)
        # N4: Ensure hint can only be raised at most once per turn
        if miscon_id and last_miscon and miscon_id == last_miscon and last_concept == current_concept:
            if not hint_raised and hint_step < config.MAX_HINT_STEPS:
                hint_step = min(hint_step + 1, config.MAX_HINT_STEPS)
                hint_raised = True

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
            "hint_raised_this_turn": hint_raised,
            "last_concept_id": current_concept,
            "last_question_id": qid,
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
        "hint_raised_this_turn": hint_raised,
        "last_concept_id": current_concept,
        "last_question_id": qid,
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
    miscon_chapter = None
    if isinstance(diag_res, dict):
        miscon_id = diag_res.get("identified_misconception_id") or diag_res.get("id")
        miscon_name = diag_res.get("identified_misconception_name") or diag_res.get("name")
        miscon_chapter = diag_res.get("chapter")

    if miscon_id and not miscon_chapter:
        try:
            catalog = getattr(diagnostician, "_load_catalog", lambda: [])()
            for m in catalog:
                if m.get("id") == miscon_id:
                    miscon_chapter = m.get("chapter")
                    break
        except Exception:
            pass

    playbook = ReflexionPlaybook()
    effective_lesson = None
    if miscon_id:
        lessons = playbook.get_lessons_for_misconception(miscon_id)
        if lessons:
            effective_lesson = lessons[0]

    student_id = state.get("student_id")
    if student_id and miscon_id:
        try:
            store = LearnerStore()
            store.record_misconception(student_id, miscon_id)
        except Exception:
            pass

    return {
        "steps": ["diagnostician"],
        "turn_steps": state.get("turn_steps", []) + ["diagnostician"],
        "identified_misconception": {
            "id": miscon_id,
            "name": miscon_name,
            "chapter": miscon_chapter,
        } if miscon_id else None,
        "effective_lesson_applied": effective_lesson,
    }


def node_tutor(state: SocraticState) -> dict:
    query = state.get("query", "")
    hint_tries = state.get("hint_tries", 0) + 1
    chapter = _resolve_chapter(state)
    passages = state.get("retrieved_sections")
    if not passages:
        passages = textbook_kb.search_textbook(query, chapter=chapter, top_k=4)
        if not passages and chapter:
            # Fall back to unfiltered search if filtered search returned no relevant passages
            passages = textbook_kb.search_textbook(query, top_k=4)
    passages = passages or []

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
        q = question_bank.get_approved_question(qid) or question_bank.get_question(qid)
        if q:
            expected_answer = q.get("gold_answer")
    if not expected_answer:
        expected_answer = state.get("gold_answer")

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
    # N1: question's own concept takes priority for grading and recording
    question_concept = q.get("concept_id") or concept_id

    is_numeric = bool(re.search(r"\d", gold_answer))
    res = grader.grade_answer(attempt, gold_answer, is_numeric=is_numeric)
    res["concept_id"] = question_concept

    feedback = res.get("feedback") or ("Correct! Well done." if res.get("is_correct") else "Not quite right. Let's review the concept.")

    return {
        "steps": ["grader"],
        "turn_steps": state.get("turn_steps", []) + ["grader"],
        "grade_result": res,
        "response": feedback,
        "current_concept_id": question_concept or concept_id,
    }


def _compute_payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _calculate_or_verify_answer(prompt_text: str, gold_answer: str, concept: str) -> str:
    """Ground and calculate numerical answer keys using deterministic math_tools before showing/proposing."""
    # 1. Parallel combination
    if "parallel" in prompt_text.lower() and any(w in prompt_text.lower() for w in ["ohm", "ω", "resistor"]):
        vals = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*(?:ohm|Ω|\b)", prompt_text, re.I)]
        if len(vals) >= 2:
            res = math_tools.solve_parallel_resistance(vals[:5])
            if res.get("ok"):
                return f"{res['value']:g} ohm"

    # 2. Series combination
    if "series" in prompt_text.lower() and any(w in prompt_text.lower() for w in ["ohm", "ω", "resistor"]):
        vals = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*(?:ohm|Ω|\b)", prompt_text, re.I)]
        if len(vals) >= 2:
            res = math_tools.solve_series_resistance(vals[:5])
            if res.get("ok"):
                return f"{res['value']:g} ohm"

    # 3. Spherical mirror formula
    if "mirror" in prompt_text.lower() and "cm" in prompt_text.lower():
        u_m = re.search(r"(\d+(?:\.\d+)?)\s*cm\s+(?:in\s+front|from)", prompt_text, re.I) or re.search(r"object.*?(\d+(?:\.\d+)?)\s*cm", prompt_text, re.I)
        f_m = re.search(r"focal\s+length.*?(\d+(?:\.\d+)?)\s*cm", prompt_text, re.I)
        if u_m and f_m:
            u_val = -abs(float(u_m.group(1)))
            is_concave = "concave" in prompt_text.lower()
            f_val = -abs(float(f_m.group(1))) if is_concave else abs(float(f_m.group(1)))
            res = math_tools.solve_mirror_formula("cm", u=u_val, f=f_val)
            if res.get("ok"):
                return f"v = {res['value']:g} cm"

    # 4. Spherical lens formula
    if "lens" in prompt_text.lower() and "cm" in prompt_text.lower():
        u_m = re.search(r"(\d+(?:\.\d+)?)\s*cm\s+(?:in\s+front|from)", prompt_text, re.I) or re.search(r"object.*?(\d+(?:\.\d+)?)\s*cm", prompt_text, re.I)
        f_m = re.search(r"focal\s+length.*?(\d+(?:\.\d+)?)\s*cm", prompt_text, re.I)
        if u_m and f_m:
            u_val = -abs(float(u_m.group(1)))
            is_convex = "convex" in prompt_text.lower()
            f_val = abs(float(f_m.group(1))) if is_convex else -abs(float(f_m.group(1)))
            res = math_tools.solve_lens_formula("cm", u=u_val, f=f_val)
            if res.get("ok"):
                return f"v = {res['value']:g} cm"

    # 5. Lens power
    if "power" in prompt_text.lower() and ("focal length" in prompt_text.lower() or " dioptre" in prompt_text.lower() or " d" in prompt_text.lower()):
        f_m = re.search(r"focal\s+length.*?(\d+(?:\.\d+)?)\s*m\b", prompt_text, re.I)
        if f_m:
            res = math_tools.solve_lens_power(f_m=float(f_m.group(1)))
            if res.get("ok"):
                return f"P = {res['value']:g} D"

    # 6. Fallback: clean and standardize numeric answer if readable by math_tools
    if gold_answer:
        tidy = math_tools.tidy_answer_text(gold_answer)
        q = math_tools.read_quantity(tidy)
        if q.get("ok"):
            return tidy

    return gold_answer


def node_question_setter(state: SocraticState) -> dict:
    concept = state.get("current_concept_id", "concept_reflection_laws")
    res = question_setter.select_question(concept)
    prompt_text = res.get("question_text", "State the laws of reflection.")
    raw_gold_answer = res.get("gold_answer", "")
    difficulty = res.get("difficulty", "medium")

    # Step 5: Solver calculates or grounds numeric answers before the question is proposed/shown
    gold_answer = _calculate_or_verify_answer(prompt_text, raw_gold_answer, concept)

    # Propose question to bank in pending_approval status
    prop = question_bank.propose_question(
        concept_id=concept,
        difficulty=difficulty,
        prompt=prompt_text,
        gold_answer=gold_answer,
    )
    qid = prop["question_id"]
    set_id = f"set_{uuid.uuid4().hex[:8]}"

    payload_data = {
        "set_id": set_id,
        "question_id": qid,
        "concept": concept,
        "prompt": prompt_text,
        "gold_answer": gold_answer,
        "difficulty": difficulty,
    }
    payload_data["payload_hash"] = _compute_payload_hash(payload_data)

    return {
        "steps": ["question_setter"],
        "turn_steps": state.get("turn_steps", []) + ["question_setter"],
        "teacher_approval_required": True,
        "teacher_approval_payload": payload_data,
    }


def node_teacher_approval_gate(state: SocraticState) -> dict:
    payload = state.get("teacher_approval_payload", {})
    decision = interrupt({"payload": payload, "prompt": "Approve new question for shared bank?"})

    is_dict = isinstance(decision, dict)
    action = decision.get("action") if is_dict else None
    decision_hash = decision.get("payload_hash") if is_dict else None

    # Expected payload hash
    raw_payload = {k: v for k, v in payload.items() if k != "payload_hash"}
    expected_hash = payload.get("payload_hash") or _compute_payload_hash(raw_payload)

    # Validate payload hash if provided
    hash_valid = True
    if decision_hash is not None:
        hash_valid = (decision_hash == expected_hash)

    approved = is_dict and (action == "approve") and hash_valid

    qid = payload.get("question_id")
    if approved:
        if qid:
            question_bank.publish_approved_question(qid)
        else:
            prop = question_bank.propose_question(
                concept_id=payload.get("concept", "concept_reflection_laws"),
                difficulty=payload.get("difficulty", "medium"),
                prompt=payload.get("prompt", ""),
                gold_answer=payload.get("gold_answer", ""),
            )
            qid = prop["question_id"]
            question_bank.publish_approved_question(qid)
        msg = "Question approved and published."
    else:
        msg = "Question proposal rejected."

    return {
        "steps": ["teacher_approval_gate"],
        "turn_steps": state.get("turn_steps", []) + ["teacher_approval_gate"],
        "teacher_approval_required": False,
        "response": msg,
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
