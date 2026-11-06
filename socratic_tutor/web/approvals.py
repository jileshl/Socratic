"""Teacher approval tied to the exact payload (L14).

An approval names the SHA-256 hash of the payload the teacher looked at. The
server recomputes the hash of what is stored now; if they differ (because anyone
edited the item after the teacher opened it), the approval is refused as stale.
An edit therefore always invalidates earlier approvals and needs a fresh one.

Two sources of items:
  * graph interrupts: the question setter pauses the graph with interrupt();
    approval resumes it with Command(resume={"action", "payload_hash", ...}).
  * question-bank rows with status 'pending_approval' (question_bank.propose_question).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from socratic_tutor.tools import question_bank

QB_FIELDS = ("id", "concept_id", "difficulty", "prompt", "gold_answer")


def payload_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class StaleApproval(Exception):
    """The payload changed after the teacher viewed it."""


def _qb_rows(status: str | None = "pending_approval") -> list[dict[str, Any]]:
    with sqlite3.connect(question_bank.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM questions" + (" WHERE status = ?" if status else "")
        return [dict(r) for r in conn.execute(sql, (status,) if status else ()).fetchall()]


def qb_item(question_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(question_bank.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM questions WHERE id = ?", (question_id,)).fetchone()
    return dict(row) if row else None


def qb_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row[k] for k in QB_FIELDS}


def pending_question_items() -> list[dict[str, Any]]:
    items = []
    for row in _qb_rows():
        payload = qb_payload(row)
        items.append({"item_id": f"qb:{row['id']}", "source": "question_bank", "payload": payload, "payload_hash": payload_hash(payload)})
    return items


def approve_question(question_id: str, viewed_hash: str) -> dict[str, Any]:
    row = qb_item(question_id)
    if row is None or row["status"] != "pending_approval":
        raise KeyError(question_id)
    current = payload_hash(qb_payload(row))
    if current != viewed_hash:
        raise StaleApproval(current)
    published = question_bank.publish_approved_question(question_id)
    return {"published": published, "payload_hash": current}


def reject_question(question_id: str, viewed_hash: str) -> dict[str, Any]:
    row = qb_item(question_id)
    if row is None:
        raise KeyError(question_id)
    current = payload_hash(qb_payload(row))
    if current != viewed_hash:
        raise StaleApproval(current)
    with sqlite3.connect(question_bank.DB_PATH) as conn:
        conn.execute("UPDATE questions SET status = 'rejected' WHERE id = ?", (question_id,))
        conn.commit()
    return {"rejected": True, "payload_hash": current}


def edit_question(question_id: str, viewed_hash: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Apply a teacher's edit. Returns the new payload and hash; it still needs approval."""
    row = qb_item(question_id)
    if row is None or row["status"] != "pending_approval":
        raise KeyError(question_id)
    if payload_hash(qb_payload(row)) != viewed_hash:
        raise StaleApproval(payload_hash(qb_payload(row)))
    allowed = {k: str(v) for k, v in changes.items() if k in ("prompt", "gold_answer", "difficulty", "concept_id")}
    if not allowed:
        raise ValueError("Nothing to edit")
    with sqlite3.connect(question_bank.DB_PATH) as conn:
        conn.execute(f"UPDATE questions SET {', '.join(f'{k} = ?' for k in allowed)} WHERE id = ?", (*allowed.values(), question_id))
        conn.commit()
    new_payload = qb_payload(qb_item(question_id))  # type: ignore[arg-type]
    return {"payload": new_payload, "payload_hash": payload_hash(new_payload)}
