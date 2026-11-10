"""The approval gate: the teacher approves, edits or rejects a SET of proposed questions before any of them
reaches students (capstone guide p.12, step 9; p.3, row L14: "Every world-changing action goes through
interrupt() with approve, edit and reject. Approval is tied to the exact payload.").

How it works (the interrupt pattern, AAI-14 p.38; a digest-bound, signed approval, AAI-15-2 p.50):
    submit_set([question ids])  -> a small approval graph runs on its OWN thread, "qbset:<set_id>",
                                   collects the rows, and pauses at interrupt() showing the exact set
                                   (pending_set() gives the set, its hash and a note)
    ... the teacher decides, minutes or days later; the checkpointer keeps the paused run (even across restarts)
    decide(set_id, decision)    -> Command(resume=decision): the gate checks the decision and then publishes,
                                   pauses again with a new version (edit), or rejects

Decisions (reviews/r4_stage3_approval_gate_step1.md and step2.md):
- S3-3: its own thread per set. A pause in the student's chat thread is cancelled by the student's next
  message (measured), so the student never waits for the teacher.
- S3-2 / S3-4: the pause shows the payload {set_id, version, questions}; its hash is computed exactly like
  the teacher view's payload_hash. A decision is {"action", "payload_hash", "approver", "signature",
  "payload"?, "changes"?}. Approve and reject apply ONLY to the version on screen (its hash); edits go
  through the "edit" action, which makes a new version (a new version number, so a new hash).
- S3-6: fail closed, all or nothing. Any problem: nothing is published, and the set waits again.
- S3-10: every decision names the approver and is signed (HMAC-SHA256) with a server-only key,
  APPROVAL_SIGNING_KEY, which no agent tool can read. No key, or a wrong signature: refused.

The database work is in question_bank.py (decision S3-7): get_questions, publish_question_set, reject_question_set.
"""

