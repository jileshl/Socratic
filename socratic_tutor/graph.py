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
from socratic_tutor.policy import check_input_guardrails, check_answer_leak, check_reply, keep_retrieved_citations
from socratic_tutor.concept_graph import ConceptGraph
from socratic_tutor.learner_store import LearnerStore
from socratic_tutor.reflexion import ReflexionPlaybook
from socratic_tutor.tools import textbook_kb, math_tools, math_tools_server, question_bank
from socratic_tutor.agents import diagnostician, tutor, grader, question_setter

REFUSAL = "I cannot fulfill this request as entered. Let's focus on our NCERT study goals."
# Used only if the guardrail ever stops a message without giving its own reply (it always gives one today).
SUPPORTIVE_REPLY_FALLBACK = (
    "It is completely normal to feel stuck or frustrated when studying physics. "
    "Let's take a deep breath and take this one small step at a time. "
    "What specific part or formula are you looking at right now?"
)
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

    # Flowchart of the blocked case (each [box] matches a comment below):
    #
    #   [IG1] start the three new per-turn safety facts empty
    #          |
    #          v
    #   [IG2] did the guardrail stop the message?                    no -> carry on to the supervisor
    #          | yes: keep its reason and its distress level
    #          v
    #   [IG3] distress (academic, severe, or a safety concern)?      yes -> its OWN reply + teacher alert, end
    #          | no
    #          v
    #   [IG4] any other block (word rule, content guard, guard down) -> its OWN reply, end

    # [IG1] Which check stopped the message (e.g. "word_rule:teacher_claim"), and how worried we are.
    reset_state["input_blocked_by"] = None
    reset_state["distress_level"] = "none"
    # The reply check at the end of the turn fills this in if it has to replace the reply (output_guardrail).
    reset_state["output_blocked_by"] = None

    # [IG2] The guardrail stopped this message.
    if not guard_res["passed"]:
        # The guardrail chooses the right words for each case: the helpline for severe distress, a calm small
        # step for exam stress, a refusal for an attack. We show ITS reply. (Before, the graph replaced it with
        # one generic sentence, so a student in severe distress never saw the helpline.)
        policy_reply: str | None = guard_res.get("reply")
        # Keep the reason and the level in the state, so the web app can label the turn and word the alert.
        reset_state["input_blocked_by"] = guard_res.get("blocked_by")
        distress_level: str | None = guard_res.get("distress_level")
        if distress_level:
            reset_state["distress_level"] = distress_level

        # [IG3] Distress or a safety concern: end the turn and tell the teacher (Teacher Rule 4).
        if guard_res.get("is_distress"):
            # Start from the old text, and use the guardrail's reply whenever it gives one.
            distress_reply: str = SUPPORTIVE_REPLY_FALLBACK
            if policy_reply:
                distress_reply = policy_reply
            reset_state.update({
                "injection_detected": False,
                "distress_detected": True,
                "teacher_alert_triggered": True,
                "response": distress_reply,
            })
            return reset_state

        # [IG4] Any other block. injection_detected stays True here, as before, so the E2 evaluation still
        # counts every stopped attack as blocked; input_blocked_by says exactly which check it was.
        refusal_reply: str = REFUSAL
        if policy_reply:
            refusal_reply = policy_reply
        reset_state.update({
            "injection_detected": True,
            "distress_detected": False,
            "teacher_alert_triggered": False,
            "response": refusal_reply,
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
    # Flowchart (each [box] matches a comment below):
    #
    #   [OG1] the answer key and the question text (if the student is on a bank question)
    #          |
    #          v
    #   [OG2] leak check: the key and the question's own numbers (free questions: rule off, see below)
    #          |
    #          |-- leak in practice mode -> retry the hint, or the scaffold question (unchanged)
    #          v
    #   [OG3] reply check (R4's check_reply, practice mode): links out, retrieved citations only, guard
    #          |
    #          v
    #        the reply the student sees
    response = state.get("response", "")
    expected_answer = None
    # [OG1] The question's own text: numbers it already gives are not a leak when the reply repeats them.
    question_text: str | None = None
    qid = state.get("current_question_id")
    if qid:
        q = question_bank.get_approved_question(qid) or question_bank.get_question(qid)
        if q:
            expected_answer = q.get("gold_answer")
            question_text = q.get("prompt")
    if not expected_answer:
        expected_answer = state.get("gold_answer")

    # [OG2] The leak check: the key, and the question's own numbers (which a hint may repeat).
    # The student's message is NOT passed here on purpose. With it, check_answer_leak would also judge FREE
    # questions (no key) by "a new number with a unit leaks", and in a review that flagged normal hints:
    # "Remember that 1 m = 100 cm", "the near point is about 25 cm", or a second turn that repeats the numbers
    # from the first. That rule stays off until the E1 runs have measured it.
    leak: bool = check_answer_leak(response, expected_answer, question_text=question_text)
    # The student's message still goes to the reply check below, as context for the content guard.
    student_text: str = str(state.get("query") or "")

    # The sections that were really retrieved, and the citations kept from them (the same rule everywhere:
    # a citation of a section that was never retrieved was made up, so it is dropped).
    retrieved: list[dict] = state.get("retrieved_sections", [])
    citations: list[str] = state.get("citations", [])
    retrieved_ids: list[str] = []
    for passage in retrieved:
        # Each retrieved passage carries the NCERT section it came from, e.g. "9.2.4".
        section_id: Any = passage.get("section_id")
        if section_id:
            retrieved_ids.append(str(section_id))
    validated_citations: list[str] = keep_retrieved_citations(citations, retrieved_ids)

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

    # [OG3] R4's reply check (policy.check_reply) on the reply that is about to go out:
    #   - removes links and images, so nothing opens or loads by itself;
    #   - keeps only citations of sections that were really retrieved (a cited section we never fetched was
    #     made up);
    #   - when the guard models are on, the content guard reads the reply (unsafe for a minor -> a safe fallback).
    # It never raises: if a check breaks, the student gets the safe fallback reply (fail closed).
    # In quiz mode the reply is the grader's fixed feedback ("Correct! Well done."), written by code, so the
    # check is skipped: the content guard would cost a model call for nothing, and if the guard were down its
    # practice-mode fallback would replace the student's right/wrong verdict.
    checked: dict[str, Any] = {"reply": response, "citations": validated_citations, "blocked_by": None}
    if state.get("mode", "practice") != "quiz":
        checked = check_reply(response, citations, retrieved_ids, student_text)

    return {
        "steps": ["output_guardrail"],
        "turn_steps": state.get("turn_steps", []) + ["output_guardrail"],
        # The cleaned reply (or the safe fallback, if the reply check replaced it).
        "response": checked["reply"],
        # Only the citations of sections that were really retrieved.
        "citations": checked["citations"],
        "answer_leak_flag": False,
        # None when the reply passed; otherwise which check replaced it (for the web app's labels).
        "output_blocked_by": checked["blocked_by"],
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


FORMULA_ALIASES: dict[str, str] = {
    "mirror": "mirror_formula",
    "mirror_formula": "mirror_formula",
    "lens": "lens_formula",
    "lens_formula": "lens_formula",
    "lens_power": "lens_power",
    "power": "lens_power",
    "parallel": "parallel_resistance",
    "parallel_resistance": "parallel_resistance",
    "resistors_parallel": "parallel_resistance",
    "series": "series_resistance",
    "series_resistance": "series_resistance",
    "resistors_series": "series_resistance",
    "ohms": "ohms_law",
    "ohm": "ohms_law",
    "ohms_law": "ohms_law",
    "joule": "joule_heating",
    "heating": "joule_heating",
    "joule_heating": "joule_heating",
    "charge_current": "charge_current",
    "voltage_work_charge": "voltage_work_charge",
    "resistivity": "resistivity",
    "wire_area": "wire_area",
    "power_voltage_current": "power_voltage_current",
    "power_current_resistance": "power_current_resistance",
    "power_voltage_resistance": "power_voltage_resistance",
    "energy_power_time": "energy_power_time",
    "energy_cost": "energy_cost",
    "focal_length_from_radius": "focal_length_from_radius",
    "mirror_magnification": "mirror_magnification",
    "lens_magnification": "lens_magnification",
    "image_height": "image_height",
    "image_nature": "image_nature",
    "combine_lens_powers": "combine_lens_powers",
    "absolute_refractive_index": "absolute_refractive_index",
    "relative_refractive_index": "relative_refractive_index",
    "relative_index_from_absolute": "relative_index_from_absolute",
}


def _calculate_or_verify_answer(
    prompt_text: str,
    gold_answer: str,
    concept: str,
    calculation: dict[str, Any] | None = None,
) -> tuple[str, bool]:
    """Ground and calculate numerical answer keys using deterministic math_tools before showing/proposing.

    Returns (answer_key, is_verified) where is_verified is True only when calculated or verified by math-tools.
    """
    # 1. Structured calculation from question setter model (guide p.2, rule 1)
    if isinstance(calculation, dict) and calculation:
        raw_formula = str(calculation.get("formula", "")).strip().lower()
        formula = FORMULA_ALIASES.get(raw_formula, raw_formula)

        if isinstance(calculation.get("values"), dict):
            raw_values = dict(calculation["values"])
        else:
            raw_values = {
                k: v for k, v in calculation.items()
                if k not in ("formula", "find", "length_unit", "unit", "solve_for", "target")
            }

        length_unit = calculation.get("length_unit") or calculation.get("unit")

        try:
            # Handle resistors list if passed as separate keys (e.g. r1, r2)
            if formula in ("parallel_resistance", "series_resistance"):
                if "resistors" not in raw_values:
                    res_vals = [float(v) for k, v in raw_values.items() if isinstance(v, (int, float))]
                    if len(res_vals) >= 2:
                        raw_values = {"resistors": res_vals}
                elif isinstance(raw_values.get("resistors"), (list, tuple)):
                    raw_values["resistors"] = [float(x) for x in raw_values["resistors"]]

            # Sign convention adjustments for optics
            if formula in ("mirror_formula", "lens_formula"):
                length_unit = length_unit or ("m" if " m " in f" {prompt_text} " else "cm")
                if "u" in raw_values:
                    raw_values["u"] = -abs(float(raw_values["u"]))
                if "f" in raw_values:
                    f_val = float(raw_values["f"])
                    if "concave" in prompt_text.lower() or "concave" in str(calculation).lower():
                        raw_values["f"] = -abs(f_val)
                    elif "convex" in prompt_text.lower() or "convex" in str(calculation).lower():
                        raw_values["f"] = abs(f_val)

            clean_values: dict[str, Any] = {}
            for k, v in raw_values.items():
                if k == "resistors" and isinstance(v, list):
                    clean_values[k] = v
                elif isinstance(v, (int, float)):
                    clean_values[k] = float(v)
                elif isinstance(v, str):
                    try:
                        clean_values[k] = float(v)
                    except ValueError:
                        clean_values[k] = v
                else:
                    clean_values[k] = v

            sol = None
            if formula in math_tools_server.OPTICS_FORMULAS:
                lu = length_unit or ("m" if formula == "lens_power" else "cm")
                sol = math_tools_server.solve_optics(formula, clean_values, length_unit=lu)
            elif formula in math_tools_server.ELECTRICITY_FORMULAS:
                sol = math_tools_server.solve_electricity(formula, clean_values)

            if sol and sol.get("ok"):
                val = sol["value"]
                unit = sol.get("unit", "").strip()
                ans = f"{val:g} {unit}".strip() if unit else f"{val:g}"
                return ans, True
        except Exception:
            pass

    # 2. Regex fallback: Parallel combination (only match resistors with ohm/Ω/ohms, not V/A)
    if "parallel" in prompt_text.lower() and any(w in prompt_text.lower() for w in ["ohm", "ω", "resistor"]):
        vals = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*(?:ohm|Ω|ohms)\b", prompt_text, re.I)]
        if len(vals) >= 2:
            try:
                res = math_tools_server.solve_electricity("parallel_resistance", {"resistors": vals[:5]})
                if res.get("ok"):
                    return f"{res['value']:g} ohm", True
            except Exception:
                pass

    # 3. Regex fallback: Series combination (only match resistors with ohm/Ω/ohms, not V/A)
    if "series" in prompt_text.lower() and any(w in prompt_text.lower() for w in ["ohm", "ω", "resistor"]):
        vals = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*(?:ohm|Ω|ohms)\b", prompt_text, re.I)]
        if len(vals) >= 2:
            try:
                res = math_tools_server.solve_electricity("series_resistance", {"resistors": vals[:5]})
                if res.get("ok"):
                    return f"{res['value']:g} ohm", True
            except Exception:
                pass

    # 4. Regex fallback: Spherical mirror formula
    if "mirror" in prompt_text.lower() and "cm" in prompt_text.lower():
        u_m = re.search(r"(\d+(?:\.\d+)?)\s*cm\s+(?:in\s+front|from)", prompt_text, re.I) or re.search(r"object.*?(\d+(?:\.\d+)?)\s*cm", prompt_text, re.I)
        f_m = re.search(r"focal\s+length.*?(\d+(?:\.\d+)?)\s*cm", prompt_text, re.I)
        if u_m and f_m:
            try:
                u_val = -abs(float(u_m.group(1)))
                is_concave = "concave" in prompt_text.lower()
                f_val = -abs(float(f_m.group(1))) if is_concave else abs(float(f_m.group(1)))
                res = math_tools_server.solve_optics("mirror_formula", {"u": u_val, "f": f_val}, length_unit="cm")
                if res.get("ok"):
                    return f"{res['value']:g} cm", True
            except Exception:
                pass

    # 5. Regex fallback: Spherical lens formula
    if "lens" in prompt_text.lower() and "cm" in prompt_text.lower():
        u_m = re.search(r"(\d+(?:\.\d+)?)\s*cm\s+(?:in\s+front|from)", prompt_text, re.I) or re.search(r"object.*?(\d+(?:\.\d+)?)\s*cm", prompt_text, re.I)
        f_m = re.search(r"focal\s+length.*?(\d+(?:\.\d+)?)\s*cm", prompt_text, re.I)
        if u_m and f_m:
            try:
                u_val = -abs(float(u_m.group(1)))
                is_convex = "convex" in prompt_text.lower()
                f_val = abs(float(f_m.group(1))) if is_convex else -abs(float(f_m.group(1)))
                res = math_tools_server.solve_optics("lens_formula", {"u": u_val, "f": f_val}, length_unit="cm")
                if res.get("ok"):
                    return f"{res['value']:g} cm", True
            except Exception:
                pass

    # 6. Regex fallback: Lens power (supports metres and cm, catches unexpected errors)
    if "power" in prompt_text.lower() and ("focal length" in prompt_text.lower() or " dioptre" in prompt_text.lower() or " d\b" in prompt_text.lower() or " d." in prompt_text.lower()):
        f_m = re.search(r"focal\s+length.*?(\d+(?:\.\d+)?)\s*m\b", prompt_text, re.I)
        if f_m:
            try:
                res = math_tools_server.solve_optics("lens_power", {"f": float(f_m.group(1))}, length_unit="m")
                if res.get("ok"):
                    return f"{res['value']:g} D", True
            except Exception:
                pass
        f_cm = re.search(r"focal\s+length.*?(\d+(?:\.\d+)?)\s*cm\b", prompt_text, re.I)
        if f_cm:
            try:
                res = math_tools_server.solve_optics("lens_power", {"f": float(f_cm.group(1))}, length_unit="cm")
                if res.get("ok"):
                    return f"{res['value']:g} D", True
            except Exception:
                pass

    # 7. Fallback: clean and standardize numeric answer if readable by math_tools, or return original text
    if gold_answer:
        tidy = math_tools.tidy_answer_text(gold_answer)
        q = math_tools.read_quantity(tidy)
        if q.get("ok"):
            return tidy, False

    return gold_answer, False


def node_question_setter(state: SocraticState) -> dict:
    concept = state.get("current_concept_id", "concept_reflection_laws")
    res = question_setter.select_question(concept)
    if not isinstance(res, dict) or res.get("error") or not res.get("question_text") or not res.get("gold_answer"):
        return {
            "steps": ["question_setter"],
            "turn_steps": state.get("turn_steps", []) + ["question_setter"],
            "teacher_approval_required": False,
            "teacher_approval_payload": None,
            "response": f"No question proposal available for concept '{concept}'.",
        }

    prompt_text = res["question_text"]
    raw_gold_answer = res["gold_answer"]
    difficulty = res.get("difficulty", "medium")
    calculation = res.get("calculation")
    if calculation is None and "formula" in res:
        calculation = {k: v for k, v in res.items() if k not in ("question_text", "gold_answer", "concept_id", "difficulty", "error")}

    # Step 5: Solver calculates or grounds numeric answers before the question is proposed/shown
    gold_answer, is_verified = _calculate_or_verify_answer(
        prompt_text, raw_gold_answer, concept, calculation=calculation
    )

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
        "verified": is_verified,
        "solver_verified": is_verified,
    }
    payload_data["payload_hash"] = _compute_payload_hash(payload_data)

    return {
        "steps": ["question_setter"],
        "turn_steps": state.get("turn_steps", []) + ["question_setter"],
        "teacher_approval_required": True,
        "teacher_approval_payload": payload_data,
    }


def node_teacher_approval_gate(state: SocraticState) -> dict:
    payload = state.get("teacher_approval_payload")
    if not payload:
        return {
            "steps": ["teacher_approval_gate"],
            "turn_steps": state.get("turn_steps", []) + ["teacher_approval_gate"],
            "teacher_approval_required": False,
            "response": state.get("response", "No question proposal to review."),
        }

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
