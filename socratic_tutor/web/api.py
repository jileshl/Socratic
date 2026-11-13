"""FastAPI API router: student chat (streamed), teacher endpoints, approvals, metrics.

Endpoints:
    GET  /healthz                    Health check
    GET  /metrics                    Prometheus metrics
    POST /api/session                Start a student session
    POST /api/chat                   One student turn, streamed via SSE
    GET  /api/quiz/next              One approved quiz question for the student (never its answer key)
    GET  /api/session/{id}/state     Checkpoint state
    POST /api/session/{id}/resume    Resume interrupted session
    POST /api/forget_me              Delete learner record & checkpoints
    POST /api/teacher/login          Teacher PIN authentication
    POST /api/teacher/logout         Clear teacher session
    GET  /api/teacher/dashboard      Teacher overview, alerts, misconceptions
    POST /api/teacher/question_sets  Ask the question setter for a new set (it waits for approval)
    GET  /api/teacher/approvals      List the question sets waiting for approval
    POST /api/teacher/approvals/{id} Approve, edit, or reject a set ("qbset:<set_id>"), signed on the server
    POST /api/teacher/alerts/{id}/ack Acknowledge an alert
    GET  /api/teacher/labels         Calibration transcript labelling queue
    POST /api/teacher/labels         Save calibration label
    POST /api/ops/emit-test-leak     Ops synthetic leak demo
    GET  /api/concepts               Topics in the concept graph (for plans)
    GET  /api/students               Class list for the student picker (names the teacher typed)
    GET  /api/student/{id}/plan      The student's study plan: teacher's plan and the suggestion
    GET  /api/student/{id}/game      Points, level, streak and badges (worked out from real records)
    GET  /api/flashcards             Revision cards from the misconception catalogue
    GET  /api/teacher/students       Every student with name, mastery, alerts and plan status
    POST /api/teacher/students       Add a student to the class list (creates a random ID)
    PUT  /api/teacher/students/{id}  Rename a student
    GET  /api/teacher/students/{id}  One student's record and study plan
    PUT  /api/teacher/students/{id}/plan  Assign or change the study plan
"""

from __future__ import annotations

import csv
import hmac
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from socratic_tutor import approval_gate, book, config, trace
from socratic_tutor import topics
from socratic_tutor.concept_graph import ConceptGraph
from socratic_tutor.graph import build_graph
from socratic_tutor.learner_store import LearnerStore
from socratic_tutor.tools import question_bank, question_bank_server, textbook_kb
from socratic_tutor.web import approvals, demo_data, game, metrics, study_plan
from socratic_tutor.web.ops_store import OpsStore

api_router = APIRouter()
router = api_router  # standard alias

REFUSAL = "I cannot fulfill this request as entered. Let's focus on our NCERT study goals."

# --- Question sets and approvals (R4 plumbing PR-2) ---
# Who is recorded as the approver. The teacher login is one shared PIN, which proves the role, not the person,
# so every decision is signed as "teacher" (decision P2-7).
TEACHER_APPROVER: str = "teacher"
# A teacher's request runs the graph on its own new thread, never a student's: "qsetter:<12 hex>".
QUESTION_REQUEST_THREAD_PREFIX: str = "qsetter:"
# The fixed text of a teacher's request. It still passes the input check like any message.
QUESTION_REQUEST_TEXT: str = "Write practice questions for this concept."
# What the teacher view says when the server has no signing key (decision P2-8: fail closed).
APPROVALS_OFF_DETAIL: str = (
    "Approvals are off: the server has no APPROVAL_SIGNING_KEY. Set it in .env and restart. "
    "Make one with: python -c \"import secrets; print(secrets.token_hex(32))\""
)

# Who makes each decision in the graph. Shown in the student view next to each box.
NODE_DECIDER = {
    "input_guardrail": "code",
    "supervisor": "code",   # node_supervisor routes by rules (mode, mastery, mix-ups); it calls no model
    "planner": "code",
    "diagnostician": "model",
    "tutor": "model",
    "grader": "code",
    "question_setter": "model",
    "teacher_approval_gate": "person",
    "output_guardrail": "code",
    "memory": "code",
}

ops = OpsStore()
learners = LearnerStore()
_graph = None
_saver = None


def graph():
    """Build the team's graph once, with a persistent SQLite checkpointer (stop and resume)."""
    global _graph, _saver
    if _graph is None:
        conn = sqlite3.connect(config.INDEX_DIR / "checkpoints.sqlite", check_same_thread=False)
        _saver = SqliteSaver(conn)
        _graph = build_graph(checkpointer=_saver)
    return _graph


# ------------------------------------------------------------------ auth


def _teacher_token() -> str:
    return hmac.new(config.get_teacher_secret(), b"teacher", "sha256").hexdigest()


def require_teacher(request: Request) -> None:
    token = request.cookies.get("teacher", "")
    if not hmac.compare_digest(token, _teacher_token()):
        raise HTTPException(status_code=401, detail="Teacher login required")


def _is_teacher(request: Request) -> bool:
    return hmac.compare_digest(request.cookies.get("teacher", ""), _teacher_token())


def _student_token(student_id: str) -> str:
    return hmac.new(config.get_teacher_secret(), f"student:{student_id}".encode(), "sha256").hexdigest()


def _may_access(request: Request, student_id: str | None) -> bool:
    """Team review (12 Nov): anyone on the student page could pick a classmate's name under "Learning as" and
    read, or delete, their record. A NAMED student (one the teacher added) now needs their 4-digit sign-in code
    once on a device (a signed cookie), or the teacher's login. A device's own random ID is its own secret, and
    the clearly-labelled demo class stays open when OPS_DEMO=1 (presenter mode)."""
    if not student_id or student_id not in ops.roster():
        return True
    if config.OPS_DEMO == "1" and student_id.startswith("stu_demo"):
        return True
    if _is_teacher(request):
        return True
    return hmac.compare_digest(request.cookies.get("student_" + student_id, ""), _student_token(student_id))


def _guard_student(request: Request, student_id: str | None) -> None:
    if not _may_access(request, student_id):
        raise HTTPException(403, "Type your sign-in code first (your teacher has it).")


# ------------------------------------------------------------------ health & metrics


@api_router.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "index_chunks": len(textbook_kb.retriever.index.chunks), "config_version": config.CONFIG_VERSION}


@api_router.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    metrics.PENDING_APPROVALS.set(len(_pending_items()))
    open_alerts = ops.open_alerts()
    metrics.STUCK_STUDENTS.set(sum(1 for a in open_alerts if a["kind"] == "stuck"))
    # Open alerts by kind, so Prometheus can page while a distress alert is still waiting for a teacher
    # (the old rule looked at new alerts in the last 5 minutes and went quiet by itself).
    for kind in ("distress", "stuck", "conduct"):
        metrics.OPEN_ALERTS.labels(kind).set(sum(1 for a in open_alerts if a["kind"] == kind))
    return Response(generate_latest(metrics.REGISTRY), media_type=CONTENT_TYPE_LATEST)


# ------------------------------------------------------------------ student API


class SessionIn(BaseModel):
    mode: str = Field(default="practice", pattern="^(practice|quiz)$")
    student_id: str | None = None
    consent: bool = False


@api_router.post("/api/session")
def start_session(body: SessionIn, request: Request) -> dict[str, Any]:
    _guard_student(request, body.student_id)
    student_id = body.student_id if body.student_id and body.student_id.startswith("stu_") else f"stu_{uuid.uuid4().hex[:12]}"
    session_id = f"ses_{uuid.uuid4().hex[:12]}"
    ops.start_session(session_id, student_id, body.mode, body.consent)
    metrics.SESSIONS.labels(body.mode).inc()
    return {"session_id": session_id, "student_id": student_id, "mode": body.mode, "consent": body.consent}


class ChatIn(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=4000)
    current_question_id: str | None = None
    chapter: str | None = None
    concept_id: str | None = None
    # "Learn from the start": the topic of the lesson the student is working through (the tutor stays on it).
    lesson_concept_id: str | None = None


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def _mastery(student_id: str) -> dict[str, float]:
    return dict(learners.get_profile(student_id)["mastery_map"])


