"""Learner memory store managing student mastery, misconceptions, and privacy."""

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
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
                    failure_streaks_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(learners)")}
            if "failure_streaks_json" not in columns:
                conn.execute(
                    "ALTER TABLE learners ADD COLUMN failure_streaks_json TEXT NOT NULL DEFAULT '{}'"
                )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quiz_attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id TEXT NOT NULL,
                    concept_id TEXT NOT NULL,
                    score REAL NOT NULL,
                    duration_seconds REAL NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    question_id TEXT
                )
            """)
            columns_qa = {row[1] for row in conn.execute("PRAGMA table_info(quiz_attempts)")}
            if "question_id" not in columns_qa:
                conn.execute(
                    "ALTER TABLE quiz_attempts ADD COLUMN question_id TEXT"
                )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS learner_sessions (
                    student_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (student_id, thread_id)
                )
            """)
            conn.commit()

    def get_profile(self, student_id: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT mastery_json, misconceptions_json, lessons_json, stuck_counter, failure_streaks_json "
                "FROM learners WHERE student_id = ?",
                (student_id,)
            )
            row = cursor.fetchone()
            if row:
                attempts = conn.execute(
                    "SELECT concept_id, score, duration_seconds, created_at, question_id "
                    "FROM quiz_attempts WHERE student_id = ? ORDER BY attempt_id DESC LIMIT 50",
                    (student_id,),
                ).fetchall()
                return {
                    "student_id": student_id,
                    "mastery_map": json.loads(row[0]),
                    "misconceptions": json.loads(row[1]),
                    "effective_lessons": json.loads(row[2]),
                    "stuck_counter": row[3],
                    "failure_streaks": json.loads(row[4]),
                    "quiz_history": [
                        {
                            "concept_id": attempt[0],
                            "score": attempt[1],
                            "duration_seconds": attempt[2],
                            "created_at": attempt[3],
                            "question_id": attempt[4],
                        }
                        for attempt in reversed(attempts)
                    ],
                }
            return {
                "student_id": student_id,
                "mastery_map": {},
                "misconceptions": [],
                "effective_lessons": [],
                "stuck_counter": 0,
                "failure_streaks": {},
                "quiz_history": [],
            }

    @staticmethod
    def _validate_student_and_concept(student_id: str, concept_id: str | None = None) -> None:
        if not student_id or not student_id.strip():
            raise ValueError("student_id must be non-empty")
        if concept_id is not None and (not concept_id or not concept_id.strip()):
            raise ValueError("concept_id must be non-empty")

    @staticmethod
    def _write_profile(conn: sqlite3.Connection, student_id: str, profile: dict) -> None:
        conn.execute("""
            INSERT INTO learners (
                student_id, mastery_json, misconceptions_json, lessons_json,
                stuck_counter, failure_streaks_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(student_id) DO UPDATE SET
                mastery_json = excluded.mastery_json,
                misconceptions_json = excluded.misconceptions_json,
                lessons_json = excluded.lessons_json,
                stuck_counter = excluded.stuck_counter,
                failure_streaks_json = excluded.failure_streaks_json,
                updated_at = CURRENT_TIMESTAMP
        """, (
            student_id,
            json.dumps(profile["mastery_map"]),
            json.dumps(profile["misconceptions"]),
            json.dumps(profile["effective_lessons"]),
            profile["stuck_counter"],
            json.dumps(profile["failure_streaks"]),
        ))

    def update_mastery(self, student_id: str, concept_id: str, score: float) -> None:
        self._validate_student_and_concept(student_id, concept_id)
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("mastery score must be between 0 and 1")
        profile = self.get_profile(student_id)
        mastery = profile["mastery_map"]
        mastery[concept_id] = round(score, 2)
        with sqlite3.connect(self.db_path) as conn:
            profile["mastery_map"] = mastery
            self._write_profile(conn, student_id, profile)
            conn.commit()

    def record_misconception(
        self,
        student_id: str,
        misconception_id: str,
        resolved: bool = False,
    ) -> None:
        self._validate_student_and_concept(student_id, misconception_id)
        profile = self.get_profile(student_id)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        existing = next(
            (item for item in profile["misconceptions"]
             if isinstance(item, dict) and item.get("id") == misconception_id),
            None,
        )
        if existing:
            existing["last_seen_at"] = now
            existing["resolved"] = bool(resolved)
        else:
            profile["misconceptions"] = [
                item for item in profile["misconceptions"]
                if item != misconception_id
            ]
            profile["misconceptions"].append({
                "id": misconception_id,
                "first_seen_at": now,
                "last_seen_at": now,
                "resolved": bool(resolved),
            })
        with sqlite3.connect(self.db_path) as conn:
            self._write_profile(conn, student_id, profile)
            conn.commit()

    def record_effective_lesson(self, student_id: str, lesson_id: str) -> None:
        self._validate_student_and_concept(student_id, lesson_id)
        profile = self.get_profile(student_id)
        if lesson_id not in profile["effective_lessons"]:
            profile["effective_lessons"].append(lesson_id)
        with sqlite3.connect(self.db_path) as conn:
            self._write_profile(conn, student_id, profile)
            conn.commit()

    def record_quiz_result(
        self,
        student_id: str,
        concept_id: str,
        score: float,
        duration_seconds: float = 0,
        question_id: str | None = None,
    ) -> dict:
        self._validate_student_and_concept(student_id, concept_id)
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("quiz score must be between 0 and 1")
        if not math.isfinite(duration_seconds) or duration_seconds < 0:
            raise ValueError("duration_seconds must be finite and non-negative")

        already_solved = False
        if question_id:
            with sqlite3.connect(self.db_path) as conn:
                existing = conn.execute(
                    "SELECT 1 FROM quiz_attempts WHERE student_id = ? AND question_id = ? AND score >= 1.0",
                    (student_id, question_id),
                ).fetchone()
                already_solved = bool(existing)

        profile = self.get_profile(student_id)
        score = round(score, 2)
        with sqlite3.connect(self.db_path) as conn:
            previous_scores = conn.execute(
                "SELECT score FROM quiz_attempts WHERE student_id = ? AND concept_id = ? "
                "ORDER BY attempt_id DESC LIMIT ?",
                (student_id, concept_id, config.MASTERY_WINDOW_SIZE - 1),
            ).fetchall()
            window_scores = [row[0] for row in previous_scores] + [score]
            profile["mastery_map"][concept_id] = round(sum(window_scores) / len(window_scores), 2)
        if score < config.PASSING_MASTERY_THRESHOLD:
            profile["failure_streaks"][concept_id] = profile["failure_streaks"].get(concept_id, 0) + 1
        else:
            profile["failure_streaks"][concept_id] = 0
        profile["stuck_counter"] = max(profile["failure_streaks"].values(), default=0)
        with sqlite3.connect(self.db_path) as conn:
            self._write_profile(conn, student_id, profile)
            conn.execute(
                "INSERT INTO quiz_attempts (student_id, concept_id, score, duration_seconds, question_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (student_id, concept_id, score, duration_seconds, question_id),
            )
            conn.commit()

        failure_streak = profile["failure_streaks"][concept_id]
        return {
            "score": score,
            "mastery": profile["mastery_map"][concept_id],
            "failure_streak": failure_streak,
            "already_solved": already_solved,
            "teacher_alert_triggered": failure_streak >= config.STUCK_FAILURE_COUNT or duration_seconds > 600,
        }

    def get_solved_question_ids(self, student_id: str) -> set[str]:
        """Return the set of question_ids that this student has already solved correctly (score >= 1.0)."""
        if not student_id:
            return set()
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT question_id FROM quiz_attempts WHERE student_id = ? AND score >= 1.0 AND question_id IS NOT NULL",
                (student_id,),
            ).fetchall()
            return {row[0] for row in rows if row[0]}

    def register_session(self, student_id: str, thread_id: str) -> None:
        self._validate_student_and_concept(student_id, thread_id)
        profile = self.get_profile(student_id)
        with sqlite3.connect(self.db_path) as conn:
            self._write_profile(conn, student_id, profile)
            conn.execute(
                "INSERT OR IGNORE INTO learner_sessions (student_id, thread_id) VALUES (?, ?)",
                (student_id, thread_id),
            )
            conn.commit()

    def forget_me(self, student_id: str, checkpointer=None) -> dict:
        """Delete profile data and associated LangGraph threads when a saver is provided."""
        self._validate_student_and_concept(student_id)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT thread_id FROM learner_sessions WHERE student_id = ?",
                (student_id,),
            ).fetchall()
        thread_ids = [row[0] for row in rows]
        if thread_ids and checkpointer is None:
            raise ValueError("checkpointer is required to delete this learner's registered sessions")
        if checkpointer is not None:
            delete_thread = getattr(checkpointer, "delete_thread", None)
            if thread_ids and delete_thread is None:
                raise TypeError("checkpointer does not support delete_thread(thread_id)")
            for thread_id in thread_ids:
                delete_thread(thread_id)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM quiz_attempts WHERE student_id = ?", (student_id,))
            conn.execute("DELETE FROM learner_sessions WHERE student_id = ?", (student_id,))
            cursor = conn.execute("DELETE FROM learners WHERE student_id = ?", (student_id,))
            conn.commit()
        return {
            "deleted": bool(cursor.rowcount or thread_ids),
            "profile_deleted": cursor.rowcount > 0,
            "checkpoints_deleted": len(thread_ids),
        }

    def forget_student(self, student_id: str, checkpointer=None) -> bool:
        """Backward-compatible alias for the cascade-aware forget API."""
        return self.forget_me(student_id, checkpointer=checkpointer)["deleted"]

    def purge_expired_profiles(
        self,
        inactive_days: int = 90,
        now: datetime | None = None,
        checkpointer=None,
    ) -> int:
        """Purge profiles inactive for the configured retention window."""
        if inactive_days <= 0:
            raise ValueError("inactive_days must be positive")
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        cutoff = (current_time - timedelta(days=inactive_days)).strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            expired = conn.execute(
                "SELECT student_id FROM learners WHERE datetime(updated_at) <= datetime(?)",
                (cutoff,),
            ).fetchall()
        for (student_id,) in expired:
            self.forget_me(student_id, checkpointer=checkpointer)
        return len(expired)
