"""LangGraph workflow definition for Socratic Tutor."""

from __future__ import annotations

import re
from typing import Any
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command
from langchain_core.messages import AnyMessage, AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from socratic_tutor import config
from socratic_tutor import approval_gate, solver_key, tool_hooks
from socratic_tutor.state import SocraticState
from socratic_tutor.policy import check_input_guardrails, check_answer_leak, check_reply, keep_retrieved_citations
from socratic_tutor import intent as intent_check
from socratic_tutor import topics
from socratic_tutor import mcp_tools
from socratic_tutor.concept_graph import ConceptGraph
from socratic_tutor.learner_store import LearnerStore
from socratic_tutor.reflexion import ReflexionPlaybook
from socratic_tutor.tools import textbook_kb, question_bank, question_bank_server
from socratic_tutor.agents import diagnostician, tutor, grader, question_setter

REFUSAL = "I cannot fulfill this request as entered. Let's focus on our NCERT study goals."
# How many questions the question setter drafts for one teacher request, unless the request says (PR-2, P2-2).
QUESTION_SET_SIZE: int = 3
# Used only if the guardrail ever stops a message without giving its own reply (it always gives one today).
SUPPORTIVE_REPLY_FALLBACK = (
    "It is completely normal to feel stuck or frustrated when studying physics. "
    "Let's take a deep breath and take this one small step at a time. "
    "What specific part or formula are you looking at right now?"
)
_SECTION_RE = re.compile(r"(?<![\d.])(9|10|11)\.(\d{1,2})(?:\.(\d{1,2}))?(?![\d])")
_NCERT_CITATION_RE = re.compile(
    r"(?P<prefix>\bNCERT\s+(?:Sec(?:tion)?\.?|Section)\s*)(?P<section>(?:9|10|11)\.\d{1,2}(?:\.\d{1,2})?)",
    re.IGNORECASE,
)


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


def _repair_ncert_citation_text(reply: str, retrieved_ids: list[str]) -> str:
    """Replace a hallucinated visible NCERT citation with a section that was actually retrieved."""
    allowed = list(dict.fromkeys(str(section_id) for section_id in retrieved_ids))

    def replace(match: re.Match[str]) -> str:
        section = match.group("section")
        if section in allowed:
            return match.group(0)
        if allowed:
            return match.group("prefix") + allowed[0]
        return "NCERT source unavailable"

    return _NCERT_CITATION_RE.sub(replace, reply)


CHAPTER_TITLE_TO_NUM: dict[str, str] = {
    "Light - Reflection and Refraction": "9",
    "Human Eye and the Colourful World": "10",
    "Electricity": "11",
}


def _concept_chapter(concept_id: str | None) -> str | None:
    """Return the canonical NCERT chapter for a concept, when the concept is known."""
    if not concept_id:
        return None
    concept = ConceptGraph().concepts.get(concept_id, {})
    chapter = concept.get("chapter")
    if chapter in CHAPTER_TITLE_TO_NUM:
        return CHAPTER_TITLE_TO_NUM[chapter]
    if chapter:
        match = re.search(r"\b(9|10|11)\b", str(chapter))
        if match:
            return match.group(1)
    return None


def _section_matches_chapter(section_id: Any, chapter: str | None) -> bool:
    """A section such as 10.2 belongs to Chapter 10; no chapter means no filtering."""
    if not chapter:
        return True
    section = str(section_id or "").strip()
    return section == chapter or section.startswith(chapter + ".")


def _resolve_chapter(state: SocraticState) -> str | None:
    """Resolve the NCERT chapter, preferring canonical topic facts over stale UI state."""
    # 1. The active concept is authoritative. A selected Chapter 10 topic must not be searched in a stale
    # Chapter 9 UI context (the Flashcard -> Ask Tutor myopia defect found during R1 testing).
    concept_chapter = _concept_chapter(state.get("current_concept_id"))
    if concept_chapter:
        return concept_chapter

    # 2. A diagnosed misconception is also tied to a canonical chapter.
    miscon = state.get("identified_misconception")
    if isinstance(miscon, dict):
        ch_title = miscon.get("chapter")
        if ch_title in CHAPTER_TITLE_TO_NUM:
            return CHAPTER_TITLE_TO_NUM[ch_title]
        if ch_title:
            m = re.search(r"\b(9|10|11)\b", str(ch_title))
            if m:
                return m.group(1)

    # 3. Use the caller/UI chapter only when no topic fact is available.
    raw_chapter = state.get("chapter")
    if raw_chapter is not None:
        ch_str = str(raw_chapter).strip()
        if ch_str in CHAPTER_TITLE_TO_NUM:
            return CHAPTER_TITLE_TO_NUM[ch_str]
        m = re.search(r"\b(9|10|11)\b", ch_str)
        if m:
            return m.group(1)

    return None


# --- Node Definitions ---

