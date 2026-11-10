"""FastMCP Tool Server: question-bank (propose, publish behind approval gate)."""

import sqlite3
import json
from pathlib import Path
from socratic_tutor import config

DB_PATH = config.INDEX_DIR / "question_bank.db"


def _init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY,
                concept_id TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                prompt TEXT NOT NULL,
                gold_answer TEXT NOT NULL,
                status TEXT DEFAULT 'pending_approval' -- pending_approval | approved | rejected
            )
        """)
        conn.commit()


_init_db()


def propose_question(concept_id: str, difficulty: str, prompt: str, gold_answer: str) -> dict:
    """Propose a new practice question for teacher approval."""
    import uuid
    qid = f"Q_{uuid.uuid4().hex[:8]}"
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO questions (id, concept_id, difficulty, prompt, gold_answer, status) VALUES (?, ?, ?, ?, ?, 'pending_approval')",
            (qid, concept_id, difficulty, prompt, gold_answer)
        )
        conn.commit()
    return {"question_id": qid, "status": "pending_teacher_approval"}


def publish_approved_question(question_id: str) -> bool:
    """Mark a question as published to the shared bank (executed ONLY by teacher approval)."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("UPDATE questions SET status = 'approved' WHERE id = ?", (question_id,))
        conn.commit()
        return cursor.rowcount > 0


# --- Question sets for the approval gate (socratic_tutor/approval_gate.py) ---
# The teacher approves or rejects a whole SET of questions at once (capstone guide p.12, step 9).
# A set changes all or nothing: every row in one transaction, so a problem with one question
# leaves the others unchanged as well. Values always go in through "?" placeholders.

QUESTION_FIELDS = ("id", "concept_id", "difficulty", "prompt", "gold_answer")
EDITABLE_FIELDS = ("difficulty", "prompt", "gold_answer")


def get_questions(question_ids: list[str]) -> list[dict]:
    """Return the stored questions with these ids, with their status, in the order asked.

    Ids that aren't in the bank are left out, so the caller can compare the lengths.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        found = []
        for question_id in question_ids:
            row = conn.execute(
                "SELECT id, concept_id, difficulty, prompt, gold_answer, status FROM questions WHERE id = ?",
                (question_id,),
            ).fetchone()
            if row is not None:
                found.append(dict(row))
        return found
    finally:
        # "with sqlite3.connect(...)" only commits; it doesn't close the file.
        conn.close()


def publish_question_set(shown: list[dict], approved: list[dict]) -> dict:
    """Publish a teacher-approved question set, all or nothing.

    shown:    each question exactly as the teacher was shown it (the QUESTION_FIELDS).
    approved: the same questions in the same order, as approved; the teacher may have edited
              difficulty, prompt or gold_answer.
    Every row must still be 'pending_approval' and unchanged since it was shown, or nothing changes.
    Returns {"published": [ids]}, or {"published": [], "problem": "..."}.
    """
    return _change_set(shown, approved, "approved", "published")


def reject_question_set(shown: list[dict]) -> dict:
    """Reject a question set, all or nothing, with the same checks as publish_question_set.

    Returns {"rejected": [ids]}, or {"rejected": [], "problem": "..."}.
    """
    return _change_set(shown, shown, "rejected", "rejected")


def _set_problem(shown: list[dict], approved: list[dict]) -> str | None:
    """What's wrong with the two lists, before the database is touched; None if they fit together."""
    if len(shown) == 0:
        return "The set has no questions."
    if len(shown) != len(approved):
        return "The approved set doesn't have the same questions as the set that was shown."
    for before, after in zip(shown, approved):
        for field in QUESTION_FIELDS:
            if not isinstance(before.get(field), str) or not isinstance(after.get(field), str):
                return f"A question in the set is missing its {field}."
        # Only the text may change: the question and its concept stay the same.
        if before["id"] != after["id"] or before["concept_id"] != after["concept_id"]:
            return "The approved set doesn't have the same questions as the set that was shown."
    return None


def _change_set(shown: list[dict], approved: list[dict], new_status: str, result_key: str) -> dict:
    """Check every row and change them all in ONE transaction, or change nothing."""
    problem = _set_problem(shown, approved)
    if problem is not None:
        return {result_key: [], "problem": problem}
    # isolation_level=None: this function starts and ends the transaction itself.
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        # BEGIN IMMEDIATE takes the write lock now, so no one can change these rows between our
        # check and our update (two approvals of the same set at once: the second finds them decided).
        conn.execute("BEGIN IMMEDIATE")
        ids = []
        for before, after in zip(shown, approved):
            row = conn.execute(
                "SELECT id, concept_id, difficulty, prompt, gold_answer, status FROM questions WHERE id = ?",
                (before["id"],),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return {result_key: [], "problem": f"Question {before['id']} is no longer in the bank."}
            if row[5] != "pending_approval":
                conn.execute("ROLLBACK")
                return {result_key: [], "problem": f"Question {before['id']} is already '{row[5]}'."}
            for position, field in enumerate(QUESTION_FIELDS):
                if row[position] != before[field]:
                    conn.execute("ROLLBACK")
                    return {result_key: [], "problem": f"Question {before['id']} changed since it was shown."}
            conn.execute(
                "UPDATE questions SET difficulty = ?, prompt = ?, gold_answer = ?, status = ? "
                "WHERE id = ? AND status = 'pending_approval'",
                (after["difficulty"], after["prompt"], after["gold_answer"], new_status, before["id"]),
            )
            ids.append(before["id"])
        # Every row passed: make all the changes visible together.
        conn.execute("COMMIT")
        return {result_key: ids}
    except Exception:
        # Anything unexpected: undo whatever this transaction did, then let the caller see the error.
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
