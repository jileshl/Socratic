"""Learner memory store managing student mastery, misconceptions, and privacy."""

import sqlite3
import json
from pathlib import Path
from socratic_tutor import config


class LearnerStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (config.INDEX_DIR / "learner_store.db")
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learners (
                    student_id TEXT PRIMARY KEY,
                    mastery_json TEXT NOT NULL,
                    misconceptions_json TEXT NOT NULL,
                    lessons_json TEXT NOT NULL,
                    stuck_counter INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def get_profile(self, student_id: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT mastery_json, misconceptions_json, lessons_json, stuck_counter FROM learners WHERE student_id = ?",
                (student_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "student_id": student_id,
                    "mastery_map": json.loads(row[0]),
                    "misconceptions": json.loads(row[1]),
                    "effective_lessons": json.loads(row[2]),
                    "stuck_counter": row[3]
                }
            return {
                "student_id": student_id,
                "mastery_map": {},
                "misconceptions": [],
                "effective_lessons": [],
                "stuck_counter": 0
            }

    def update_mastery(self, student_id: str, concept_id: str, score: float) -> None:
        profile = self.get_profile(student_id)
        mastery = profile["mastery_map"]
        mastery[concept_id] = round(score, 2)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO learners (student_id, mastery_json, misconceptions_json, lessons_json, stuck_counter)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(student_id) DO UPDATE SET
                    mastery_json = excluded.mastery_json,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                student_id,
                json.dumps(mastery),
                json.dumps(profile["misconceptions"]),
                json.dumps(profile["effective_lessons"]),
                profile["stuck_counter"]
            ))
            conn.commit()

    def forget_student(self, student_id: str) -> bool:
        """Purge all learner records for GDPR / Minor privacy compliance."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM learners WHERE student_id = ?", (student_id,))
            conn.commit()
            return cursor.rowcount > 0