# The student asking for more help on the same topic. Only this (or a repeated mix-up, or being stuck) moves
# the hint ladder up; "okay, thanks" or the student's own explanation does not.
_MORE_HELP = re.compile(
    r"\b(hints?|help|stuck|confus\w*|lost|no idea|not sure|give up|i['’]?m done"
    r"|(?:do|did|can)\s*(?:n['’]?t|not)\s+(?:get|understand|follow|see|know)|cannot\s+(?:get|understand|follow|see)"
    r"|tell me|give me|show me|the answer|formula|explain (?:it |this |that )?(?:again|differently))\b",
    re.IGNORECASE,
)


def asks_for_more_help(query: str) -> bool:
    return bool(_MORE_HELP.search(query or ""))


def node_input_guardrail(state: SocraticState, config: RunnableConfig) -> dict:
    query = state.get("query", "")
    guard_res = check_input_guardrails(query)

    # [H1] R4's tool hooks: every student turn starts with a fresh tool budget, shared by all the agents
    # (config.MAX_TOOL_CALLS_PER_TURN calls, and the same call at most MAX_IDENTICAL_TOOL_CALLS times).
    # Without this, the budget would run out after a few turns and every tool call would be blocked.
    hooks_session_id: Any = state.get("session_id")
    if isinstance(hooks_session_id, str) and hooks_session_id.strip() != "":
        tool_hooks.start_turn(hooks_session_id)

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
        "intent": "physics",
        "intent_rule": None,
        "detected_concept_id": None,
        "off_topic": False,
        "unproductive_turns": int(state.get("unproductive_turns") or 0),
    }
    if state.get("chapter"):
        reset_state["chapter"] = state["chapter"]

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

    # [IG5] Intent check (code, practice mode): is this about learning physics? Another student's results, a role
    # claim, rudeness, "go away", "hi" or "ok thanks" get a short fixed reply here, with no diagnosis and no new
    # hint, so the tutor no longer answers every message with the same hint (team testing, 12 Nov).
    # Only for a student's own message: a teacher's "propose a question set" request runs the same graph.
    if state.get("mode", "practice") == "practice" and not state.get("teacher_approval_required"):
        started = any(getattr(m, "type", "") == "ai" for m in (state.get("messages") or []))
        active_concept = state.get("current_concept_id") or state.get("lesson_concept_id")
        raw_query = str(guard_res["sanitized_query"] or "").strip()
        verdict = intent_check.classify(
            raw_query,
            in_conversation=started,
            config_runnable=config,
            current_concept=active_concept,
        )
        kind, rule = verdict
        reset_state["intent"], reset_state["intent_rule"] = kind, rule
        cid = getattr(verdict, "concept_id", None)
        if cid:
            reset_state["detected_concept_id"] = cid

        # Track unproductive / stagnant turns in practice mode (disengaged acks, sighs, or short fillers)
        stagnant_tokens = {
            "arrey", "arre", "but", "but then", "oh well", "well", "f9", "ans", "tell", "tell me", "nah", "nope",
            "k", "kk", "ok", "okay", "idk",
        }
        q_lower = raw_query.lower()
        is_stagnant = (
            (q_lower in stagnant_tokens)
            or (kind == "small_talk" and rule == "ack")
            or (kind in ("rude", "fed_up", "conduct", "gibberish"))
            or (len(raw_query.split()) <= 2 and not any(ch in raw_query for ch in "=+-*/0123456789?"))
        )

        curr_unproductive = int(state.get("unproductive_turns") or 0)
        new_unproductive = (curr_unproductive + 1) if is_stagnant else 0
        reset_state["unproductive_turns"] = new_unproductive

        if new_unproductive >= 3:
            reset_state["teacher_alert_triggered"] = True

        if kind == "confused":
            # "huh?": the same topic, explained another way (and it counts as asking for more help).
            reset_state["query"] = intent_check.CONFUSED_REWRITE
        elif kind != "physics":
            reset_state["off_topic"] = True
            # Anti-repetition: if student repeatedly gives small_talk acks (e.g. "k", "kk"), don't repeat the identical ACK_REPLY
            if kind == "small_talk" and rule == "ack" and curr_unproductive >= 1:
                if new_unproductive >= 3:
                    reset_state["response"] = (
                        "It looks like we're stuck in a loop on this topic. I've notified your teacher so you can review this "
                        "together in class. In the meantime, would you like to try another topic or take a break?"
                    )
                else:
                    reset_state["response"] = (
                        "It seems like you might be stuck or ready for a break. "
                        "Would you like to try a different topic, or should I ask your teacher to check in with you?"
                    )
            else:
                reset_state["response"] = intent_check.reply_for(kind, rule)
            reset_state["messages"] = [AIMessage(content=reset_state["response"])]
            if kind in ("rude", "fed_up", "conduct"):
                reset_state["rude_count"] = int(state.get("rude_count") or 0) + 1
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
    explicit_concept = state.get("current_concept_id")
    current_concept = explicit_concept
    # "Learn from the start": while the student works through a lesson, the tutor stays on the lesson's topic.
    # A mix-up from another chapter can still move it; one in the same chapter can't (a vague reply or "huh"
    # used to drift a Laws of Reflection lesson to the mirror formula).
    lesson_concept = state.get("lesson_concept_id")
    if lesson_concept and lesson_concept in cg.concepts and not state.get("concept_pinned"):
        current_concept = lesson_concept
    # The topic is pinned when the student picked it for this turn (web: "Practise it"), or when a caller
    # passes current_concept_id without saying (tests, evaluation). A topic only carried over from the last
    # turn is not pinned: a new chapter or a new question may move the tutor to its own topic.
    pinned = bool(state.get("concept_pinned", bool(explicit_concept)))

    req_chapter = state.get("chapter")
    req_ch_num = None
    if req_chapter:
        req_ch_num = str(req_chapter).strip()
        if req_ch_num in CHAPTER_TITLE_TO_NUM:
            req_ch_num = CHAPTER_TITLE_TO_NUM[req_ch_num]
        else:
            m = re.search(r"\b(9|10|11)\b", req_ch_num)
            if m:
                req_ch_num = m.group(1)
        current_ch_num = CHAPTER_TITLE_TO_NUM.get(cg.concepts.get(current_concept or "", {}).get("chapter", ""))
        if current_concept and not pinned and current_ch_num and current_ch_num != req_ch_num:
            current_concept = None  # the student moved to another chapter

    if not current_concept and req_ch_num:
        for cid, cdata in cg.concepts.items():
            c_ch_num = CHAPTER_TITLE_TO_NUM.get(cdata.get("chapter", ""))
            if c_ch_num == req_ch_num and mastery.get(cid, 0.0) < config.PASSING_MASTERY_THRESHOLD:
                current_concept = cid
                break
        if not current_concept:
            for cid, cdata in cg.concepts.items():
                if CHAPTER_TITLE_TO_NUM.get(cdata.get("chapter", "")) == req_ch_num:
                    current_concept = cid
                    break

    if not current_concept:
        current_concept = next_concept

    # A question that clearly names another topic ("what is the power of a lens?", "why is the sky blue?") moves
    # the tutor there, also out of a lesson, and its chapter comes along for the book search. A topic the
    # student picked for this turn ("Practise it") still wins.
    chapter_out = state.get("chapter")
    detected = state.get("detected_concept_id")
    asked = detected if (detected and detected in cg.concepts) else (topics.topic_of(state.get("query", "")) if state.get("mode", "practice") == "practice" else None)
    if asked and asked in cg.concepts and asked != current_concept and not pinned:
        current_concept = asked
        chapter_out = CHAPTER_TITLE_TO_NUM.get(cg.concepts[asked].get("chapter", ""), chapter_out)
    # Once a topic is known, its catalog chapter wins over a stale chapter supplied by the page that opened
    # the tutor. This also covers a pinned topic, where `asked == current_concept` and the old code did nothing.
    chapter_out = _concept_chapter(current_concept) or chapter_out
    lesson_pinned = bool(lesson_concept) and current_concept == lesson_concept
    # A quiz answer belongs to its question's topic (team review, 12 Nov: one of three wrong answers to the same
    # mirror question was logged under another topic, so the "3 in a row" stuck alert never fired).
    if state.get("mode", "practice") == "quiz" and state.get("current_question_id"):
        try:
            asked_q = question_bank.get_approved_question(state["current_question_id"])
            if asked_q and asked_q.get("concept_id") in cg.concepts:
                current_concept = asked_q["concept_id"]
        except Exception:
            pass

    # Teacher Rule 3: Flag stuck student after 3 consecutive failures
    failure_streaks = profile.get("failure_streaks", {})
    concept_failures = failure_streaks.get(current_concept or "", 0)
    # Stuck means stuck on THIS topic. (Before, the worst streak on any topic counted, so a student who had
    # moved on to a new topic was still treated as stuck, and the teacher kept getting "stuck" alerts.)
    stuck = concept_failures >= config.STUCK_FAILURE_COUNT
    teacher_alert = bool(stuck or state.get("teacher_alert_triggered", False))

    mode = state.get("mode", "practice")
    plan = state.get("plan", [])
    turn_steps = state.get("turn_steps", [])

    hint_step = state.get("hint_step", 1)
    hint_raised = state.get("hint_raised_this_turn", False)
    last_concept = state.get("last_concept_id")
    # A new topic (or the session's first turn) starts the hint ladder where the learner record says: a student who
    # has mastered the topic skips the orientation step (signature challenge A).
    if (last_concept and current_concept and last_concept != current_concept) or (not last_concept and not hint_raised):
        hint_step = _start_hint(mastery.get(current_concept or ""))

    last_qid = state.get("last_question_id")
    qid = state.get("current_question_id")
    if last_qid and qid and last_qid != qid:
        hint_step = 1

    # Hint progression, at most once per turn: a bigger hint only when the student asks for more help on the
    # same topic ("another hint", "still confused", "just tell me the answer"), or is stuck. A reply such as
    # "okay, thanks" or the student's own explanation keeps the hint level (a repeated mix-up raises it below).
    if mode == "practice" and not plan:
        is_continuing_practice = bool(last_concept and last_concept == current_concept)
        # "huh?" is not a request for a bigger hint: the tutor explains the same step another way instead.
        wants_more_help = (is_continuing_practice and state.get("intent") != "confused"
                           and asks_for_more_help(state.get("query", "")))
        if (stuck or wants_more_help) and not hint_raised and hint_step < config.MAX_HINT_STEPS:
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
                "chapter": _concept_chapter(current_concept) or chapter_out,
            }
        else:
            # N3: If grader encountered an error (e.g. unapproved question), do not run replan
            if grade_res.get("error"):
                # A question that isn't available tells the teacher. A check that R4's tool hooks blocked
                # (budget used up, tools paused) is about the system, not the student, so the alert stays as it was.
                error_alert: bool = True
                if str(grade_res.get("error")).startswith("tool_blocked"):
                    error_alert = teacher_alert
                return {
                    "steps": ["supervisor"],
                    "turn_steps": turn_steps + ["supervisor"],
                    "plan": ["grade_error"],
                    "mastery_map": mastery,
                    "current_concept_id": current_concept,
                    "next_recommended_concept": next_concept,
                    "teacher_alert_triggered": error_alert,
                    "hint_step": hint_step,
                    "hint_raised_this_turn": hint_raised,
                    "last_concept_id": current_concept,
                    "last_question_id": qid,
                    "chapter": _concept_chapter(current_concept) or chapter_out,
                }

            # Grader finished! Supervisor saves quiz result and replans
            score = float(grade_res.get("score", 0.0))
            # N1: quiz results filed under the question's own concept, not the student's current concept
            quiz_concept = grade_res.get("concept_id")
            qid = state.get("current_question_id")
            if not quiz_concept:
                if qid:
                    q = question_bank.get_approved_question(qid)
                    if q and q.get("concept_id"):
                        quiz_concept = q.get("concept_id")
            quiz_concept = quiz_concept or current_concept

            concept_failures = 0
            quiz_res: dict[str, Any] = {}
            if student_id and quiz_concept:
                quiz_res = store.record_quiz_result(student_id, quiz_concept, score, question_id=qid)
                if quiz_res.get("teacher_alert_triggered"):
                    teacher_alert = True
                updated_profile = store.get_profile(student_id)
                mastery = dict(updated_profile.get("mastery_map", {}))
                failure_streaks = updated_profile.get("failure_streaks", {})
                concept_failures = failure_streaks.get(quiz_concept or "", 0)
            if isinstance(grade_res, dict):
                grade_res["already_solved"] = quiz_res.get("already_solved", False)

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
                "chapter": _concept_chapter(current_concept) or chapter_out,
            }

    # Question Setter Mode:
    if state.get("teacher_approval_required"):
        return {
            "steps": ["supervisor"],
            "turn_steps": turn_steps + ["supervisor"],
            "plan": ["draft_questions", "solve_keys", "propose_set"],
            "mastery_map": mastery,
            "current_concept_id": current_concept,
            "next_recommended_concept": next_concept,
            "teacher_alert_triggered": teacher_alert,
            "hint_step": hint_step,
            "hint_raised_this_turn": hint_raised,
            "last_concept_id": current_concept,
            "last_question_id": qid,
            "chapter": _concept_chapter(current_concept) or chapter_out,
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
            "chapter": _concept_chapter(current_concept) or chapter_out,
        }

    # 2. Has diagnostician produced a result?
    if "diagnostician" in turn_steps or "diagnose" in plan:
        diag = state.get("identified_misconception")
        raw_mid = diag.get("id") if (diag and isinstance(diag, dict)) else None
        miscon_id = raw_mid if (raw_mid and isinstance(raw_mid, str) and raw_mid.strip().lower() not in ("null", "none", "nil", "n/a", "")) else None
        last_miscon = state.get("last_misconception_id")

        if not pinned and diag and isinstance(diag, dict) and miscon_id:
            try:
                catalog = getattr(diagnostician, "_load_catalog", lambda: [])()
                for m in catalog:
                    if m.get("id") == miscon_id and m.get("concept_id"):
                        diag_concept = m["concept_id"]
                        if diag_concept in cg.concepts:
                            diag_ch = diag.get("chapter")
                            curr_ch = cg.concepts.get(current_concept, {}).get("chapter")
                            if (current_concept == "concept_reflection_laws" and not lesson_pinned) or (diag_ch and diag_ch != curr_ch):
                                if diag_concept != current_concept:
                                    hint_step, hint_raised = 1, False  # a new topic starts at the smallest hint
                                current_concept = diag_concept
                        break
            except Exception:
                pass

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
            "chapter": _concept_chapter(current_concept) or chapter_out,
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
        "chapter": _concept_chapter(current_concept) or chapter_out,
    }