import hashlib
import hmac
import json
import logging
import os
import sys
import threading
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from socratic_tutor import config  # noqa: F401  (imported so that .env is loaded before the key is read)
from socratic_tutor.tools import question_bank
from socratic_tutor.tools.question_bank_server import (
    DIFFICULTIES,
    MAX_GOLD_ANSWER_LENGTH,
    MAX_PROMPT_LENGTH,
    answer_key_problem,
    safe_for_log,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# The three decisions a teacher can make (capstone guide p.3: approve, edit and reject).
ACTIONS: list[str] = ["approve", "edit", "reject"]
# Each set waits on its own thread: "qbset:" + set_id (decision S3-3).
THREAD_PREFIX: str = "qbset:"
# The name of the environment variable (in .env) that holds the server-only signing key (decision S3-10).
SIGNING_KEY_VARIABLE: str = "APPROVAL_SIGNING_KEY"
# A set is a handful of questions; more than this is refused, so one approval can't hide a flood [own choice].
MAX_SET_SIZE: int = 10
# The longest set id and approver id accepted [own choice].
MAX_SET_ID_LENGTH: int = 40
MAX_APPROVER_LENGTH: int = 100
# An approval faster than this, counted from when the version appeared, is flagged in the log:
# "a two-second approval means nobody is reading" (AAI-15-2 p.59; AAI-14 p.30) [own choice of number].
FAST_APPROVAL_SECONDS: float = 5.0
# A SHA-256 hash and an HMAC-SHA256 signature are both written as 64 lowercase hex characters.
HEX_DIGITS: str = "0123456789abcdef"


def now() -> float:
    """The current time in seconds. One small function, so the tests can control the clock."""
    return time.time()


# ---------------------------------------------------------------------------
# The state of one approval run (saved by the checkpointer after every node)
# ---------------------------------------------------------------------------
class ApprovalState(TypedDict, total=False):
    set_id: str
    question_ids: list[str]
    version: int                  # 1 at submit; +1 for every new version (an edit, or fresh rows)
    payload: dict[str, Any]       # {"set_id", "version", "questions": [{id, concept_id, difficulty, prompt, gold_answer}]}
    payload_hash: str             # payload_hash(payload): the version the teacher must approve
    stored_questions: list[dict[str, Any]]   # the rows as they are in the bank (an edit changes only the payload)
    status: str                   # "waiting" | "published" | "rejected" | "refused"
    note: str                     # why the set is waiting again, or how it ended
    shown_at: float               # when the current version appeared (for the wait time in the log)


# ---------------------------------------------------------------------------
# Logging: one stderr line per submitted set and per decision. Never the question text.
# ---------------------------------------------------------------------------
logger: logging.Logger = logging.getLogger("approval-gate")
if not logger.handlers:
    # Send the log lines to stderr, with a timestamp and the module's name.
    stderr_handler: logging.StreamHandler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter("%(asctime)s approval-gate %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(stderr_handler)
    logger.setLevel(logging.INFO)
    # Keep these lines out of other loggers (for example the app's root logger).
    logger.propagate = False


def safe_log_value(text: str) -> str:
    """Make a value safe for an UNQUOTED log field: only letters, digits and . , _ - are kept; the rest become _.

    The same rule as textbook_kb_server.safe_log_value: an approver name like 'x ok=True' can't add fake fields.
    """
    safe = ""
    for character in text:
        if character.isascii() and (character.isalnum() or character in ".,_-"):
            safe = safe + character
        else:
            safe = safe + "_"
    return safe


def log_event(set_id: str, action: str, outcome: str, approver: str, questions: int, wait_seconds: float | None,
              payload_hash: str, reason: str) -> str:
    """Build and write one log line, and return it (the tests read it)."""
    line = "set=" + safe_log_value(set_id) + " action=" + safe_log_value(action)
    line = line + " outcome=" + safe_log_value(outcome)
    if approver != "":
        line = line + " approver=" + safe_log_value(approver[:MAX_APPROVER_LENGTH])
    line = line + " questions=" + str(questions)
    if wait_seconds is not None:
        line = line + " wait_s=" + str(round(wait_seconds, 1))
        # A very quick approval is flagged, so the dashboard can show it next to "waiting approvals".
        if action == "approve" and outcome == "published" and wait_seconds < FAST_APPROVAL_SECONDS:
            line = line + " fast=True"
    # The first 12 characters of the hash are enough to tell versions apart in a log.
    line = line + " hash=" + safe_log_value(payload_hash[:12])
    if reason != "":
        line = line + ' reason="' + safe_for_log(reason[:80]) + '"'
    logger.info(line)
    return line


# ---------------------------------------------------------------------------
# The payload and its hash (decision S3-2)
# ---------------------------------------------------------------------------


def payload_hash(payload: Any) -> str:
    """The SHA-256 fingerprint of a payload, exactly as the teacher view computes it (web/approvals.py).

    Key-sorted, compact JSON, so the same content always gives the same fingerprint, and one changed
    character gives a different one. AAI-15-2 p.50 binds an approval to the exact call the same way.
    """
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def make_payload(set_id: str, version: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The payload the teacher sees: the set id, the version number and, for each question, the five fields.

    The version number makes every new version's hash new, even if an edit brings the text back to an
    earlier version: an old approval can never fit again.
    """
    questions: list[dict[str, Any]] = []
    for row in rows:
        question: dict[str, Any] = {}
        for field in question_bank.QUESTION_FIELDS:
            question[field] = row[field]
        questions.append(question)
    return {"set_id": set_id, "version": version, "questions": questions}


def is_hex_digest(text: Any) -> bool:
    """True for 64 lowercase hex characters (a SHA-256 hash, or an HMAC-SHA256 signature)."""
    if not isinstance(text, str) or len(text) != 64:
        return False
    for character in text:
        if character not in HEX_DIGITS:
            return False
    return True


# ---------------------------------------------------------------------------
# The signature (decision S3-10): who approved, and exactly what
# ---------------------------------------------------------------------------


def signing_key() -> str | None:
    """The server-only key from the environment (.env), read at call time; None if it isn't set."""
    key = os.getenv(SIGNING_KEY_VARIABLE)
    if key is None or key.strip() == "":
        return None
    return key


def signed_text(set_id: str, action: str, hash_text: str, approver: str, changes: Any) -> str:
    """The exact text that is signed: a JSON list of the set, the action, the version's hash, the approver
    and a digest of the edits. JSON keeps the fields apart, so no field can pretend to be the next one."""
    changes_digest = ""
    if changes is not None:
        changes_digest = payload_hash(changes)
    return json.dumps([set_id, action, hash_text, approver, changes_digest], ensure_ascii=False)


def make_signature(set_id: str, action: str, hash_text: str, approver: str, changes: Any, key: str) -> str:
    """HMAC-SHA256 over signed_text, with the server-only key, as 64 hex characters."""
    message = signed_text(set_id, action, hash_text, approver, changes)
    return hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_decision(set_id: str, action: str, hash_text: str, approver: str, changes: Any = None,
                  payload: dict[str, Any] | None = None, key: str | None = None) -> dict[str, Any]:
    """Build a signed decision. The teacher view calls this when the logged-in teacher clicks a button.

    The key comes from APPROVAL_SIGNING_KEY unless one is given (the tests and the demo give one).
    """
    if key is None:
        key = signing_key()
    if key is None:
        raise ValueError("APPROVAL_SIGNING_KEY is not set, so no decision can be signed.")
    decision: dict[str, Any] = {"action": action, "payload_hash": hash_text, "approver": approver}
    if changes is not None:
        decision["changes"] = changes
    if payload is not None:
        decision["payload"] = payload
    decision["signature"] = make_signature(set_id, action, hash_text, approver, changes, key)
    return decision


# ---------------------------------------------------------------------------
# Checking a decision (box [G2])
# ---------------------------------------------------------------------------


def edited_value_problem(field: str, value: Any) -> str | None:
    """[G2] What's wrong with one edited value; None if it's fine (an edited key must still be readable, S3-8)."""
    if field not in question_bank.EDITABLE_FIELDS:
        return "Only " + ", ".join(question_bank.EDITABLE_FIELDS) + " can be edited, not " + str(field) + "."
    if not isinstance(value, str) or value.strip() == "":
        return "The edited " + field + " is empty."
    if field == "difficulty" and value.strip() not in DIFFICULTIES:
        return "difficulty must be one of " + ", ".join(DIFFICULTIES) + "."
    if field == "prompt" and len(value.strip()) > MAX_PROMPT_LENGTH:
        return "The edited prompt is longer than " + str(MAX_PROMPT_LENGTH) + " characters."
    if field == "gold_answer":
        if len(value.strip()) > MAX_GOLD_ANSWER_LENGTH:
            return "The edited gold_answer is longer than " + str(MAX_GOLD_ANSWER_LENGTH) + " characters."
        # The grader's code must still be able to read it (the question-bank server's [Q4] check).
        key_problem = answer_key_problem(value.strip())
        if key_problem is not None:
            return "The edited answer key can't be used: " + key_problem
    return None


def apply_changes(questions: list[dict[str, Any]], changes: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    """[G3] The questions with the teacher's edits applied (a NEW list), or a problem.

    changes = {question_id: {field: new value}}, for questions in the set and editable fields only.
    The new values are stored without surrounding spaces.
    """
    if not isinstance(changes, dict) or len(changes) == 0:
        return None, "An edit needs 'changes': {question_id: {field: new value}}."
    # Copy every question first, so the version the teacher was shown stays as it was.
    edited: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for question in questions:
        copy = dict(question)
        edited.append(copy)
        by_id[copy["id"]] = copy
    for question_id in changes:
        if question_id not in by_id:
            return None, "The edit names a question that isn't in this set."
        field_changes = changes[question_id]
        if not isinstance(field_changes, dict) or len(field_changes) == 0:
            return None, "The edit for a question must be {field: new value}."
        for field in field_changes:
            problem = edited_value_problem(field, field_changes[field])
            if problem is not None:
                return None, problem
            by_id[question_id][field] = field_changes[field].strip()
    return edited, None


def approver_problem(approver: Any) -> str | None:
    """[G2] The approver must be a short, printable name with no surrounding spaces (the teacher login's id)."""
    if not isinstance(approver, str) or approver == "" or len(approver) > MAX_APPROVER_LENGTH:
        return "The decision must name the approver (the logged-in teacher)."
    if approver != approver.strip() or not approver.isprintable():
        return "The approver's name can't have surrounding spaces or control characters."
    return None


def check_decision(decision: Any, state: ApprovalState) -> dict[str, Any]:
    """[G2] Check a decision against the version on screen. Returns {"ok": True, "action", "approver",
    "questions"} (the version to publish or reject, or the edited new version), or {"ok": False, "problem", ...}.

    Every check that could fail on odd input is written so that it returns a problem instead of raising:
    an exception here would be replayed on every later resume and jam the set.
    """
    shown_questions = state["payload"]["questions"]
    current_hash = state["payload_hash"]
    result: dict[str, Any] = {"ok": False, "action": "unknown", "approver": ""}

    # The form of the decision.
    if not isinstance(decision, dict):
        result["problem"] = "The decision isn't in the expected form."
        return result
    action = decision.get("action")
    if action not in ACTIONS:
        result["problem"] = "Unknown action: it must be approve, edit or reject."
        return result
    result["action"] = action
    problem = approver_problem(decision.get("approver"))
    if problem is not None:
        result["problem"] = problem
        return result
    approver = decision["approver"]
    result["approver"] = approver
    hash_text = decision.get("payload_hash")
    if not is_hex_digest(hash_text):
        result["problem"] = "The decision must carry the hash (64 hex characters) of the version it is for."
        return result

    # Who: the signature, made with the server-only key (S3-10). Without the key, nothing can be decided.
    key = signing_key()
    if key is None:
        result["problem"] = "Approvals need APPROVAL_SIGNING_KEY on the server, so this decision was refused."
        return result
    signature = decision.get("signature")
    if not is_hex_digest(signature):
        result["problem"] = "The decision's signature doesn't match, so it wasn't made through the teacher's login."
        return result
    try:
        expected = make_signature(state["set_id"], action, hash_text, approver, decision.get("changes"), key)
    except (TypeError, ValueError):
        # The changes couldn't be turned into JSON, so they can't have been signed either.
        result["problem"] = "The decision's changes can't be read."
        return result
    # Both are 64 hex characters (checked above), so comparing them as bytes is safe and takes constant time.
    if not hmac.compare_digest(signature.encode("ascii"), expected.encode("ascii")):
        result["problem"] = "The decision's signature doesn't match, so it wasn't made through the teacher's login."
        return result

    # What: every decision is for the version on screen. An older hash is stale, whatever else it carries.
    if hash_text != current_hash:
        result["problem"] = "This decision is for an older version of the set (stale). Review the current version."
        return result
    # A payload sent along (the teacher view sends one) must be exactly the version on screen.
    if "payload" in decision:
        try:
            sent_hash = payload_hash(decision["payload"])
        except (TypeError, ValueError):
            sent_hash = ""
        if sent_hash != current_hash:
            result["problem"] = "The payload sent with the decision isn't the version on screen."
            return result

    if action == "edit":
        edited, problem = apply_changes(shown_questions, decision.get("changes"))
        if problem is not None:
            result["problem"] = problem
            return result
        result["ok"] = True
        result["questions"] = edited
        return result
    # approve or reject: the version on screen.
    result["ok"] = True
    result["questions"] = shown_questions
    return result


# ---------------------------------------------------------------------------
# The two nodes of the approval graph
# ---------------------------------------------------------------------------


def collect_node(state: ApprovalState) -> dict[str, Any]:
    """[C1]-[C3] Read the set's rows ONCE and build the payload and its hash. (It never re-runs on resume.)"""
    set_id = state["set_id"]
    question_ids = state.get("question_ids", [])
    # [C1] the rows, as stored.
    rows = question_bank.get_questions(question_ids)
    # [C2] every id found once, and every question still waiting for approval.
    problem = ""
    if len(rows) != len(question_ids):
        problem = "Some of the questions aren't in the bank."
    else:
        for row in rows:
            if row["status"] != "pending_approval":
                problem = "Question " + row["id"] + " is already '" + row["status"] + "'."
    if problem != "":
        log_event(set_id, "submit", "refused", "", len(question_ids), None, "", problem)
        return {"status": "refused", "note": problem}
    # [C3] the exact version the teacher will see (version 1), and its fingerprint. The rows as stored are
    # kept too: at approval, the bank must still hold exactly these (publish_question_set checks).
    payload = make_payload(set_id, 1, rows)
    hash_text = payload_hash(payload)
    log_event(set_id, "submit", "waiting", "", len(rows), None, hash_text, "")
    return {
        "version": 1,
        "payload": payload,
        "payload_hash": hash_text,
        "stored_questions": payload["questions"],
        "status": "waiting",
        "note": "Waiting for the teacher.",
        "shown_at": now(),
    }


def fresh_version(state: ApprovalState, problem: str) -> dict[str, Any]:
    """[G4]/[G5] After the bank refused a publish or reject: wait again with the CURRENT rows as a new version,
    or end if the set can't be completed (a question was deleted or already decided elsewhere)."""
    rows = question_bank.get_questions(state["question_ids"])
    still_pending = len(rows) == len(state["question_ids"])
    for row in rows:
        if row["status"] != "pending_approval":
            still_pending = False
    if not still_pending:
        return {"status": "refused", "note": problem + " Nothing in this set was changed."}
    version = state["version"] + 1
    payload = make_payload(state["set_id"], version, rows)
    return {
        "version": version,
        "payload": payload,
        "payload_hash": payload_hash(payload),
        "stored_questions": payload["questions"],
        "status": "waiting",
        "note": problem + " Review the current version.",
        "shown_at": now(),
    }


def carry_out(state: ApprovalState, decision: Any) -> dict[str, Any]:
    """[G2]-[G5] Check the decision and carry it out. Returns the state update for the gate node."""
    wait_seconds = now() - state.get("shown_at", now())
    question_count = len(state["payload"]["questions"])

    # [G2] CHECK the decision: its form, the signature (who), and the version (what).
    checked = check_decision(decision, state)
    if not checked["ok"]:
        log_event(state["set_id"], checked["action"], "refused", checked["approver"], question_count,
                  wait_seconds, state["payload_hash"], checked["problem"])
        # Fail closed: nothing changes; the same version waits again, with the reason.
        return {"status": "waiting", "note": checked["problem"]}
    action = checked["action"]
    approver = checked["approver"]

    # [G3] EDIT: a new version (a new version number and a new hash), which needs its own approval.
    if action == "edit":
        version = state["version"] + 1
        new_payload = {"set_id": state["set_id"], "version": version, "questions": checked["questions"]}
        new_hash = payload_hash(new_payload)
        log_event(state["set_id"], "edit", "waiting", approver, question_count, wait_seconds, new_hash, "")
        return {
            "version": version,
            "payload": new_payload,
            "payload_hash": new_hash,
            "status": "waiting",
            "note": "Edited: approve this version to publish it.",
            "shown_at": now(),
        }

    # [G4] APPROVE / [G5] REJECT, all or nothing. The bank must still hold the rows exactly as collected
    # (stored_questions); publish_question_set / reject_question_set check that inside one transaction.
    stored = state["stored_questions"]
    if action == "approve":
        outcome = question_bank.publish_question_set(stored, checked["questions"])
        changed = outcome["published"]
        finished = {"status": "published", "note": "Published by " + approver + "."}
    else:
        outcome = question_bank.reject_question_set(stored)
        changed = outcome["rejected"]
        finished = {"status": "rejected", "note": "Rejected by " + approver + "."}
    if changed:
        log_event(state["set_id"], action, finished["status"], approver, question_count, wait_seconds,
                  state["payload_hash"], "")
        return finished
    log_event(state["set_id"], action, "refused", approver, question_count, wait_seconds,
              state["payload_hash"], outcome["problem"])
    # The bank refused because a row changed, is gone, or was decided elsewhere: show the current rows.
    return fresh_version(state, outcome["problem"])


def gate_node(state: ApprovalState) -> dict[str, Any]:
    """[G1]-[G6] Pause for the teacher, then check and carry out the decision.

    The FIRST line is interrupt(): on resume the node re-runs from its top, so nothing that changes
    anything may come before it (measured, step-1 doc E3).
    """
    # [G1] PAUSE. The first time, the run stops here. After Command(resume=decision), interrupt() RETURNS it.
    # The value shown is exactly the payload, so anyone hashing it (the teacher view's payload_hash) gets the
    # same fingerprint as the gate. The hash and the note are read with pending_set().
    decision = interrupt(state["payload"])
    try:
        return carry_out(state, decision)
    except Exception as error:  # [W] anything unexpected (e.g. a locked database): fail closed, never crash
        # A crash here would be dangerous: LangGraph replays the same decision on every later resume, so
        # the set would be stuck for good. Instead the node finishes, nothing changes (the bank's transaction
        # rolled back), and the same version waits again for a NEW decision.
        problem = "Unexpected problem (" + type(error).__name__ + "); nothing was changed."
        log_event(state["set_id"], "unknown", "refused", "", len(state["payload"]["questions"]), None,
                  state["payload_hash"], problem)
        return {"status": "waiting", "note": problem}


def route_after_collect(state: ApprovalState) -> str:
    """After collect: a refused set ends; a good one goes to the gate."""
    if state.get("status") == "refused":
        return END
    return "gate"


def route_after_gate(state: ApprovalState) -> str:
    """After the gate: "waiting" loops back to the gate (pause again); anything else ends the run."""
    if state.get("status") == "waiting":
        return "gate"
    return END


def build_approval_graph(checkpointer: Any) -> Any:
    """The approval graph: START -> collect -> gate (loops while "waiting") -> END.

    It needs a checkpointer, because a set waits for the teacher across turns and restarts. The app passes the
    same SqliteSaver it uses for its own graph (.index/checkpoints.sqlite); the tests pass a temporary one.
    """
    workflow = StateGraph(ApprovalState)
    workflow.add_node("collect", collect_node)
    workflow.add_node("gate", gate_node)
    workflow.add_edge(START, "collect")
    workflow.add_conditional_edges("collect", route_after_collect, ["gate", END])
    workflow.add_conditional_edges("gate", route_after_gate, ["gate", END])
    return workflow.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# The three functions others call: submit_set, pending_set, decide
# ---------------------------------------------------------------------------

# One lock per set: two decisions for the same set at the same moment (two clicks, two tabs) run one after
# the other, so the second sees the first one's result. It covers one process; across processes, the bank's
# transaction still keeps the rows right.
SET_LOCKS: dict[str, threading.Lock] = {}
SET_LOCKS_GUARD: threading.Lock = threading.Lock()


def lock_for(set_id: str) -> threading.Lock:
    """The lock for one set, created the first time it's needed."""
    with SET_LOCKS_GUARD:
        if set_id not in SET_LOCKS:
            SET_LOCKS[set_id] = threading.Lock()
        return SET_LOCKS[set_id]


def thread_config(set_id: str) -> dict[str, Any]:
    """The checkpointer address of a set's approval run: thread "qbset:<set_id>"."""
    return {"configurable": {"thread_id": THREAD_PREFIX + set_id}}


def is_safe_set_id(set_id: Any) -> bool:
    """A set id is short and made of letters, digits, _ and - only (it becomes part of a thread id and the log)."""
    if not isinstance(set_id, str) or set_id == "" or len(set_id) > MAX_SET_ID_LENGTH:
        return False
    for character in set_id:
        if not (character.isascii() and (character.isalnum() or character in "_-")):
            return False
    return True


def submit_set(graph: Any, question_ids: list[str], set_id: str | None = None) -> dict[str, Any]:
    """[S1]-[S3] Start the approval of a set of proposed questions. It returns as soon as the set is waiting.

    Returns {"ok": True, "set_id", "thread_id", "payload", "payload_hash"}, or {"ok": False, "error"}.
    """
    # [S1] the set id (a new random one unless given) and its thread.
    if set_id is None:
        set_id = "set_" + uuid.uuid4().hex[:8]
    if not is_safe_set_id(set_id):
        log_event("-", "submit", "refused", "", 0, None, "", "unsafe set id")
        return {"ok": False, "error": "The set id must be 1-40 letters, digits, _ or -."}
    # The questions: a short list of distinct ids.
    problem = ""
    if not isinstance(question_ids, list) or len(question_ids) == 0 or len(question_ids) > MAX_SET_SIZE:
        problem = "A set has 1 to " + str(MAX_SET_SIZE) + " questions."
    else:
        seen: list[str] = []
        for question_id in question_ids:
            if not isinstance(question_id, str) or question_id in seen:
                problem = "The question ids must be distinct ids."
            seen.append(question_id)
    if problem != "":
        log_event(set_id, "submit", "refused", "", 0, None, "", problem)
        return {"ok": False, "error": problem}
    config_for_set = thread_config(set_id)
    with lock_for(set_id):
        # A set id is used once: new input on an existing thread would start a new run and replace a waiting
        # approval (measured, step-1 doc E2).
        if graph.get_state(config_for_set).values:
            log_event(set_id, "submit", "refused", "", len(question_ids), None, "", "set id already in use")
            return {"ok": False, "error": "This set id is already in use."}
        # [S2] run collect, then the gate, which pauses.
        output = graph.invoke({"set_id": set_id, "question_ids": question_ids}, config_for_set)
    # [S3] the waiting version, or why the set was refused.
    waiting = pending_set(graph, set_id)
    if waiting is None:
        return {"ok": False, "error": str(output.get("note", "The set could not be submitted."))}
    return {
        "ok": True,
        "set_id": set_id,
        "thread_id": THREAD_PREFIX + set_id,
        "payload": waiting["payload"],
        "payload_hash": waiting["payload_hash"],
    }


def pending_set(graph: Any, set_id: str) -> dict[str, Any] | None:
    """The waiting version of a set ({"set_id", "payload", "payload_hash", "note"}), or None if it isn't waiting."""
    if not is_safe_set_id(set_id):
        return None
    snapshot = graph.get_state(thread_config(set_id))
    if snapshot.next != ("gate",):
        return None
    for task in snapshot.tasks:
        for paused in task.interrupts:
            # The interrupt's value is the payload itself; its hash is recomputed, and the note is in the state.
            return {
                "set_id": set_id,
                "payload": paused.value,
                "payload_hash": payload_hash(paused.value),
                "note": str(snapshot.values.get("note", "")),
            }
    return None


def decide(graph: Any, set_id: str, decision: Any) -> dict[str, Any]:
    """[D1]-[D3] Hand the teacher's decision to a waiting set. Returns {"status", "note", "payload_hash"}.

    status: "waiting" (refused, or edited: a version still needs approval), "published", "rejected",
    "refused" (the set couldn't be completed), or "not_waiting" (nothing waits: e.g. a double click).
    """
    if not is_safe_set_id(set_id):
        return {"status": "not_waiting", "note": "This set isn't waiting for a decision.", "payload_hash": ""}
    # The checkpointer saves the decision with the run, so it must be plain JSON data. Anything else is refused
    # here, before the gate runs: saving would otherwise fail after the bank had already changed.
    try:
        json.dumps(decision)
    except (TypeError, ValueError):
        log_event(set_id, "unknown", "refused", "", 0, None, "", "the decision is not plain JSON data")
        return {"status": "waiting", "note": "The decision can't be read, so it wasn't applied.", "payload_hash": ""}
    with lock_for(set_id):
        # [D1] only a waiting set can be decided; a second click after it finished changes nothing.
        if pending_set(graph, set_id) is None:
            log_event(set_id, "unknown", "not_waiting", "", 0, None, "", "")
            return {"status": "not_waiting", "note": "This set isn't waiting for a decision.", "payload_hash": ""}
        # [D2] resume the gate with the decision.
        graph.invoke(Command(resume=decision), thread_config(set_id))
        # [D3] how it ended (or why it waits again).
        values = graph.get_state(thread_config(set_id)).values
    return {
        "status": str(values.get("status", "")),
        "note": str(values.get("note", "")),
        "payload_hash": str(values.get("payload_hash", "")),
    }
