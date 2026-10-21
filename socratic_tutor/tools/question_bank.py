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