def node_diagnostician(state: SocraticState) -> dict:
    query = state.get("query", "")
    messages = state.get("messages", [])

    # Guard against cross-chapter misconception bleed:
    # A student working on Electricity (Ch 11) must not receive a Light (Ch 9) misconception banner
    cg = ConceptGraph()
    active_chapter = state.get("chapter")
    current_cid = state.get("current_concept_id")
    if current_cid and current_cid in cg.concepts:
        concept_ch = cg.concepts[current_cid].get("chapter")
        if concept_ch:
            active_chapter = CHAPTER_TITLE_TO_NUM.get(concept_ch, active_chapter)

    # Filter catalog by active chapter to prioritize relevant domain misconceptions
    catalog = getattr(diagnostician, "_load_catalog", lambda: [])()
    chapter_catalog = None
    if active_chapter and catalog:
        active_ch_num = CHAPTER_TITLE_TO_NUM.get(str(active_chapter), str(active_chapter))
        chapter_catalog = [
            m for m in catalog
            if CHAPTER_TITLE_TO_NUM.get(str(m.get("chapter")), str(m.get("chapter"))) == active_ch_num
        ]

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

    diag_res = diagnostician.diagnose_response(contextual_query, chapter_misconceptions=chapter_catalog)
    raw_diag_id = (diag_res.get("identified_misconception_id") or diag_res.get("id")) if isinstance(diag_res, dict) else None
    if not isinstance(diag_res, dict) or not raw_diag_id or (isinstance(raw_diag_id, str) and raw_diag_id.strip().lower() in ("null", "none", "nil", "n/a", "")):
        diag_res = diagnostician.diagnose_response(query, chapter_misconceptions=chapter_catalog)

    miscon_id = None
    miscon_name = None
    miscon_chapter = None
    miscon_desc = None
    miscon_scaffolding = None
    miscon_probe = None
    if isinstance(diag_res, dict):
        raw_id = diag_res.get("identified_misconception_id") or diag_res.get("id")
        if isinstance(raw_id, str) and raw_id.strip().lower() not in ("null", "none", "nil", "n/a", ""):
            miscon_id = raw_id.strip()
            miscon_name = diag_res.get("identified_misconception_name") or diag_res.get("name")
            miscon_chapter = diag_res.get("chapter")
            miscon_desc = diag_res.get("description")
            miscon_scaffolding = diag_res.get("scaffolding_hint")
            miscon_probe = diag_res.get("diagnostic_probe")

    if miscon_id:
        try:
            for m in catalog:
                if m.get("id") == miscon_id:
                    miscon_name = m.get("name") or miscon_name
                    miscon_chapter = m.get("chapter") or miscon_chapter
                    miscon_desc = m.get("description") or miscon_desc
                    miscon_scaffolding = m.get("scaffolding_hint") or miscon_scaffolding
                    miscon_probe = m.get("diagnostic_probe") or miscon_probe
                    break
        except Exception:
            pass

    if miscon_id and active_chapter:
        miscon_ch_num = CHAPTER_TITLE_TO_NUM.get(str(miscon_chapter), str(miscon_chapter))
        active_ch_num = CHAPTER_TITLE_TO_NUM.get(str(active_chapter), str(active_chapter))
        if miscon_ch_num and active_ch_num and miscon_ch_num != active_ch_num:
            miscon_id = None
            miscon_name = None
            miscon_desc = None
            miscon_scaffolding = None
            miscon_probe = None

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
            "description": miscon_desc,
            "scaffolding_hint": miscon_scaffolding,
            "diagnostic_probe": miscon_probe,
        } if miscon_id else None,
        "effective_lesson_applied": effective_lesson,
    }


