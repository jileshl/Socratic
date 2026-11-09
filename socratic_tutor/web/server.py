"""FastAPI service: student chat (streamed), teacher view, approvals, metrics.

    uvicorn socratic_tutor.web.server:app --host 0.0.0.0 --port 8000
    python -m socratic_tutor.app            (same thing)

Pages:  /            student view (practice and quiz modes)
        /teacher     teacher view (PIN login; the login decides the role, never chat text)
API:    POST /api/session            start a session (pseudonymous student ID, consent flag)
        POST /api/chat               one student turn, streamed as server-sent events
        GET  /api/session/{id}/state checkpoint for a session (what ran, what is next)
        POST /api/session/{id}/resume continue a run that stopped mid-way (checkpointer)
        POST /api/forget_me          delete everything stored for a student
        /api/teacher/...             dashboard, approvals, alerts, transcript labelling
        GET  /metrics                Prometheus metrics; GET /healthz
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from langchain_core.messages import HumanMessage
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from socratic_tutor import config, trace
from socratic_tutor.learner_store import LearnerStore
from socratic_tutor.web import approvals, metrics
from socratic_tutor.web.ops_store import OpsStore

STATIC = Path(__file__).parent / "static"
REFUSAL = "I cannot fulfill this request as entered. Let's focus on our NCERT study goals."

# Who makes each decision in the graph. Shown in the student view next to each box.
# R3: update this when a node changes from code to model or the reverse.
NODE_DECIDER = {
    "input_guardrail": "code",
    "supervisor": "model",
    "planner": "code",
    "diagnostician": "model",
    "tutor": "model",
    "grader": "code",
    "question_setter": "model",
    "teacher_approval_gate": "person",
    "output_guardrail": "code",
    "memory": "code",
}

app = FastAPI(title="Socratic Tutor", version="0.2.0")
ops = OpsStore()
learners = LearnerStore()
_graph = None
_saver = None


def graph():
    """Build the team's graph once, with a persistent SQLite checkpointer (stop and resume)."""
    global _graph, _saver
    if _graph is None:
        from langgraph.checkpoint.sqlite import SqliteSaver

        from socratic_tutor.graph import build_graph

        conn = sqlite3.connect(config.INDEX_DIR / "checkpoints.sqlite", check_same_thread=False)
        _saver = SqliteSaver(conn)
        _graph = build_graph(checkpointer=_saver)
    return _graph


# ------------------------------------------------------------------ auth


def _teacher_secret() -> bytes:
    explicit = os.getenv("TEACHER_SECRET")
    seed = explicit or f"{os.getenv('TEACHER_PIN', '1234')}|{config.BASE_DIR}"
    return hashlib.sha256(seed.encode()).digest()


def _teacher_token() -> str:
    return hmac.new(_teacher_secret(), b"teacher", hashlib.sha256).hexdigest()


def require_teacher(request: Request) -> None:
    token = request.cookies.get("teacher", "")
    if not hmac.compare_digest(token, _teacher_token()):
        raise HTTPException(status_code=401, detail="Teacher login required")


# ------------------------------------------------------------------ pages


@app.get("/", include_in_schema=False)
def student_page() -> FileResponse:
    return FileResponse(STATIC / "student.html")


@app.get("/teacher", include_in_schema=False)
def teacher_page() -> FileResponse:
    return FileResponse(STATIC / "teacher.html")


@app.get("/static/{name}", include_in_schema=False)
def static_file(name: str) -> FileResponse:
    path = (STATIC / name).resolve()
    if path.parent != STATIC.resolve() or not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    from socratic_tutor.tools import textbook_kb

    return {"ok": True, "index_chunks": len(textbook_kb.retriever.index.chunks), "config_version": config.CONFIG_VERSION}


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    metrics.PENDING_APPROVALS.set(len(_pending_items()))
    metrics.STUCK_STUDENTS.set(sum(1 for a in ops.open_alerts() if a["kind"] == "stuck"))
    return Response(generate_latest(metrics.REGISTRY), media_type=CONTENT_TYPE_LATEST)


