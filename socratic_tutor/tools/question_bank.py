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
    return _read_questions(question_ids)


def _rows_problem(shown: list[dict]) -> str | None:
    """[R1] Compare the stored rows with what was shown (no lock); the reason for the first difference, or None."""
    ids = []
    for question in shown:
        ids.append(question["id"])
    stored = {}
    for row in _read_questions(ids):
        stored[row["id"]] = row
    for before in shown:
        row = stored.get(before["id"])
        if row is None:
            return f"Question {before['id']} is no longer in the bank."
        if row["status"] != "pending_approval":
            return f"Question {before['id']} is already '{row['status']}'."
        for field in QUESTION_FIELDS:
            if row[field] != before[field]:
                return f"Question {before['id']} changed since it was shown."
    return None


def _read_questions(question_ids: list[str]) -> list[dict]:
    """The stored rows for these ids, in order, missing ones left out (used by get_questions and _rows_problem)."""
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
    """Check every row, then change them all in ONE short transaction, or change nothing.

    [R1] The rows are read and compared OUTSIDE the transaction, so the write lock is held only for the UPDATEs.
    [R3] Each UPDATE's WHERE repeats the values that were checked, so a row changed after [R1] (by another writer
         in that gap) updates 0 rows, and the whole set is rolled back. This is an "optimistic" check.
    """
    problem = _set_problem(shown, approved)
    if problem is not None:
        return {result_key: [], "problem": problem}
    # [R1] read and compare, without taking any lock.
    problem = _rows_problem(shown)
    if problem is not None:
        return {result_key: [], "problem": problem}
    # isolation_level=None: this function starts and ends the transaction itself.
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        # [R2] BEGIN IMMEDIATE takes the write lock; only the UPDATEs run while it's held.
        conn.execute("BEGIN IMMEDIATE")
        ids = []
        for before, after in zip(shown, approved):
            # [R3] change the row only if it is still exactly what was checked in [R1].
            cursor = conn.execute(
                "UPDATE questions SET difficulty = ?, prompt = ?, gold_answer = ?, status = ? "
                "WHERE id = ? AND status = 'pending_approval' "
                "AND concept_id = ? AND difficulty = ? AND prompt = ? AND gold_answer = ?",
                (after["difficulty"], after["prompt"], after["gold_answer"], new_status,
                 before["id"], before["concept_id"], before["difficulty"], before["prompt"], before["gold_answer"]),
            )
            if cursor.rowcount != 1:
                # Someone changed (or decided, or deleted) it after [R1]: undo every row of this set.
                conn.execute("ROLLBACK")
                return {result_key: [], "problem": f"Question {before['id']} changed while the set was being saved."}
            ids.append(before["id"])
        # [R4] every row matched: make all the changes visible together.
        conn.execute("COMMIT")
        return {result_key: ids}
    except Exception:
        # Anything unexpected: undo whatever this transaction did, then let the caller see the error.
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