def search_textbook(query: str, chapter: str | None = None, top_k: int = 4) -> list[dict[str, Any]]:
    """The tutor's textbook tool, under the name R4's permission map knows ("search_textbook").

    It goes through the MCP protocol to the textbook-kb server (HTTP inside Docker, in-memory elsewhere; see
    mcp_tools.py), so the agents use the same MCP tools the tool list documents. The server calls
    textbook_kb.search_textbook at call time, so a test that swaps that function still works, and the hook
    still sees the right tool name.
    """
    return mcp_tools.search_textbook(query, chapter=chapter, top_k=top_k)


def _tutor_search(arguments: dict[str, Any], state: SocraticState) -> list[dict[str, Any]]:
    """One textbook search for the tutor, through R4's tool hooks. A blocked search gives no passages."""
    # Flowchart (each [box] matches a comment below):
    #
    #   [TS1] tool_hooks.run_tool("tutor", search_textbook, arguments, state)
    #          |   the hook checks: may the tutor use it? quiz rule? budget left? paused? then runs it, and logs
    #          |
    #          |-- blocked ("BLOCKED: <reason>") -> [TS2] no passages (the hook has logged why)
    #          v
    #   [TS3] the passages, as the search returned them

    # [TS1] Through the hook, as the agent "tutor".
    result: Any = tool_hooks.run_tool("tutor", search_textbook, arguments, state)
    # [TS2] A blocked call returns a string, not a list: the tutor then hints without textbook passages.
    if tool_hooks.is_blocked(result):
        return []
    # [TS3] The search's own result.
    return result