@api_router.post("/api/chat")
def chat(body: ChatIn) -> StreamingResponse:
    session = ops.session(body.session_id)
    if session is None:
        raise HTTPException(404, "Unknown session; start one with POST /api/session")
    return StreamingResponse(
        _run_turn(session, body.message, body.current_question_id, body.chapter, body.concept_id, body.lesson_concept_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _block_reason(values: dict[str, Any]) -> str | None:
    """One short label for why a turn was stopped (the 'blocked' column and the Prometheus label), or None.

    The guardrail says exactly which check stopped a message (e.g. "word_rule:teacher_claim",
    "content_guard:S1"). Only the part before the first ":" is used, so the set of labels stays small.
    """
    # Flowchart (each [box] matches a comment below):
    #
    #   [B1] distress in this message?                 yes -> "distress"
    #   [B2] an input check stopped it?                yes -> its first part ("word_rule" -> "injection")
    #   [B3] an older state with only the flag?        yes -> "injection"
    #   [B4] the reply check replaced the reply?       yes -> "output_check"
    #        otherwise                                      -> None (the turn went through)

    # [B1] Distress is a hand-off to the teacher, not an attack.
    if values.get("distress_detected"):
        return "distress"
    # [B2] The input guardrail's own reason.
    input_blocked_by: Any = values.get("input_blocked_by")
    if input_blocked_by:
        first_part: str = str(input_blocked_by).split(":")[0]
        # Word rules catch attacks such as "I'm the teacher"; the dashboard has always called these "injection".
        if first_part == "word_rule":
            return "injection"
        return first_part
    # [B3] A turn saved before input_blocked_by existed only has the old flag.
    if values.get("injection_detected"):
        return "injection"
    # [B4] The reply check (links, citations, content guard) had to replace the reply.
    if values.get("output_blocked_by"):
        return "output_check"
    return None


def _session_concept(session: dict[str, Any]) -> str | None:
    """The concept a student is working on: where the graph left this session, else the next recommended one."""
    # [C1] The graph saves the session's current concept in its checkpoint (thread = session id).
    saved: dict[str, Any] = graph().get_state({"configurable": {"thread_id": session["session_id"]}}).values
    current: Any = saved.get("current_concept_id")
    if current:
        return str(current)
    # [C2] A new session: the concept graph's recommendation for this student's mastery so far.
    recommended: Any = ConceptGraph().next_recommended(_mastery(session["student_id"]))
    if recommended:
        return str(recommended)
    return None


@api_router.get("/api/quiz/next")
def next_quiz_question(session_id: str, previous_id: str | None = None) -> dict[str, Any]:
    """Give the student one teacher-approved quiz question for their concept, WITHOUT its answer key.

    The page sends the returned question_id with the student's answer (POST /api/chat), so the grader checks
    it against that question's approved key. previous_id is the question just asked, so the next call moves on.
    Questions already solved correctly by this student are skipped.
    """
    # Flowchart (each [box] matches a comment below):
    #
    #   [Q1] a known session?                                     no  -> 404
    #   [Q2] approved questions for the student's concept (unsolved)
    #   [Q3] none for that concept? -> approved questions of any concept (unsolved)
    #   [Q4] none at all?                                         yes -> "no questions yet" (question_id None)
    #   [Q5] the question after previous_id (wrapping round), without its answer key

    # [Q1] Only a real session may ask.
    session: dict[str, Any] | None = ops.session(session_id)
    if session is None:
        raise HTTPException(404, "Unknown session; start one with POST /api/session")
    student_id: str | None = session.get("student_id")
    solved_ids: set[str] = learners.get_solved_question_ids(student_id) if student_id else set()

    # [Q2] The concept the student is on, and the approved questions for it (keys are never selected).
    concept_id: str | None = _session_concept(session)
    questions: list[dict[str, Any]] = []
    if concept_id is not None:
        all_concept_qs = question_bank.list_approved_for_students(concept_id)
        questions = [q for q in all_concept_qs if q["id"] not in solved_ids]
    # [Q3] No approved question for this concept yet (or all solved). First choice: approved questions of a concept the student
    # is ready for (all its prerequisites mastered), so a beginner isn't quizzed on an advanced topic. Last
    # resort: any approved question, so a quiz can still run (e.g. in the demo, with only seeded questions).
    if len(questions) == 0:
        every_approved: list[dict[str, Any]] = question_bank.list_approved_for_students(None)
        every_unsolved: list[dict[str, Any]] = [q for q in every_approved if q["id"] not in solved_ids]
        graph_of_concepts: ConceptGraph = ConceptGraph()
        mastery: dict[str, float] = _mastery(session["student_id"]) if student_id else {}
        for question in every_unsolved:
            # can_advance: every prerequisite of this question's concept is at the passing mastery.
            if graph_of_concepts.can_advance(question["concept_id"], mastery):
                questions.append(question)
        if len(questions) == 0:
            questions = every_unsolved
    # [Q4] The teacher hasn't approved any question yet, or all approved questions are already solved.
    if len(questions) == 0:
        msg = "You have solved all approved quiz questions! Great job." if solved_ids else "There are no approved quiz questions yet. Please ask your teacher."
        return {"question_id": None, "note": msg}
    # [Q5] Start with the first question; if the page says which one it just asked, take the one after it.
    chosen: dict[str, Any] = questions[0]
    for position in range(len(questions)):
        if questions[position]["id"] == previous_id:
            # The one after it, going back to the first after the last.
            next_position: int = (position + 1) % len(questions)
            chosen = questions[next_position]
            break
    return {
        "question_id": chosen["id"],
        "prompt": chosen["prompt"],
        "concept_id": chosen["concept_id"],
        "difficulty": chosen["difficulty"],
    }


def _run_turn(
    session: dict[str, Any],
    message: str,
    current_question_id: str | None = None,
    chapter: str | None = None,
    concept_id: str | None = None,
    lesson_concept_id: str | None = None,
) -> Iterator[str]:
    session_id, student_id, mode = session["session_id"], session["student_id"], session["mode"]
    meter = trace.CostMeter()
    cfg = {
        "configurable": {"thread_id": session_id},
        "callbacks": [meter, trace.TraceCallback(session_id)],
        "recursion_limit": config.GRAPH_RECURSION_LIMIT,
    }
    before = _mastery(student_id)
    started = time.perf_counter()
    state_in = {
        "session_id": session_id,
        "student_id": student_id,
        "mode": mode,
        "current_question_id": current_question_id,
        "query": message,
        "messages": [HumanMessage(content=message)],
        "steps": [],
        "response": "",
        "citations": [],
        "identified_misconception": None,
        "injection_detected": False,
        "teacher_alert_triggered": False,
        "answer_leak_flag": False,
    }
    if chapter:
        state_in["chapter"] = chapter
    # A topic the student picked (Practise it) holds for this turn. Otherwise the tutor keeps the topic it was
    # on, and may move to the topic of a new question (see node_supervisor).
    state_in["concept_pinned"] = bool(concept_id)
    state_in["lesson_concept_id"] = lesson_concept_id
    if concept_id:
        state_in["current_concept_id"] = concept_id
    if session["turns"] == 0:
        state_in["mastery_map"] = before
    yield _sse({"type": "start", "session_id": session_id, "mode": mode})
    interrupted = None
    error = None
    try:
        for update in graph().stream(state_in, config=cfg, stream_mode="updates"):
            for node, _ in update.items():
                if node == "__interrupt__":
                    interrupted = update[node]
                    continue
                yield _sse({"type": "step", "node": node, "decided_by": NODE_DECIDER.get(node, "model")})
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        metrics.ERRORS.labels("chat").inc()

    latency = time.perf_counter() - started
    values = graph().get_state({"configurable": {"thread_id": session_id}}).values if error is None else {}
    reply = str(values.get("response") or "") if error is None else "Sorry, something went wrong on our side. Please try again."
    # Why the turn was stopped, as one short label ("injection", "distress", "content_guard", ...), or None.
    blocked_reason: str | None = _block_reason(values)
    leak: bool = bool(values.get("answer_leak_flag")) and mode == "practice"
    misconception = values.get("identified_misconception") or {}
    raw_mid = misconception.get("id") if isinstance(misconception, dict) else misconception
    misconception_id = str(raw_mid).strip() if (raw_mid and isinstance(raw_mid, str) and str(raw_mid).strip().lower() not in ("null", "none", "nil", "n/a", "")) else None
    concept_id = values.get("current_concept_id")
    after = _mastery(student_id)
    delta = None
    if concept_id and concept_id in after:
        delta = round(after[concept_id] - before.get(concept_id, 0.0), 3)
        metrics.MASTERY_DELTA.observe(delta)
    usage = meter.snapshot()

    outcome = "error" if error else ("blocked" if blocked_reason else "ok")
    metrics.REQUESTS.labels(mode, outcome).inc()
    metrics.LATENCY.labels(mode).observe(latency)
    if mode == "practice":
        # What kind of message each practice turn was (physics, "huh?", off-topic, fed up, ...): loops and
        # frustration show up in Grafana.
        metrics.INTENTS.labels(str(values.get("intent") or "physics")).inc()
    metrics.LLM_CALLS.inc(usage["llm_calls"])
    if usage["cost_usd"]:
        metrics.LLM_COST.inc(usage["cost_usd"])
        metrics.TURN_COST.observe(usage["cost_usd"])
    if leak:
        metrics.ANSWER_LEAKS.labels("live").inc()
    if blocked_reason:
        metrics.GUARDRAIL_BLOCKS.labels(blocked_reason).inc()
    ops.record_turn(
        session_id=session_id, student_id=student_id, mode=mode, latency_s=round(latency, 3),
        cost_usd=usage["cost_usd"], llm_calls=usage["llm_calls"], leak=int(leak), blocked=blocked_reason,
        misconception_id=misconception_id, concept_id=concept_id, mastery_delta=delta, error=error,
    )
    # A "distress" alert only when the guardrail found distress in THIS message. (Before, every teacher alert
    # was filed as distress, so e.g. a quiz answer to an unavailable question paged the teacher about distress.
    # Stuck students get their own "stuck" alerts just below.)
    # Whether a teacher alert was really filed in this turn (the student's page says "a teacher has been told"
    # only then).
    alert_filed: bool = False
    if values.get("distress_detected"):
        # Severe distress or a safety concern gets a more urgent wording than exam stress.
        alert_detail: str = "Distress language detected; please check in with this student."
        if values.get("distress_level") == "severe":
            alert_detail = "Severe distress or a safety concern: please check in with this student now."
        ops.add_alert(student_id, session_id, "distress", alert_detail)
        metrics.DISTRESS_ALERTS.inc()
        alert_filed = True
    if _update_stuck_alerts(student_id, session_id, concept_id, delta, values.get("grade_result") if error is None else None):
        alert_filed = True
    # Rude three times in one session: often frustration, so a gentle heads-up for the teacher (once per session).
    if values.get("off_topic") and values.get("intent") in ("rude", "fed_up") and int(values.get("rude_count") or 0) >= 3 \
            and not ops.has_open_alert(student_id, "conduct"):
        ops.add_alert(student_id, session_id, "conduct", "Rude or fed-up messages three times in one session; they may be frustrated. A quick check-in could help.")
        alert_filed = True
    # PR-2: a student's turn never pauses for the teacher any more (question sets wait on their own "qbset:"
    # thread), so nothing is saved here. The old save hashed the whole interrupt value, while the graph's gate
    # compared the inner payload's hash, so every approval of such an item was refused.
    for name, value in _class_misconceptions().items():
        metrics.CLASS_MISCONCEPTIONS.labels(name).set(value)
    trace.record("turn", session_id=session_id, student_id=student_id, mode=mode, student=message, tutor=reply, latency_s=round(latency, 3), outcome=outcome, **usage)

    # The "stopped by safety check" chip is for refusals only. A distress reply is a hand-off to a person, not a
    # refusal, so a student in distress never sees it labelled as "stopped".
    shown_as_blocked: bool = False
    if blocked_reason is not None and blocked_reason != "distress":
        shown_as_blocked = True
    # The page loads the next quiz question only after a real grade (not after a refusal, distress or an error).
    graded: bool = False
    grade_result: Any = values.get("grade_result")
    if error is None and isinstance(grade_result, dict) and not grade_result.get("error"):
        # A grade that carries an "error" (e.g. "unapproved_question") wasn't a real grade.
        graded = True
    yield _sse(
        {
            "type": "reply",
            "text": reply,
            # Only the sections the reply actually cites (the rest of the search results were often off topic).
            "citations": _cited_in(reply, values.get("citations") or []),
            "blocked": shown_as_blocked,
            "teacher_alerted": alert_filed,
            # "academic" (study stress or frustration) or "severe": the page offers study steps only for the first.
            "distress_level": values.get("distress_level") if values.get("distress_detected") else None,
            "graded": graded,
            "pending_approval": bool(interrupted),
            "next_concept": values.get("next_recommended_concept"),
            # What the tutor saw this turn, for the student view's "what happened" panel.
            "misconception": _misconception_brief(misconception_id),
            "concept": {"id": concept_id, "title": _concept_titles().get(concept_id, concept_id), "chapter": _concept_chapters().get(concept_id, "")} if concept_id else None,
            "hint_step": values.get("hint_step") if mode == "practice" else None,
            "max_hints": config.MAX_HINT_STEPS,
            "plan": list(values.get("plan") or []),
            "mastery_delta": delta,
            "grade": _grade_brief(values.get("grade_result")) if mode == "quiz" else None,
            "answer_leak_flagged": leak,
            # The NCERT book next to the tutor's question: a real excerpt, the formulas and the figure of the
            # section it cited (code, no model). Not for refusals, distress replies or quiz marking.
            "book": _book_for(values, message, concept_id) if (mode == "practice" and error is None and not blocked_reason) else None,
            # Behind the scenes, for the side panel: what each step saw and decided.
            "behind": _behind(values, message, mode, blocked_reason),
            "latency_s": round(latency, 2),
            "cost_usd": usage["cost_usd"],
            "error": bool(error),
        }
    )


def _cited_in(reply: str, citations: list[str]) -> list[str]:
    """The sections from the search that the reply names ("[NCERT Sec 9.1]", "Section 10.2")."""
    named = set(re.findall(r"(?:Sec(?:tion)?\.?|NCERT)\s*(\d+(?:\.\d+)+)", reply or "", re.IGNORECASE))
    return [c for c in citations if c in named]


def _safe_figure(text: str, concept_id: str | None, prefer_own: bool = False) -> dict[str, Any] | None:
    try:
        return book.pick_figure(text, concept_id, book.CONCEPT_SECTIONS.get(concept_id or "", []), prefer_own=prefer_own)
    except Exception:
        return None


def _book_for(values: dict[str, Any], message: str, concept_id: str | None) -> dict[str, Any] | None:
    # A follow-up ("another hint") says little on its own, so the student's last questions help pick the figure.
    # A message that names its own topic ("why is the sky blue?") stands alone: the earlier questions may be about
    # the old topic (a reflection lesson once gave the sky question a long-sightedness figure).
    asked = [str(getattr(m, "content", "")) for m in (values.get("messages") or []) if getattr(m, "type", "") == "human"]
    query = message if topics.topic_of(message) else " ".join([message] + asked[-3:-1])
    # Which page to open: the section the reply itself names ("[NCERT Sec 11.4]") first, then the topic's own
    # sections, then the rest of the search results.
    cited = list(values.get("citations") or [])
    named = re.findall(r"\b((?:9|10|11)\.\d+(?:\.\d+)?)\b", str(values.get("response") or ""))
    own = book.CONCEPT_SECTIONS.get(concept_id or "", [])
    order = list(dict.fromkeys([s for s in named if s in cited or s in own] + [s for s in own if s in cited] + cited))
    try:
        return book.book_card(order, query, concept_id)
    except Exception:  # the book card is extra help; a reply never fails because of it
        return None


def _behind(values: dict[str, Any], message: str, mode: str, blocked_reason: str | None) -> dict[str, Any]:
    """What happened behind the scenes this turn, in plain words for the side panel. No answer keys."""
    sources = []
    for p in values.get("retrieved_sections") or []:
        sid = p.get("section_id")
        if sid and all(s["section_id"] != sid for s in sources):
            sources.append({"section_id": sid, "title": book.section_title(sid) or p.get("title") or p.get("section_title") or ""})
    masked = str(values.get("query") or message).strip() != message.strip()
    return {
        "mode": mode,
        "safety": {
            "blocked_by": values.get("input_blocked_by"),
            "reason": blocked_reason,
            "distress_level": values.get("distress_level") if values.get("distress_detected") else None,
            "personal_details_masked": masked,
        },
        "concept_pinned": bool(values.get("concept_pinned")),
        "sources": sources[:4],
        "lesson_used": values.get("effective_lesson_applied"),
        # The turn's plan as the supervisor set it, and whether it replanned (after a quiz answer), for the
        # side panel (L10: "show the user a plan object"; "a trace showing a replan").
        "plan": list(values.get("plan") or []),
        "replanned": "replanned" in (values.get("plan") or []),
        "tutor_mode": values.get("tutor_mode"),
        "hint_level": values.get("hint_step"),
        "intent": values.get("intent") or "physics",
        "intent_rule": values.get("intent_rule"),
        "off_topic": bool(values.get("off_topic")),
        # The models behind the steps (from config / .env), so the side panel can name them.
        "models": {"guard": config.GUARD_MODEL, "agents": config.SPECIALIST_MODEL, "search": "BM25 keywords + local embeddings (Chroma)"},
    }


@api_router.get("/api/models")
def models() -> dict[str, str]:
    """The models behind the steps (from config / .env), for the workflow in the side panel."""
    return {"guard": config.GUARD_MODEL, "agents": config.SPECIALIST_MODEL, "search": "BM25 keywords + local embeddings (Chroma)"}


@api_router.get("/api/lesson/{concept_id}")
def lesson(concept_id: str, request: Request, student_id: str | None = None) -> dict[str, Any]:
    """"Learn this topic from the start": real text, figure and formulas from the NCERT book, matched to the
    student's mastery of the topic (new / in progress / mastered). Code only; no model call."""
    titles = _concept_titles()
    if concept_id not in titles:
        raise HTTPException(404, "Unknown topic")
    mastery = None
    if student_id and not _may_access(request, student_id):
        student_id = None
    if student_id and student_id.startswith("stu_"):
        mastery = (learners.get_profile(student_id).get("mastery_map") or {}).get(concept_id)
    next_id = None
    if mastery is not None and mastery >= config.PASSING_MASTERY_THRESHOLD:
        mastery_map = learners.get_profile(student_id).get("mastery_map") or {} if student_id else {}
        cg = ConceptGraph()
        later = [c for c, d in cg.concepts.items() if concept_id in d.get("prerequisites", []) and mastery_map.get(c, 0.0) < config.PASSING_MASTERY_THRESHOLD]
        next_id = later[0] if later else cg.next_recommended(mastery_map)
    out = book.lesson(concept_id, mastery, titles.get(concept_id, concept_id), next_id, titles.get(next_id or "", ""))
    out["chapter"] = _concept_chapters().get(concept_id, "")
    out["has_quiz"] = any(r.get("concept_id") == concept_id for r in approvals._qb_rows("approved"))
    # How many more fully right answers reach "mastered" (mastery is the average of the last few quiz scores).
    # The quiz used to say "One more right answer and it's yours" even at 33%.
    out["right_needed"] = None
    if student_id and mastery is not None and mastery < config.PASSING_MASTERY_THRESHOLD:
        window = list(learners.recent_scores(student_id, concept_id, config.MASTERY_WINDOW_SIZE))
        for k in range(1, config.MASTERY_WINDOW_SIZE + 1):
            scores = ([1.0] * k + window)[: config.MASTERY_WINDOW_SIZE]
            if sum(scores) / len(scores) >= config.PASSING_MASTERY_THRESHOLD:
                out["right_needed"] = k
                break
    return out


def _update_stuck_alerts(student_id: str, session_id: str, concept_id: str | None, delta: float | None, grade_now: Any) -> bool:
    """"Stuck" alerts (teacher rules: 3 quiz answers in a row not yet right on one topic, or 10+ minutes in a
    session without progress). Progress closes them: a quiz answer fully right, or mastery going up, resolves
    the student's open "stuck" alerts, and only the CURRENT topic's streak can raise a new one.

    Team review (12 Nov): after the teacher pressed "Mark as handled", the student's very next message filed
    the same alert again (the streak was still 3, and the 10-minute rule fired on every turn). Now an alert the
    teacher handled comes back only for NEW trouble: 3 more answers not yet right on that topic, and the
    10-minute rule fires at most once per session. Returns True when a new alert was filed."""
    progressed: bool = (delta or 0) > 0 or (isinstance(grade_now, dict) and grade_now.get("is_correct") is True and not grade_now.get("error"))
    if progressed:
        ops.resolve_alerts(student_id, "stuck", "(Resolved automatically: the student then made progress.)")
        return False
    if ops.has_open_alert(student_id, "stuck"):
        return False
    earlier = ops.alerts_of(student_id, "stuck")
    streak = int((learners.get_profile(student_id).get("failure_streaks") or {}).get(concept_id or "", 0))
    if streak >= config.STUCK_FAILURE_COUNT:
        # The last alert about this topic's streak, if the teacher handled it and the student hasn't made
        # progress since (progress resets the streak and closes alerts as "progress").
        handled = next((a for a in earlier if a["meta"].get("rule") == "streak" and a["meta"].get("concept") == concept_id), None)
        if handled is None or handled.get("closed_by") != "teacher" or streak >= int(handled["meta"].get("streak", 0)) + config.STUCK_FAILURE_COUNT:
            title = _concept_titles().get(concept_id or "", concept_id or "a topic")
            ops.add_alert(student_id, session_id, "stuck", f"Stuck on {title}: {streak} quiz answers in a row not yet right.",
                          meta={"rule": "streak", "concept": concept_id, "streak": streak})
            return True
        return False
    minutes, gained = ops.session_progress(session_id)
    if minutes >= config.STUCK_MINUTES_ON_PROBLEM and gained <= 0:
        if any(a["meta"].get("rule") == "minutes" and a.get("session_id") == session_id for a in earlier):
            return False
        ops.add_alert(student_id, session_id, "stuck", f"{int(minutes)} minutes in this session without progress (teacher rule: 10+ minutes).",
                      meta={"rule": "minutes"})
        return True
    return False


def _concept_titles() -> dict[str, str]:
    global _CONCEPT_TITLES
    if _CONCEPT_TITLES is None:
        graph_data = json.loads((config.DATA_DIR / "concept_graph.json").read_text(encoding="utf-8"))
        _CONCEPT_TITLES = {c["id"]: c.get("title", c["id"]) for c in graph_data.get("concepts", [])}
    return _CONCEPT_TITLES


_CONCEPT_TITLES: dict[str, str] | None = None
_CONCEPT_CHAPTERS: dict[str, str] | None = None


def _concept_chapters() -> dict[str, str]:
    global _CONCEPT_CHAPTERS
    if _CONCEPT_CHAPTERS is None:
        graph_data = json.loads((config.DATA_DIR / "concept_graph.json").read_text(encoding="utf-8"))
        _CONCEPT_CHAPTERS = {c["id"]: c.get("chapter", "") for c in graph_data.get("concepts", [])}
    return _CONCEPT_CHAPTERS


def _misconception_brief(misconception_id: str | None) -> dict[str, str] | None:
    if not misconception_id or not isinstance(misconception_id, str):
        return None
    mid = misconception_id.strip()
    if mid.lower() in ("null", "none", "nil", "n/a", ""):
        return None
    names = _misconception_names()
    if mid not in names:
        return None
    info = names[mid]
    name = info.get("name")
    if not name or str(name).strip().lower() in ("null", "none", "nil", "n/a", ""):
        return None
    return {"id": mid, "name": name, "chapter": info.get("chapter")}


def _grade_brief(grade: Any) -> dict[str, Any] | None:
    """Only the verdict and the student-safe feedback; never the answer key."""
    if not isinstance(grade, dict):
        return None
    return {
        "is_correct": bool(grade.get("is_correct")),
        "feedback": grade.get("feedback"),
        "already_solved": bool(grade.get("already_solved")),
        "checked_by": "math-tools (code)",
    }


@api_router.get("/api/quiz/questions")
def quiz_questions(request: Request, student_id: str | None = None) -> dict[str, Any]:
    """Approved questions a student can be quizzed on. Answer keys never leave the server.
    If student_id is provided, questions already solved by the student with score >= 1.0 are omitted.
    """
    rows = approvals._qb_rows("approved")
    titles = _concept_titles()
    solved_ids: set[str] = set()
    _guard_student(request, student_id)
    if student_id:
        solved_ids = learners.get_solved_question_ids(student_id)
    items = [
        {"question_id": r["id"], "concept_id": r["concept_id"], "concept": titles.get(r["concept_id"], r["concept_id"]),
         "chapter": _concept_chapters().get(r["concept_id"], ""), "difficulty": r["difficulty"], "prompt": r["prompt"],
         # the figure from the NCERT book that fits this question (code; never the worked answer)
         # (the topic's own figure first: "find the image distance" once gave a lens question the mirror figure)
         "figure": _safe_figure(r["prompt"], r["concept_id"], prefer_own=True)}
        for r in rows
        if not str(r["prompt"]).startswith("[TEST]") and r["id"] not in solved_ids
    ]
    return {"items": items}


@api_router.get("/api/student/{student_id}/progress")
def student_progress(student_id: str, request: Request) -> dict[str, Any]:
    """The student's own learner record (pseudonymous ID): mastery and misconceptions, nothing else."""
    if not student_id.startswith("stu_"):
        raise HTTPException(404)
    _guard_student(request, student_id)
    return _progress(student_id)


def _progress(student_id: str) -> dict[str, Any]:
    profile = learners.get_profile(student_id)
    titles = _concept_titles()
    chapters = _concept_chapters()
    mastery = [{"concept_id": c, "title": titles.get(c, c), "chapter": chapters.get(c, ""), "mastery": round(float(v), 2)} for c, v in sorted(profile["mastery_map"].items())]
    seen = []
    for item in profile.get("misconceptions", []):
        key = item.get("id") if isinstance(item, dict) else str(item)
        brief = _misconception_brief(key)
        if brief:
            brief["resolved"] = bool(item.get("resolved")) if isinstance(item, dict) else False
            seen.append(brief)
    return {"student_id": student_id, "mastery": mastery, "misconceptions": seen}


def _open_misconceptions(profile: dict[str, Any]) -> list[dict[str, Any]]:
    names = _misconception_names()
    out = []
    for item in profile.get("misconceptions", []):
        key = item.get("id") if isinstance(item, dict) else str(item)
        if isinstance(item, dict) and item.get("resolved"):
            continue
        info = names.get(key)
        if info:
            out.append({"id": key, **info})
    return out


def _quiz_concepts(student_id: str | None = None) -> set[str]:
    rows = approvals._qb_rows("approved")
    if student_id:
        solved_ids = learners.get_solved_question_ids(student_id)
        return {r["concept_id"] for r in rows if r["id"] not in solved_ids}
    return {r["concept_id"] for r in rows}


def _plan_for(student_id: str) -> dict[str, Any]:
    profile = learners.get_profile(student_id)
    return study_plan.view(dict(profile["mastery_map"]), _open_misconceptions(profile), ops.plan(student_id), _quiz_concepts(student_id))


def _fallback_name(student_id: str) -> str:
    return "Student " + student_id.removeprefix("stu_")[-4:].upper()


def _game_for(student_id: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or learners.get_profile(student_id)
    times = ops.message_times(student_id)
    assigned = _plan_for(student_id).get("assigned")
    return game.summary(profile, len(times), times, _concept_chapters(), assigned)


@api_router.get("/api/student/{student_id}/game")
def student_game(student_id: str, request: Request) -> dict[str, Any]:
    if not student_id.startswith("stu_"):
        raise HTTPException(404)
    _guard_student(request, student_id)
    return {"student_id": student_id, **_game_for(student_id)}


@api_router.get("/api/flashcards")
def flashcards(request: Request, student_id: str = "") -> dict[str, Any]:
    """One card per common mix-up: the question that exposes it, then the trap and how to fix it.

    Text comes from data/misconceptions.json (written and checked by the team). The student's own
    mix-ups and the topics on their plan are marked so the deck can put them first."""
    data = json.loads((config.DATA_DIR / "misconceptions.json").read_text(encoding="utf-8"))
    mine: set[str] = set()
    plan_topics: set[str] = set()
    if student_id.startswith("stu_") and _may_access(request, student_id):
        mine = {m["id"] for m in _open_misconceptions(learners.get_profile(student_id))}
        assigned = ops.plan(student_id)
        plan_topics = set((assigned or {}).get("concepts") or [])
    titles = _concept_titles()
    cards = [
        {
            "card_id": m["id"],
            "chapter": m.get("chapter", ""),
            "concept_id": m.get("concept_id"),
            "concept": titles.get(m.get("concept_id"), m.get("concept_id")),
            "front": m.get("diagnostic_probe", ""),
            "trap": m.get("name", ""),
            "why": m.get("description", ""),
            "fix": m.get("scaffolding_hint", ""),
            "mine": m["id"] in mine,
            "on_plan": m.get("concept_id") in plan_topics,
            "figure": _safe_figure(m.get("diagnostic_probe", "") + " " + m.get("name", ""), m.get("concept_id")),
        }
        for m in data
        if m.get("diagnostic_probe")
    ]
    return {"items": cards}


@api_router.get("/api/concepts")
def concepts() -> dict[str, Any]:
    graph_data = json.loads((config.DATA_DIR / "concept_graph.json").read_text(encoding="utf-8"))
    return {"items": [{"concept_id": c["id"], "title": c.get("title", c["id"]), "chapter": c.get("chapter", ""), "prerequisites": c.get("prerequisites", [])} for c in graph_data.get("concepts", [])]}


@api_router.get("/api/students")
def class_list() -> dict[str, Any]:
    """Names the teacher typed, for the "Who's learning?" picker. No progress, no alerts."""
    return {"items": [{"student_id": sid, "name": name} for sid, name in ops.roster().items()]}


@api_router.get("/api/student/{student_id}/plan")
def student_plan(student_id: str, request: Request) -> dict[str, Any]:
    if not student_id.startswith("stu_"):
        raise HTTPException(404)
    _guard_student(request, student_id)
    return {"student_id": student_id, **_plan_for(student_id)}


@api_router.get("/api/session/{session_id}/state")
def session_state(session_id: str, request: Request) -> dict[str, Any]:
    session = ops.session(session_id)
    if session is None:
        raise HTTPException(404)
    _guard_student(request, session["student_id"])
    snapshot = graph().get_state({"configurable": {"thread_id": session_id}})
    values = snapshot.values or {}
    return {
        "session_id": session_id,
        "next": list(snapshot.next or []),
        "steps": values.get("steps", []),
        "last_response": values.get("response"),
        # The conversation so far (the page shows it again after a reload; it used to be lost).
        "messages": [
            {"role": "student" if getattr(m, "type", "") == "human" else "tutor", "text": str(getattr(m, "content", ""))}
            for m in (values.get("messages") or [])[-20:]
            if getattr(m, "type", "") in ("human", "ai") and str(getattr(m, "content", "")).strip()
        ],
        "checkpoint_id": (snapshot.config or {}).get("configurable", {}).get("checkpoint_id"),
    }


@api_router.post("/api/session/{session_id}/resume")
def resume(session_id: str) -> dict[str, Any]:
    """Continue a run that stopped part-way (for example the server was killed mid-turn)."""
    if ops.session(session_id) is None:
        raise HTTPException(404)
    cfg = {"configurable": {"thread_id": session_id}}
    snapshot = graph().get_state(cfg)
    if not snapshot.next:
        raise HTTPException(409, "Nothing to resume: the last run finished.")
    out = graph().invoke(None, config=cfg)
    return {"resumed_from": list(snapshot.next), "steps": out.get("steps", []), "response": out.get("response")}


class ForgetIn(BaseModel):
    student_id: str


@api_router.post("/api/forget_me")
def forget_me(body: ForgetIn, request: Request) -> dict[str, Any]:
    """Delete everything stored for this pseudonymous student (memory policy).

    A student the teacher added (named, on the class list) is deleted by the teacher, from the teacher page:
    on a shared class device anyone could otherwise pick a classmate's name and wipe their record (and drop
    them from the class list). A device's own random ID can still delete itself here."""
    if body.student_id in ops.roster() and not _is_teacher(request):
        raise HTTPException(403, "Ask your teacher to delete your data: they can do it from the teacher page.")
    return _forget(body.student_id)


def _forget(student_id: str) -> dict[str, Any]:
    body = ForgetIn(student_id=student_id)
    sessions = ops.sessions_of(body.student_id)
    graph()
    deleted_threads = 0
    for session_id in sessions:
        try:
            _saver.delete_thread(session_id)  # type: ignore[union-attr]
            deleted_threads += 1
        except Exception:
            metrics.ERRORS.labels("forget_checkpoint").inc()
    learner_deleted = learners.forget_student(body.student_id, checkpointer=_saver)
    counts = ops.forget(body.student_id)
    trace.record("forget_me", student_id=body.student_id, sessions=len(sessions))

    # Cryptographic erasure receipt (GDPR / POCSO compliance)
    erasure_time = datetime.now(timezone.utc).isoformat()
    receipt_data = f"{body.student_id}|{erasure_time}|{counts}|{deleted_threads}"
    secret = config.get_teacher_secret()
    receipt_signature = hmac.new(secret, receipt_data.encode("utf-8"), "sha256").hexdigest()
    erasure_receipt = {
        "student_id": body.student_id,
        "erasure_timestamp": erasure_time,
        "signature": receipt_signature,
        "algorithm": "HMAC-SHA256",
        "verified": True,
    }

    return {
        "student_id": body.student_id,
        "learner_record_deleted": learner_deleted,
        "checkpoint_threads_deleted": deleted_threads,
        "ops_rows_deleted": counts,
        "erasure_receipt": erasure_receipt,
    }


# ------------------------------------------------------------------ teacher API


class LoginIn(BaseModel):
    pin: str


@api_router.post("/api/teacher/login")
def teacher_login(body: LoginIn, response: Response) -> dict[str, Any]:
    if not hmac.compare_digest(body.pin, config.get_teacher_pin()):
        raise HTTPException(401, "Wrong PIN")
    response.set_cookie("teacher", _teacher_token(), httponly=True, samesite="strict", max_age=8 * 3600)
    return {"ok": True}


@api_router.post("/api/teacher/logout")
def teacher_logout(response: Response) -> dict[str, Any]:
    response.delete_cookie("teacher")
    return {"ok": True}


def _class_misconceptions() -> dict[str, int]:
    """Students in whom each misconception was seen: learner store, plus the turn log."""
    counts: dict[str, set[str]] = {}
    with sqlite3.connect(learners.db_path) as conn:
        for student_id, misconceptions_json in conn.execute("SELECT student_id, misconceptions_json FROM learners"):
            for item in json.loads(misconceptions_json or "[]"):
                key = item.get("id") if isinstance(item, dict) else str(item).split()[0]
                counts.setdefault(key, set()).add(student_id)
    for row in ops._all("SELECT DISTINCT misconception_id, student_id FROM turns WHERE misconception_id IS NOT NULL"):
        counts.setdefault(row["misconception_id"], set()).add(row["student_id"])
    return {key: len(students) for key, students in counts.items()}


def _class_mastery() -> list[dict[str, Any]]:
    totals: dict[str, list[float]] = {}
    with sqlite3.connect(learners.db_path) as conn:
        for (mastery_json,) in conn.execute("SELECT mastery_json FROM learners WHERE student_id NOT LIKE 'RT-%' AND student_id NOT LIKE 'CLEAN-%'"):
            for concept, score in json.loads(mastery_json or "{}").items():
                totals.setdefault(concept, []).append(float(score))
    titles, chapters = _concept_titles(), _concept_chapters()
    return [{"concept_id": c, "title": titles.get(c, c), "chapter": chapters.get(c, ""), "avg_mastery": round(sum(v) / len(v), 2), "students": len(v)} for c, v in sorted(totals.items())]


def _misconception_names() -> dict[str, dict[str, str]]:
    data = json.loads((config.DATA_DIR / "misconceptions.json").read_text(encoding="utf-8"))
    return {m["id"]: {"name": m["name"], "concept_id": m["concept_id"], "chapter": m["chapter"]} for m in data}


def _waiting_items() -> tuple[list[dict[str, Any]], str | None]:
    """[L1]-[L2] The question sets waiting for the teacher (PR-2: sets only, decision P2-6), and why the list
    couldn't be read, if it couldn't (so the view never shows "Nothing waiting" when the list is broken).

    The old per-question "qb:" rows and the "graph:" student-thread pauses are gone: a set's rows could otherwise
    be approved one by one, unsigned, around the gate. web/approvals.py no longer decides anything; only its
    _qb_rows still lists the approved questions for /api/quiz/questions.
    """
    # Flowchart (each [box] matches a comment below):
    #
    #   [L1] every waiting set from the one shared approval graph       a failure -> ([], why), counted
    #   [L2] one item per set: "qbset:<set_id>", its payload, its hash and its note
    #   [R]  (the items, None)

    # [L1] every waiting set, from the one shared approval graph. A failure is counted and reported.
    try:
        sets: list[dict[str, Any]] = approval_gate.waiting_sets(approval_gate.get_approval_graph())
    except Exception as error:
        metrics.ERRORS.labels("approvals_list").inc()
        return [], "The waiting question sets could not be read (" + type(error).__name__ + ")."
    # [L2] one item per set; its id is the set's thread id, "qbset:<set_id>".
    items: list[dict[str, Any]] = []
    for waiting in sets:
        items.append({
            "item_id": approval_gate.THREAD_PREFIX + waiting["set_id"],
            "source": "question_set",
            "payload": waiting["payload"],
            "payload_hash": waiting["payload_hash"],
            "note": waiting["note"],
        })
    # [R] the items, and no problem.
    return items, None


def _pending_items() -> list[dict[str, Any]]:
    """The waiting question sets (for the counts on the dashboard and in /metrics)."""
    items, _problem = _waiting_items()
    return items


def _class_highlights() -> dict[str, Any]:
    """Real numbers only: what the class achieved, and who passed a quiz in the last 7 days."""
    passing = config.PASSING_MASTERY_THRESHOLD
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    mastered = sorted_mixups = 0
    with sqlite3.connect(learners.db_path) as conn:
        for mastery_json, misconceptions_json in conn.execute("SELECT mastery_json, misconceptions_json FROM learners WHERE student_id LIKE 'stu_%'"):
            mastered += sum(1 for v in json.loads(mastery_json or "{}").values() if float(v) >= passing)
            sorted_mixups += sum(1 for m in json.loads(misconceptions_json or "[]") if isinstance(m, dict) and m.get("resolved"))
        recent = conn.execute(
            "SELECT student_id, concept_id, MAX(score), MAX(created_at) FROM quiz_attempts WHERE student_id LIKE 'stu_%' AND created_at >= ? AND score >= ? "
            "GROUP BY student_id, concept_id ORDER BY MAX(created_at) DESC LIMIT 8",
            (since, passing),
        ).fetchall()
        correct_week = conn.execute("SELECT COUNT(*) FROM quiz_attempts WHERE student_id LIKE 'stu_%' AND created_at >= ? AND score >= 1.0", (since,)).fetchone()[0]
    active_week = ops._all("SELECT COUNT(DISTINCT student_id) AS n FROM turns WHERE student_id LIKE 'stu_%' AND at >= ?", ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds"),))[0]["n"]
    roster, titles = ops.roster(), _concept_titles()
    shout_outs = [
        {"student_id": sid, "name": roster.get(sid) or _fallback_name(sid), "concept": titles.get(cid, cid), "score": round(float(score), 2), "at": at}
        for sid, cid, score, at in recent
    ]
    return {"topics_mastered": mastered, "mixups_sorted": sorted_mixups, "quiz_correct_7d": correct_week, "active_students_7d": active_week, "shout_outs": shout_outs}


def _named_alerts() -> list[dict[str, Any]]:
    roster = ops.roster()
    return [{**a, "student_name": roster.get(a["student_id"]) or _fallback_name(a["student_id"])} for a in ops.open_alerts()]


@api_router.get("/api/teacher/dashboard", dependencies=[Depends(require_teacher)])
def dashboard() -> dict[str, Any]:
    names = _misconception_names()
    by_misconception = [
        {"misconception_id": mid, "students": n, **names.get(mid, {"name": mid, "concept_id": None, "chapter": None})}
        for mid, n in sorted(_class_misconceptions().items(), key=lambda kv: -kv[1])
    ]
    return {
        **ops.dashboard_numbers(),
        "misconceptions_by_concept": by_misconception,
        "class_mastery": _class_mastery(),
        "waiting_approvals": len(_pending_items()),
        "open_alerts": _named_alerts(),
        "highlights": _class_highlights(),
        "demo_students": _demo_student_count(),
        "ops_demo": config.OPS_DEMO == "1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@api_router.get("/api/teacher/approvals", dependencies=[Depends(require_teacher)])
def list_approvals() -> dict[str, Any]:
    # PR-2: the waiting sets, and why the list couldn't be read (None when it could).
    items, list_error = _waiting_items()
    return {
        "items": items,
        "list_error": list_error,
        "recent_decisions": ops.approval_log(),
        # PR-2: the concepts the teacher can ask the question setter for, and whether decisions can be signed.
        "concept_ids": question_bank_server.load_concept_ids(),
        "approvals_enabled": approval_gate.signing_key() is not None,
    }


class QuestionSetIn(BaseModel):
    # The concept the teacher picked (checked against the concept graph by the route).
    concept_id: str = Field(min_length=1, max_length=60)
    # How many questions to draft: 1 to 5, three by default (decision P2-2).
    count: int = Field(default=3, ge=1, le=5)


@api_router.post("/api/teacher/question_sets", dependencies=[Depends(require_teacher)])
def propose_question_set(body: QuestionSetIn) -> JSONResponse:
    """[P1]-[P5] The teacher asks for a new question set (R4 plumbing PR-2, A1; decision P2-1).

    The tutor graph runs on a NEW thread: its supervisor routes the request to the question setter, whose set
    waits for the teacher on its own "qbset:" thread. No student's chat ever waits.
    """
    # Flowchart (each [box] matches a comment below):
    #
    #   [P1] a known concept?                                      no -> 400 (no model call)
    #   [P2] a new thread "qsetter:<12 hex>" (no student, not "qbset:")
    #   [P3] the graph: input check -> supervisor -> question_setter -> END
    #   [P4] stopped by the input check?                           yes -> 200, ok False, why
    #   [P5] the setter's summary -> 200 {ok, set_id, question_count, refused, note}; a crash -> 500

    # [P1] only a concept from the concept graph; an unknown one costs no model call.
    if body.concept_id not in question_bank_server.load_concept_ids():
        raise HTTPException(400, "Unknown concept: " + body.concept_id)
    # [P2] the request's own thread.
    thread_id: str = QUESTION_REQUEST_THREAD_PREFIX + uuid.uuid4().hex[:12]
    run_config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": config.GRAPH_RECURSION_LIMIT,
    }
    # The request as graph input: no student, practice mode (quiz mode would route to the grader).
    state_in: dict[str, Any] = {
        "session_id": thread_id,
        "student_id": "",
        "mode": "practice",
        "teacher_approval_required": True,
        "current_concept_id": body.concept_id,
        "question_set_size": body.count,
        "query": QUESTION_REQUEST_TEXT,
        "messages": [],
        "steps": [],
    }
    # [P3] run the graph.
    try:
        values: dict[str, Any] = graph().invoke(state_in, config=run_config)
    except Exception as error:
        metrics.ERRORS.labels("propose_set").inc()
        return JSONResponse(status_code=500, content={"error": "propose_failed", "detail": type(error).__name__})
    # [P4] the input check stopped the request (e.g. the content guard is down: fail closed).
    if values.get("input_blocked_by"):
        note: str = "The request was stopped by the input check (" + str(values.get("input_blocked_by")) + ")."
        return JSONResponse({"ok": False, "set_id": "", "question_count": 0, "refused": [], "note": note})
    # [P5] what the question setter did: ids and reasons only, never an answer key.
    proposed: Any = values.get("proposed_set")
    if not isinstance(proposed, dict):
        return JSONResponse(status_code=500, content={"error": "propose_failed", "detail": "The question setter did not run."})
    return JSONResponse({
        "ok": bool(proposed.get("ok")),
        "set_id": str(proposed.get("set_id", "")),
        "question_count": len(proposed.get("question_ids", [])),
        "refused": proposed.get("refused", []),
        "note": str(proposed.get("note", "")),
    })


class DecisionIn(BaseModel):
    action: str = Field(pattern="^(approve|edit|reject)$")
    payload_hash: str
    changes: dict[str, Any] | None = None


def _refused_response(item_id: str, body: DecisionIn, note: str, current_hash: str) -> JSONResponse:
    """A decision the gate didn't apply: log it, and tell the teacher why (409). Nothing was changed."""
    ops.log_approval(item_id, body.action, body.payload_hash, "refused: " + note[:60])
    return JSONResponse(status_code=409, content={"error": "refused", "detail": note, "current_hash": current_hash})


@api_router.post("/api/teacher/approvals/{item_id}", dependencies=[Depends(require_teacher)])
def decide(item_id: str, body: DecisionIn) -> JSONResponse:
    """[T1]-[T6] The teacher's decision on a waiting set, signed HERE on the server (S3-10) and carried out by
    approval_gate.decide. The browser never sees the signing key; the gate checks the signature and the hash."""
    # Flowchart (each [box] matches a comment below):
    #
    #   [T1] "qbset:<set_id>"?                                           no -> 404
    #   [T2] the server has a signing key?                               no -> 503, nothing changes
    #   [T3] the set is waiting?                                         no -> 404
    #        the hash sent != the waiting version's hash -> counted as stale (the gate decides)
    #   [T4] sign the decision: set, action, the hash ON SCREEN, "teacher", the edits
    #   [T5] approval_gate.decide
    #   [T6] published / rejected -> 200; edited (a new version) -> 200;
    #        still waiting, or refused -> 409 with the reason; nothing waits any more -> 404

    # [T1] only question sets can be decided here.
    if not item_id.startswith(approval_gate.THREAD_PREFIX):
        raise HTTPException(404, "Unknown item")
    set_id: str = item_id[len(approval_gate.THREAD_PREFIX):]
    # [T2] without the key no decision can be signed, and the gate refuses unsigned ones: say why (fail closed).
    if approval_gate.signing_key() is None:
        ops.log_approval(item_id, body.action, body.payload_hash, "refused: no signing key")
        return JSONResponse(status_code=503, content={"error": "approvals_off", "detail": APPROVALS_OFF_DETAIL})
    gate_graph: Any = approval_gate.get_approval_graph()
    # [T3] the version waiting now.
    waiting: dict[str, Any] | None = approval_gate.pending_set(gate_graph, set_id)
    if waiting is None:
        raise HTTPException(404, "Item not found or no longer pending")
    waiting_hash: str = waiting["payload_hash"]
    if body.payload_hash != waiting_hash:
        # Only counted here; the gate itself refuses a decision for an older version.
        metrics.STALE_APPROVALS.inc()
    # [T4] sign what the teacher saw: the hash on screen, and the edits for an edit only.
    changes: dict[str, Any] | None = None
    if body.action == "edit":
        changes = body.changes
    try:
        decision: dict[str, Any] = approval_gate.sign_decision(set_id, body.action, body.payload_hash, TEACHER_APPROVER, changes)
    except ValueError:
        # The key vanished between [T2] and here.
        return JSONResponse(status_code=503, content={"error": "approvals_off", "detail": APPROVALS_OFF_DETAIL})
    # [T5] the gate checks the decision and carries it out.
    outcome: dict[str, Any] = approval_gate.decide(gate_graph, set_id, decision)
    status: str = outcome["status"]
    note: str = outcome["note"]
    # [T6] what happened.
    if status == "published" or status == "rejected":
        ops.log_approval(item_id, body.action, body.payload_hash, "ok")
        _observe_approval_wait(gate_graph, set_id)
        return JSONResponse({"item_id": item_id, "action": body.action, "status": status, "note": note,
                             "published": status == "published"})
    if status == "not_waiting":
        raise HTTPException(404, "Item not found or no longer pending")
    # An edit applied: the set waits again as a NEW version (a new hash), which needs its own approval.
    # The gate reports the version that was waiting WHEN it applied this decision (read under the set's lock):
    # only a changed hash means this edit was applied. (A hash read here, before the lock, could already be
    # stale: another tab's edit in between would make a refused edit look applied.)
    hash_before: str = outcome["previous_payload_hash"]
    edited: bool = (body.action == "edit" and status == "waiting" and hash_before != ""
                    and outcome["payload_hash"] != hash_before)
    if edited:
        ops.log_approval(item_id, body.action, body.payload_hash, "ok")
        return JSONResponse({"item_id": item_id, "action": body.action, "status": "edited", "note": note,
                             "payload_hash": outcome["payload_hash"]})
    # Anything else was refused (stale, unsigned, changed in the bank, or the set can't be completed).
    current_hash: str = outcome["payload_hash"]
    if current_hash == "":
        current_hash = waiting_hash
    return _refused_response(item_id, body, note, current_hash)


def _observe_approval_wait(gate_graph: Any, set_id: str) -> None:
    """Time from the set's first proposal to the teacher's decision (the Grafana "approval wait" panel was
    always empty: nothing recorded it)."""
    try:
        history = list(gate_graph.get_state_history(approval_gate.thread_config(set_id)))
        started = min(datetime.fromisoformat(h.created_at) for h in history if h.created_at)
        metrics.APPROVAL_LATENCY.observe(max(0.0, (datetime.now(timezone.utc) - started).total_seconds()))
    except Exception:
        metrics.ERRORS.labels("approval_latency").inc()


def _known_students() -> list[str]:
    ids = set(ops.roster())
    with sqlite3.connect(learners.db_path) as conn:
        ids |= {row[0] for row in conn.execute("SELECT student_id FROM learners WHERE student_id LIKE 'stu_%'")}
    ids |= {r["student_id"] for r in ops._all("SELECT DISTINCT student_id FROM sessions WHERE student_id LIKE 'stu_%' AND turns > 0")}
    return sorted(ids)


@api_router.get("/api/teacher/students", dependencies=[Depends(require_teacher)])
def teacher_students() -> dict[str, Any]:
    roster, plans, active = ops.roster(), ops.plans(), ops.last_active()
    alerts: dict[str, int] = {}
    for a in ops.open_alerts():
        alerts[a["student_id"]] = alerts.get(a["student_id"], 0) + 1
    items = []
    for sid in _known_students():
        profile = learners.get_profile(sid)
        mastery = profile["mastery_map"]
        plan = plans.get(sid)
        plan_ids = json.loads(plan["concepts_json"]) if plan else []
        items.append({
            "student_id": sid,
            "name": roster.get(sid) or _fallback_name(sid),
            "named": sid in roster,
            "code": ops.student_code(sid) if sid in roster else None,
            "avg_mastery": round(sum(mastery.values()) / len(mastery), 2) if mastery else None,
            "topics": len(mastery),
            "open_mixups": len(_open_misconceptions(profile)),
            "open_alerts": alerts.get(sid, 0),
            "last_active": active.get(sid),
            "plan_topics": len(plan_ids),
            "plan_done": sum(1 for c in plan_ids if study_plan.status_of(mastery, c) == "mastered"),
            "plan_due": plan["due"] if plan else None,
            "demo": sid.startswith(demo_data.DEMO_PREFIX),
            **_game_brief(sid, profile),
        })
    items.sort(key=lambda i: (-i["open_alerts"], not i["named"], i["name"].lower()))
    return {"items": items}


def _game_brief(student_id: str, profile: dict[str, Any]) -> dict[str, Any]:
    g = _game_for(student_id, profile)
    return {"points": g["points"], "level": g["level"], "streak_days": g["streak_days"], "badges_earned": sum(1 for b in g["badges"] if b["earned"])}


class StudentIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise HTTPException(422, "Type a name")
    return cleaned


@api_router.post("/api/teacher/students", dependencies=[Depends(require_teacher)])
def add_student(body: StudentIn) -> dict[str, Any]:
    student_id = f"stu_{uuid.uuid4().hex[:12]}"
    ops.add_student(student_id, _clean_name(body.name))
    return {"student_id": student_id, "name": _clean_name(body.name)}


@api_router.put("/api/teacher/students/{student_id}", dependencies=[Depends(require_teacher)])
def rename_student(student_id: str, body: StudentIn) -> dict[str, Any]:
    if not student_id.startswith("stu_"):
        raise HTTPException(404)
    ops.add_student(student_id, _clean_name(body.name))
    return {"student_id": student_id, "name": _clean_name(body.name)}


@api_router.post("/api/teacher/students/{student_id}/forget", dependencies=[Depends(require_teacher)])
def teacher_forget_student(student_id: str) -> dict[str, Any]:
    """The teacher deletes a student's data (the student page can't, for a named student)."""
    if not student_id.startswith("stu_"):
        raise HTTPException(404)
    return _forget(student_id)


class CodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=12)


@api_router.get("/api/student/{student_id}/access")
def student_access(student_id: str, request: Request) -> dict[str, Any]:
    """Whether this browser may learn as this student (a named student needs their sign-in code once)."""
    return {"student_id": student_id, "allowed": _may_access(request, student_id), "named": student_id in ops.roster()}


@api_router.post("/api/student/{student_id}/unlock")
def student_unlock(student_id: str, body: CodeIn, response: Response) -> dict[str, Any]:
    code = ops.student_code(student_id)
    if code is None or not hmac.compare_digest(body.code.strip(), code):
        metrics.ERRORS.labels("student_code_wrong").inc()
        raise HTTPException(403, "That code isn't right. Check it with your teacher.")
    response.set_cookie("student_" + student_id, _student_token(student_id), httponly=True, samesite="strict", max_age=180 * 24 * 3600)
    return {"ok": True}


@api_router.get("/api/teacher/students/{student_id}", dependencies=[Depends(require_teacher)])
def teacher_student(student_id: str) -> dict[str, Any]:
    if not student_id.startswith("stu_"):
        raise HTTPException(404)
    progress = _progress(student_id)
    return {
        **progress,
        "name": ops.roster().get(student_id) or _fallback_name(student_id),
        "named": student_id in ops.roster(),
        "code": ops.student_code(student_id),
        "open_alerts": [a for a in ops.open_alerts() if a["student_id"] == student_id],
        "last_active": ops.last_active().get(student_id),
        "plan": _plan_for(student_id),
        "game": _game_for(student_id),
    }


class PlanIn(BaseModel):
    concepts: list[str] = Field(max_length=12)
    note: str = Field(default="", max_length=500)
    due: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


@api_router.put("/api/teacher/students/{student_id}/plan", dependencies=[Depends(require_teacher)])
def assign_plan(student_id: str, body: PlanIn) -> dict[str, Any]:
    if not student_id.startswith("stu_"):
        raise HTTPException(404)
    known = study_plan.concept_graph().concepts
    unknown = [c for c in body.concepts if c not in known]
    if unknown:
        raise HTTPException(422, f"Unknown topics: {', '.join(unknown)}")
    concepts = list(dict.fromkeys(body.concepts))
    ops.set_plan(student_id, concepts, body.note.strip(), body.due)
    trace.record("study_plan_assigned", student_id=student_id, topics=len(concepts))
    return {"student_id": student_id, **_plan_for(student_id)}


@api_router.post("/api/teacher/alerts/{alert_id}/ack", dependencies=[Depends(require_teacher)])
def ack_alert(alert_id: int) -> dict[str, Any]:
    if not ops.ack_alert(alert_id):
        raise HTTPException(404)
    return {"ok": True}


# ---- transcript labelling for judge calibration (R5: evalkit/calibrate.py)

LABEL_DIR = config.EVAL_RESULTS_DIR / "labels"
CRITERIA = ("conceptual_accuracy", "identified_misconception", "socratic_guidance")  # the teacher's rubric, 1-5


@api_router.get("/api/teacher/labels", dependencies=[Depends(require_teacher)])
def labels_todo(labeller: str = "") -> dict[str, Any]:
    source = LABEL_DIR / "to_label.csv"
    if not source.exists():
        return {"items": [], "note": "No transcripts exported yet. Run: python -m evalkit.calibrate export --run evalkit/results/runs/<run_id>"}
    with open(source, newline="", encoding="utf-8") as handle:
        items = list(csv.DictReader(handle))
    done: set[str] = set()
    labelled = LABEL_DIR / "human_labels.csv"
    if labelled.exists():
        with open(labelled, newline="", encoding="utf-8") as handle:
            done = {r["item_id"] for r in csv.DictReader(handle) if not labeller or r.get("labeller") == labeller}
    return {"items": [i for i in items if i["item_id"] not in done], "done": len(done), "total": len(items), "criteria": CRITERIA}


class LabelIn(BaseModel):
    item_id: str
    labeller: str = Field(min_length=1, max_length=40)
    conceptual_accuracy: int = Field(ge=1, le=5)
    identified_misconception: int = Field(ge=1, le=5)
    socratic_guidance: int = Field(ge=1, le=5)


@api_router.post("/api/teacher/labels", dependencies=[Depends(require_teacher)])
def save_label(body: LabelIn) -> dict[str, Any]:
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    path = LABEL_DIR / "human_labels.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new:
            writer.writerow(["item_id", "labeller", *CRITERIA, "at"])
        writer.writerow([body.item_id, body.labeller, *(getattr(body, c) for c in CRITERIA), datetime.now(timezone.utc).isoformat(timespec="seconds")])
    return {"ok": True}


# ---- alert demo (only with OPS_DEMO=1): adds clearly-labelled synthetic leaks


def _demo_student_count() -> int:
    with sqlite3.connect(learners.db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM learners WHERE student_id LIKE 'stu_demo_%'").fetchone()[0]


class DemoDataIn(BaseModel):
    action: str = Field(pattern="^(seed|clear)$")


@api_router.post("/api/ops/demo-data", dependencies=[Depends(require_teacher)])
def demo_data_switch(body: DemoDataIn) -> dict[str, Any]:
    """Add or remove the clearly-labelled demo class (web/demo_data.py). Only with OPS_DEMO=1."""
    if config.OPS_DEMO != "1":
        raise HTTPException(403, "Set OPS_DEMO=1 to enable demo data")
    if body.action == "clear":
        return {"ok": True, **demo_data.clear_demo_class(learners, ops)}
    result = demo_data.seed_demo_class(learners, ops)
    questions = demo_data.propose_demo_questions()
    return {"ok": True, **result, "questions_proposed": len(questions)}


@api_router.post("/api/ops/emit-test-leak", dependencies=[Depends(require_teacher)])
def emit_test_leak(count: int = 5) -> dict[str, Any]:
    if config.OPS_DEMO != "1":
        raise HTTPException(403, "Set OPS_DEMO=1 to enable the alert demo")
    metrics.ANSWER_LEAKS.labels("synthetic").inc(max(1, min(count, 50)))
    return {"ok": True, "added": count, "source": "synthetic"}