# ------------------------------------------------------------------ student API


class SessionIn(BaseModel):
    mode: str = Field(default="practice", pattern="^(practice|quiz)$")
    student_id: str | None = None
    consent: bool = False


@app.post("/api/session")
def start_session(body: SessionIn) -> dict[str, Any]:
    student_id = body.student_id if body.student_id and body.student_id.startswith("stu_") else f"stu_{uuid.uuid4().hex[:12]}"
    session_id = f"ses_{uuid.uuid4().hex[:12]}"
    ops.start_session(session_id, student_id, body.mode, body.consent)
    metrics.SESSIONS.labels(body.mode).inc()
    return {"session_id": session_id, "student_id": student_id, "mode": body.mode, "consent": body.consent}


class ChatIn(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=4000)


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def _mastery(student_id: str) -> dict[str, float]:
    return dict(learners.get_profile(student_id)["mastery_map"])


@app.post("/api/chat")
def chat(body: ChatIn) -> StreamingResponse:
    session = ops.session(body.session_id)
    if session is None:
        raise HTTPException(404, "Unknown session; start one with POST /api/session")
    return StreamingResponse(_run_turn(session, body.message), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _run_turn(session: dict[str, Any], message: str) -> Iterator[str]:
    session_id, student_id, mode = session["session_id"], session["student_id"], session["mode"]
    meter = trace.CostMeter()  # the same meter the eval harness uses
    cfg = {
        "configurable": {"thread_id": session_id},
        "callbacks": [meter, trace.TraceCallback(session_id)],
        "recursion_limit": 2 * config.MAX_LLM_CALLS_PER_TURN + 5,
    }
    before = _mastery(student_id)
    started = time.perf_counter()
    state_in = {
        "session_id": session_id,
        "student_id": student_id,
        "mode": mode,
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
    except Exception as exc:  # report, count, and keep the service up
        error = f"{type(exc).__name__}: {exc}"
        metrics.ERRORS.labels("chat").inc()

    latency = time.perf_counter() - started
    values = graph().get_state({"configurable": {"thread_id": session_id}}).values if error is None else {}
    reply = str(values.get("response") or "") if error is None else "Sorry, something went wrong on our side. Please try again."
    blocked_reason = None
    if values.get("injection_detected"):
        blocked_reason = "injection"
    elif values.get("teacher_alert_triggered") and reply == REFUSAL:
        blocked_reason = "distress"
    leak = bool(values.get("answer_leak_flag")) and mode == "practice"
    misconception = values.get("identified_misconception") or {}
    misconception_id = misconception.get("id") if isinstance(misconception, dict) else misconception
    concept_id = values.get("current_concept_id")
    after = _mastery(student_id)
    delta = None
    if concept_id and concept_id in after:
        delta = round(after[concept_id] - before.get(concept_id, 0.0), 3)
        metrics.MASTERY_DELTA.observe(delta)
    usage = meter.snapshot()

    # metrics and operational records (no message text stored here)
    outcome = "error" if error else ("blocked" if blocked_reason else "ok")
    metrics.REQUESTS.labels(mode, outcome).inc()
    metrics.LATENCY.labels(mode).observe(latency)
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
    if values.get("teacher_alert_triggered"):
        ops.add_alert(student_id, session_id, "distress", "Distress language detected; please check in with this student.")
        metrics.DISTRESS_ALERTS.inc()
    stuck = learners.get_profile(student_id).get("stuck_counter", 0)
    if stuck >= config.STUCK_SESSION_COUNT and not ops.has_open_alert(student_id, "stuck"):
        ops.add_alert(student_id, session_id, "stuck", f"Stuck on the same concept for {stuck} sessions.")
    minutes, gained = ops.session_progress(session_id)
    if minutes >= config.STUCK_MINUTES_ON_PROBLEM and gained <= 0 and not ops.has_open_alert(student_id, "stuck"):
        ops.add_alert(student_id, session_id, "stuck", f"{int(minutes)} minutes in this session without progress (teacher rule: 10+ minutes).")
    if interrupted:
        payload = getattr(interrupted[0], "value", interrupted[0]) if isinstance(interrupted, (list, tuple)) else interrupted
        payload_json = json.dumps(payload, sort_keys=True, default=str)
        ops.save_interrupt(session_id, student_id, payload_json, approvals.payload_hash(json.loads(payload_json)))
    for name, value in _class_misconceptions().items():
        metrics.CLASS_MISCONCEPTIONS.labels(name).set(value)
    trace.record("turn", session_id=session_id, student_id=student_id, mode=mode, student=message, tutor=reply, latency_s=round(latency, 3), outcome=outcome, **usage)

    yield _sse(
        {
            "type": "reply",
            "text": reply,
            "citations": values.get("citations") or [],
            "blocked": bool(blocked_reason),
            "teacher_alerted": bool(values.get("teacher_alert_triggered")),
            "pending_approval": bool(interrupted),
            "next_concept": values.get("next_recommended_concept"),
            "latency_s": round(latency, 2),
            "cost_usd": usage["cost_usd"],
            "error": bool(error),
        }
    )


@app.get("/api/session/{session_id}/state")
def session_state(session_id: str) -> dict[str, Any]:
    if ops.session(session_id) is None:
        raise HTTPException(404)
    snapshot = graph().get_state({"configurable": {"thread_id": session_id}})
    values = snapshot.values or {}
    return {
        "session_id": session_id,
        "next": list(snapshot.next or []),
        "steps": values.get("steps", []),
        "last_response": values.get("response"),
        "checkpoint_id": (snapshot.config or {}).get("configurable", {}).get("checkpoint_id"),
    }


@app.post("/api/session/{session_id}/resume")
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


@app.post("/api/forget_me")
def forget_me(body: ForgetIn) -> dict[str, Any]:
    """Delete everything stored for this pseudonymous student (memory policy)."""
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
    return {"student_id": body.student_id, "learner_record_deleted": learner_deleted, "checkpoint_threads_deleted": deleted_threads, "ops_rows_deleted": counts}


# ------------------------------------------------------------------ teacher API


class LoginIn(BaseModel):
    pin: str


@app.post("/api/teacher/login")
def teacher_login(body: LoginIn, response: Response) -> dict[str, Any]:
    if not hmac.compare_digest(body.pin, os.getenv("TEACHER_PIN", "1234")):
        raise HTTPException(401, "Wrong PIN")
    response.set_cookie("teacher", _teacher_token(), httponly=True, samesite="strict", max_age=8 * 3600)
    return {"ok": True}


@app.post("/api/teacher/logout")
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
    return [{"concept_id": c, "avg_mastery": round(sum(v) / len(v), 2), "students": len(v)} for c, v in sorted(totals.items())]


def _misconception_names() -> dict[str, dict[str, str]]:
    data = json.loads((config.DATA_DIR / "misconceptions.json").read_text(encoding="utf-8"))
    return {m["id"]: {"name": m["name"], "concept_id": m["concept_id"], "chapter": m["chapter"]} for m in data}


def _pending_items() -> list[dict[str, Any]]:
    items = approvals.pending_question_items()
    for row in ops.pending_interrupts():
        payload = json.loads(row["payload_json"])
        items.append({"item_id": f"graph:{row['thread_id']}", "source": "graph_interrupt", "payload": payload, "payload_hash": row["payload_hash"], "created_at": row["created_at"]})
    return items


@app.get("/api/teacher/dashboard", dependencies=[Depends(require_teacher)])
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
        "open_alerts": ops.open_alerts(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@app.get("/api/teacher/approvals", dependencies=[Depends(require_teacher)])
def list_approvals() -> dict[str, Any]:
    return {"items": _pending_items(), "recent_decisions": ops.approval_log()}


class DecisionIn(BaseModel):
    action: str = Field(pattern="^(approve|edit|reject)$")
    payload_hash: str
    changes: dict[str, Any] | None = None


@app.post("/api/teacher/approvals/{item_id}", dependencies=[Depends(require_teacher)])
def decide(item_id: str, body: DecisionIn) -> JSONResponse:
    source, _, key = item_id.partition(":")
    try:
        if source == "qb":
            if body.action == "approve":
                result = approvals.approve_question(key, body.payload_hash)
            elif body.action == "reject":
                result = approvals.reject_question(key, body.payload_hash)
            else:
                result = approvals.edit_question(key, body.payload_hash, body.changes or {})
        elif source == "graph":
            result = _decide_interrupt(key, body)
        else:
            raise HTTPException(404, "Unknown item")
    except approvals.StaleApproval as stale:
        metrics.STALE_APPROVALS.inc()
        ops.log_approval(item_id, body.action, body.payload_hash, "refused: stale")
        return JSONResponse(
            status_code=409,
            content={"error": "stale_approval", "detail": "This item changed after you opened it, so your approval no longer applies. Review the new version.", "current_hash": str(stale)},
        )
    except KeyError:
        raise HTTPException(404, "Item not found or no longer pending")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    ops.log_approval(item_id, body.action, body.payload_hash, "ok")
    return JSONResponse({"item_id": item_id, "action": body.action, **result})


def _decide_interrupt(thread_id: str, body: DecisionIn) -> dict[str, Any]:
    from langgraph.types import Command

    row = next((r for r in ops.pending_interrupts() if r["thread_id"] == thread_id), None)
    if row is None:
        raise KeyError(thread_id)
    if row["payload_hash"] != body.payload_hash:
        raise approvals.StaleApproval(row["payload_hash"])
    if body.action == "edit":
        payload = json.loads(row["payload_json"])
        payload.update(body.changes or {})
        new_hash = approvals.payload_hash(payload)
        ops.save_interrupt(thread_id, row["student_id"], json.dumps(payload, sort_keys=True), new_hash)
        return {"payload": payload, "payload_hash": new_hash, "note": "Edited: approve this new version to publish it."}
    created = datetime.fromisoformat(row["created_at"])
    metrics.APPROVAL_LATENCY.observe((datetime.now(timezone.utc) - created).total_seconds())
    resume_value = {"action": body.action, "payload_hash": body.payload_hash, "payload": json.loads(row["payload_json"])}
    out = graph().invoke(Command(resume=resume_value), config={"configurable": {"thread_id": thread_id}})
    ops.clear_interrupt(thread_id)
    return {"resumed": True, "steps": out.get("steps", [])}


@app.post("/api/teacher/alerts/{alert_id}/ack", dependencies=[Depends(require_teacher)])
def ack_alert(alert_id: int) -> dict[str, Any]:
    if not ops.ack_alert(alert_id):
        raise HTTPException(404)
    return {"ok": True}


# ---- transcript labelling for judge calibration (R5: evalkit/calibrate.py)

LABEL_DIR = config.EVAL_RESULTS_DIR / "labels"
CRITERIA = ("conceptual_accuracy", "identified_misconception", "socratic_guidance")  # the teacher's rubric, 1-5


@app.get("/api/teacher/labels", dependencies=[Depends(require_teacher)])
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


@app.post("/api/teacher/labels", dependencies=[Depends(require_teacher)])
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


@app.post("/api/ops/emit-test-leak", dependencies=[Depends(require_teacher)])
def emit_test_leak(count: int = 5) -> dict[str, Any]:
    if os.getenv("OPS_DEMO") != "1":
        raise HTTPException(403, "Set OPS_DEMO=1 to enable the alert demo")
    metrics.ANSWER_LEAKS.labels("synthetic").inc(max(1, min(count, 50)))
    return {"ok": True, "added": count, "source": "synthetic"}