# The tutor's textbook tools, by the names R4's permission map knows; each goes to the textbook-kb MCP server.
_TEXTBOOK_TOOLS: dict[str, Any] = {
    "search_textbook": search_textbook,
    "get_section": mcp_tools.get_section,
    "get_exemplar": mcp_tools.get_exemplar,
}


def _learner_context(state: SocraticState) -> str | None:
    """What the learner record says about this student, in a line the tutor can use (signature challenge A).
    Pseudonymous: mastery numbers, topic titles and misconception names only. With memory off (E4) the record is
    empty, so every student gets the same help: that is the comparison."""
    student_id = state.get("student_id")
    if not student_id:
        return None
    try:
        profile = LearnerStore().get_profile(student_id)
    except Exception:
        return None
    concepts = ConceptGraph().concepts
    mastery = profile.get("mastery_map") or {}
    here = state.get("current_concept_id")
    parts: list[str] = []
    if here in mastery:
        parts.append(f"quiz mastery of this topic {round(float(mastery[here]) * 100)}% (passing is {round(config.PASSING_MASTERY_THRESHOLD * 100)}%)")
    else:
        parts.append("no quiz on this topic yet")
    mastered = [concepts[c]["title"] for c, v in mastery.items() if c != here and c in concepts and v >= config.PASSING_MASTERY_THRESHOLD]
    if mastered:
        parts.append("has mastered " + ", ".join(mastered[:4]))
    names = {m.get("id"): m.get("name") for m in getattr(diagnostician, "_load_catalog", lambda: [])()}
    seen = []
    for item in profile.get("misconceptions") or []:
        mid = item.get("id") if isinstance(item, dict) else str(item)
        if mid in names:
            seen.append(names[mid] + (" (sorted since)" if isinstance(item, dict) and item.get("resolved") else ""))
    if seen:
        parts.append("mix-ups seen before: " + "; ".join(seen[:3]))
    if profile.get("lessons"):
        parts.append(f"{len(profile['lessons'])} teaching lesson(s) worked for them before")
    return "; ".join(parts)


def _start_hint(mastery: float | None) -> int:
    """Where the hint ladder starts on a topic: a student who has mastered it skips the orientation step."""
    return 2 if (mastery or 0.0) >= config.PASSING_MASTERY_THRESHOLD else 1


def _last_tutor_reply(messages: list) -> str:
    """The tutor's last real reply, skipping the intent check's fixed replies ("No problem...", "Hi!...")."""
    fixed = set(intent_check.REPLIES.values()) | {intent_check.ACK_REPLY}
    for m in reversed(messages or []):
        if getattr(m, "type", "") == "ai":
            text = str(getattr(m, "content", "") or "")
            if text not in fixed:
                return text
    return ""


def _too_similar(a: str, b: str, threshold: float = 0.8) -> bool:
    """Nearly the same reply (ignoring case, spacing and the citation tag)."""
    import difflib

    norm = lambda t: re.sub(r"\s+", " ", re.sub(r"\[NCERT[^\]]*\]", "", t.lower())).strip()
    x, y = norm(a), norm(b)
    return bool(x and y) and difflib.SequenceMatcher(None, x, y).ratio() >= threshold


def node_tutor(state: SocraticState) -> dict:
    query = state.get("query", "")
    hint_tries = state.get("hint_tries", 0) + 1
    chapter = _resolve_chapter(state)
    passages = state.get("retrieved_sections")
    if passages and chapter:
        passages = [p for p in passages if _section_matches_chapter(p.get("section_id"), chapter)]
    # "huh?" or a lesson reply with no topic words of its own ("I don't get it") would search the book for
    # nothing and cite random sections: search with the topic's title instead.
    search_query = query
    topic_title = ConceptGraph().concepts.get(state.get("current_concept_id") or "", {}).get("title")
    if topic_title and (state.get("intent") == "confused" or (state.get("lesson_concept_id") and not intent_check.PHYSICS_WORDS.search(query))):
        search_query = f"{topic_title}: {query}"
    hint_step = state.get("hint_step", 1)
    learner_context = _learner_context(state)

    # Teacher Rule 2: Parallel resistor remediation path
    remediation = None
    query_lower = query.lower()
    if "parallel" in query_lower and any(w in query_lower for w in ("resistor", "resistance", "current")):
        if state.get("teacher_alert_triggered") or hint_step >= 2:
            remediation = "parallel_resistors"
    lesson = state.get("effective_lesson_applied")

    active_miscon = state.get("identified_misconception")
    if not active_miscon and state.get("last_misconception_id"):
        last_mid = state["last_misconception_id"]
        try:
            catalog = getattr(diagnostician, "_load_catalog", lambda: [])()
            for m in catalog:
                if m.get("id") == last_mid:
                    active_miscon = {
                        "id": last_mid,
                        "name": m.get("name"),
                        "chapter": m.get("chapter"),
                        "description": m.get("description"),
                        "scaffolding_hint": m.get("scaffolding_hint"),
                        "diagnostic_probe": m.get("diagnostic_probe"),
                    }
                    break
        except Exception:
            pass

    # The tutor as a ReAct agent over its MCP tools, when a real model is configured (team review, 13 Nov). It
    # decides what to look up; every call goes through the tool hooks and the textbook-kb MCP server.
    hint: str | None = None
    tutor_mode = "fixed"
    if not passages and tutor.react_available():
        try:
            hint, found = tutor.react_hint(
                search_query, chapter, lambda name, args: tool_hooks.run_tool("tutor", _TEXTBOOK_TOOLS[name], args, state),
                hint_level=hint_step, approved_lesson=lesson, remediation=remediation,
                misconception=active_miscon, conversation_history=state.get("messages", []),
                learner_context=learner_context,
            )
            passages = found
            tutor_mode = "react"
        except Exception:
            hint = None  # fall back to the fixed tutor below; the reply still goes out
    if not passages:
        # Both searches go through R4's tool hooks (permission, quiz rule, budget, log), as the tutor's tool.
        passages = _tutor_search({"query": search_query, "chapter": chapter, "top_k": 4}, state)
        if not passages and chapter:
            # A broad retry can recover from incomplete chapter metadata, but it must never import a passage
            # from another chapter into this topic.
            broad_passages = _tutor_search({"query": search_query, "top_k": 4}, state)
            passages = [p for p in broad_passages if _section_matches_chapter(p.get("section_id"), chapter)]
    passages = passages or []

    initial_citations = []
    for p in passages:
        sec = p.get("section_id")
        if sec and sec not in initial_citations:
            initial_citations.append(sec)

    if hint is None:
        hint = tutor.generate_hint(
            student_query=query,
            ncert_passages=passages,
            hint_level=hint_step,
            approved_lesson=lesson,
            remediation=remediation,
            misconception=active_miscon,
            conversation_history=state.get("messages", []),
            learner_context=learner_context,
        )

    # Repeat guard: a reply almost the same as the tutor's last one helps nobody (team testing, 12 Nov: the same
    # concave-mirror hint, turn after turn). Ask once more for a different approach.
    # Only on the first try of a turn: on a leak retry the last reply in the history is this turn's own draft.
    previous: str = _last_tutor_reply(state.get("messages", [])) if hint_tries == 1 else ""
    if previous and _too_similar(hint, previous):
        retry = tutor.generate_hint(
            student_query=query + "\n\n(Your last reply was nearly the same as this one. Do not repeat it. Change approach: "
            "use an everyday example, or ask a smaller and easier question that leads to the same idea.)",
            ncert_passages=passages,
            hint_level=hint_step,
            approved_lesson=lesson,
            remediation=remediation,
            misconception=active_miscon,
            conversation_history=state.get("messages", []),
            learner_context=learner_context,
        )
        if retry and not _too_similar(retry, previous):
            hint = retry

    all_citations = _extract_section_ids(initial_citations, hint)

    return {
        "steps": ["tutor"],
        "turn_steps": state.get("turn_steps", []) + ["tutor"],
        "response": hint,
        "citations": all_citations,
        "retrieved_sections": passages,
        "hint_tries": hint_tries,
        "answer_leak_flag": False,
        "tutor_mode": tutor_mode,
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
        if section_id and _section_matches_chapter(section_id, _resolve_chapter(state)):
            retrieved_ids.append(str(section_id))
    validated_citations: list[str] = keep_retrieved_citations(citations, retrieved_ids)
    response = _repair_ncert_citation_text(response, retrieved_ids)

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
    # The graph's state goes along, so the grader's checks run through R4's tool hooks as the agent "grader".
    res = grader.grade_answer(attempt, gold_answer, is_numeric=is_numeric, state=state)
    res["concept_id"] = question_concept

    feedback = res.get("feedback") or ("Correct! Well done." if res.get("is_correct") else "Not quite right. Let's review the concept.")
    # A check the hook blocked (budget used up, tools paused, session facts missing) is not a wrong answer:
    # say so, and record no grade (the "error" key makes the supervisor skip the replan).
    if str(res.get("error", "")).startswith("tool_blocked"):
        feedback = grader.CANNOT_CHECK_FEEDBACK
        res["feedback"] = grader.CANNOT_CHECK_FEEDBACK

    return {
        "steps": ["grader"],
        "turn_steps": state.get("turn_steps", []) + ["grader"],
        "grade_result": res,
        "response": feedback,
        "current_concept_id": question_concept or concept_id,
    }


def node_question_setter(state: SocraticState) -> dict:
    """The question setter (R4 plumbing PR-2, decision I2): the model drafts the questions, the SOLVER computes
    every answer key, and the drafts wait for the teacher as ONE set on the approval gate's own thread.

    Nothing pauses in this graph: the set waits on "qbset:<set_id>" (approval_gate), so this run ends at once
    (question_setter -> END). No answer key is ever put in this graph's state.
    """
    # Flowchart (each [box] matches a comment below):
    #
    #   [QS1] which concept (the teacher's pick), and how many questions?   no or unknown concept -> [QS4]
    #   [QS2] one model call per question (easy, medium, hard); the solver keys each draft (solver_key)
    #   [QS3] any draft left?                                             no -> [QS4], nothing is sent
    #         yes -> approval_gate.propose_set(drafts): ONE set, waiting for the teacher
    #   [QS4] the summary: ok, the set id, the question ids, every refusal with its difficulty. Never a key.

    # This turn's trajectory, plus what the summary will report (filled in below).
    turn_steps: list[str] = state.get("turn_steps", []) + ["question_setter"]
    # Every refused draft: {"difficulty", "error"}.
    refused: list[dict[str, Any]] = []
    # The set that went to the teacher ("" if none did), and its question ids.
    set_id: str = ""
    question_ids: list[str] = []
    # One sentence for the teacher about what happened.
    note: str = ""
    # How many of the drafts are the agent's fixed fallback questions (the model gave none).
    fallback_count: int = 0

    # [QS1] the concept the teacher asked for, and the set size (QUESTION_SET_SIZE unless the request says).
    concept: Any = state.get("current_concept_id")
    count: int = QUESTION_SET_SIZE
    asked_size: Any = state.get("question_set_size")
    if isinstance(asked_size, int) and not isinstance(asked_size, bool):
        count = asked_size
    if not isinstance(concept, str) or concept == "":
        note = "No concept was given, so no questions were drafted."
    elif concept not in question_bank_server.load_concept_ids():
        note = "Unknown concept '" + concept + "', so no questions were drafted."
    else:
        # [QS2] one model call per draft; the solver computes each key, and refuses what it can't compute.
        made: dict[str, Any] = solver_key.drafts_for_concept(concept, count, question_setter.select_question)
        drafts: list[dict[str, Any]] = made["drafts"]
        fallback_count = made["fallback_count"]
        for item in made["refused"]:
            refused.append({"difficulty": item["difficulty"], "error": item["error"]})
        # [QS3] nothing left to send: the teacher gets nothing to approve.
        if len(drafts) == 0:
            note = "No draft could be keyed by the solver, so nothing was sent to the teacher."
        else:
            # The drafts go to the teacher as one set (the question-bank checks run inside propose_set).
            proposed: dict[str, Any] = approval_gate.propose_set(drafts)
            # A draft the bank refused (e.g. a duplicate) is reported with its difficulty.
            for item in proposed.get("refused", []):
                position: Any = item.get("draft")
                difficulty: str = ""
                if isinstance(position, int) and 0 <= position < len(drafts):
                    difficulty = drafts[position]["difficulty"]
                refused.append({"difficulty": difficulty, "error": str(item.get("error", ""))})
            if proposed.get("ok") is True:
                set_id = str(proposed["set_id"])
                question_ids = list(proposed["question_ids"])
                note = (str(len(question_ids)) + " question(s) are waiting for the teacher's approval in set "
                        + set_id + ".")
                # Say so when fixed fallback questions stood in for the model's own (e.g. the model is down).
                if fallback_count > 0:
                    note = (note + " " + str(fallback_count) + " of the drafts were fixed fallback questions, "
                            "because the model gave no usable question.")
            else:
                note = str(proposed.get("error", "The set could not be sent to the teacher."))

    # [QS4] what the caller (the teacher's request) learns. Ids and reasons only, never an answer key.
    summary: dict[str, Any] = {
        "ok": set_id != "",
        "set_id": set_id,
        "question_ids": question_ids,
        "refused": refused,
        "note": note,
    }
    return {
        "steps": ["question_setter"],
        "turn_steps": turn_steps,
        "teacher_approval_required": False,
        "response": note,
        "proposed_set": summary,
    }


# --- Routing Functions ---

def route_guardrail(state: SocraticState) -> str:
    if state.get("injection_detected") or state.get("distress_detected") or state.get("off_topic"):
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
    # "huh?" has nothing to diagnose (it used to flag a mix-up the student never made).
    if "diagnostician" not in turn_steps and state.get("intent") != "confused" \
            and ("diagnose" in plan or not state.get("identified_misconception")):
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
    # PR-2: the question setter's set waits on the approval gate's own thread, so this run ends here.
    workflow.add_edge("question_setter", END)
    workflow.add_conditional_edges(
        "output_guardrail",
        route_output,
        {"tutor": "tutor", END: END},
    )

    return workflow.compile(checkpointer=checkpointer)
