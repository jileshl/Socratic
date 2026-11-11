"""Operational records for the running service (not the learner model).

Stores only what the teacher view and the operators need: pseudonymous session
and student IDs, per-turn outcomes (latency, cost, leak flag, block reason),
alerts and approval decisions, plus the teacher's class list (a display name the teacher
types for each pseudonymous ID) and the study plan the teacher assigns. Names stay in this
table: they are never sent to a model, a trace or a log. No message text is stored here; scrubbed text
lives only in the traces (socratic_tutor/trace.py). "Forget my data" deletes a
student's rows here as well as in the learner store and the checkpointer.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from socratic_tutor import config

RETENTION_DAYS = 90  # matches MEMORY_POLICY.md ("90 days of inactivity")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    student_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    consent INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    cost_usd REAL NOT NULL DEFAULT 0,
    turns INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    student_id TEXT NOT NULL,
    at TEXT NOT NULL,
    mode TEXT NOT NULL,
    latency_s REAL,
    cost_usd REAL,
    llm_calls INTEGER,
    leak INTEGER NOT NULL DEFAULT 0,
    blocked TEXT,
    misconception_id TEXT,
    concept_id TEXT,
    mastery_delta REAL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    session_id TEXT,
    kind TEXT NOT NULL,
    detail TEXT,
    at TEXT NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pending_interrupts (
    thread_id TEXT PRIMARY KEY,
    student_id TEXT,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roster (
    student_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS study_plans (
    student_id TEXT PRIMARY KEY,
    concepts_json TEXT NOT NULL,
    note TEXT,
    due TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approval_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    action TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    outcome TEXT NOT NULL,
    at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class OpsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (config.INDEX_DIR / "ops.db")
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock, self._connect() as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur

    def _all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    # sessions and turns ---------------------------------------------------
    def start_session(self, session_id: str, student_id: str, mode: str, consent: bool) -> None:
        self._exec(
            "INSERT OR IGNORE INTO sessions (session_id, student_id, mode, consent, started_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, student_id, mode, int(consent), now()),
        )

    def session(self, session_id: str) -> dict[str, Any] | None:
        rows = self._all("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        return rows[0] if rows else None

    def record_turn(self, **turn: Any) -> None:
        turn.setdefault("at", now())
        keys = ", ".join(turn)
        marks = ", ".join("?" for _ in turn)
        self._exec(f"INSERT INTO turns ({keys}) VALUES ({marks})", tuple(turn.values()))
        self._exec(
            "UPDATE sessions SET turns = turns + 1, cost_usd = cost_usd + ? WHERE session_id = ?",
            (float(turn.get("cost_usd") or 0.0), turn["session_id"]),
        )

    def session_progress(self, session_id: str) -> tuple[float, float]:
        """Minutes since the session started, and the total mastery gained in it."""
        session = self.session(session_id)
        if session is None:
            return 0.0, 0.0
        started = datetime.fromisoformat(session["started_at"])
        minutes = (datetime.now(timezone.utc) - started).total_seconds() / 60
        gained = self._all("SELECT COALESCE(SUM(mastery_delta), 0) AS g FROM turns WHERE session_id = ?", (session_id,))[0]["g"]
        return minutes, float(gained)

    # alerts ------------------------------------------------------------------
    def add_alert(self, student_id: str, session_id: str | None, kind: str, detail: str) -> None:
        self._exec("INSERT INTO alerts (student_id, session_id, kind, detail, at) VALUES (?, ?, ?, ?, ?)", (student_id, session_id, kind, detail, now()))

    def open_alerts(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM alerts WHERE acknowledged = 0 ORDER BY at DESC")

    def ack_alert(self, alert_id: int) -> bool:
        return self._exec("UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,)).rowcount > 0

    def has_open_alert(self, student_id: str, kind: str) -> bool:
        return bool(self._all("SELECT 1 FROM alerts WHERE student_id = ? AND kind = ? AND acknowledged = 0", (student_id, kind)))

    # graph interrupts awaiting a teacher -------------------------------------------
    def save_interrupt(self, thread_id: str, student_id: str, payload_json: str, payload_hash: str) -> None:
        self._exec(
            "INSERT OR REPLACE INTO pending_interrupts (thread_id, student_id, payload_json, payload_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (thread_id, student_id, payload_json, payload_hash, now()),
        )

    def pending_interrupts(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM pending_interrupts ORDER BY created_at")

    def clear_interrupt(self, thread_id: str) -> None:
        self._exec("DELETE FROM pending_interrupts WHERE thread_id = ?", (thread_id,))

    def log_approval(self, item_id: str, action: str, payload_hash: str, outcome: str) -> None:
        self._exec("INSERT INTO approval_log (item_id, action, payload_hash, outcome, at) VALUES (?, ?, ?, ?, ?)", (item_id, action, payload_hash, outcome, now()))

    def approval_log(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM approval_log ORDER BY id DESC LIMIT ?", (limit,))

    # teacher dashboard ------------------------------------------------------------
    def dashboard_numbers(self) -> dict[str, Any]:
        rows = self._all(
            "SELECT COUNT(*) AS sessions, COALESCE(AVG(cost_usd), 0) AS avg_cost, COALESCE(SUM(turns), 0) AS turns FROM sessions WHERE turns > 0"
        )[0]
        leaks = self._all("SELECT COUNT(*) AS n FROM turns WHERE leak = 1")[0]["n"]
        blocked = self._all("SELECT COUNT(*) AS n FROM turns WHERE blocked IS NOT NULL")[0]["n"]
        mastery = self._all(
            "SELECT concept_id, ROUND(AVG(mastery_delta), 3) AS avg_delta, COUNT(*) AS n FROM turns WHERE mastery_delta IS NOT NULL AND concept_id IS NOT NULL GROUP BY concept_id"
        )
        return {
            "sessions": rows["sessions"],
            "turns": rows["turns"],
            "avg_cost_per_session_usd": round(rows["avg_cost"], 5),
            "answer_leaks": leaks,
            "blocked_turns": blocked,
            "mastery_change_by_concept": mastery,
        }

    def misconceptions_from_turns(self) -> list[dict[str, Any]]:
        return self._all(
            "SELECT misconception_id, COUNT(DISTINCT student_id) AS students FROM turns WHERE misconception_id IS NOT NULL GROUP BY misconception_id ORDER BY students DESC"
        )

    # class list and study plans (teacher-side) ----------------------------------
    def add_student(self, student_id: str, display_name: str) -> None:
        self._exec(
            "INSERT INTO roster (student_id, display_name, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(student_id) DO UPDATE SET display_name = excluded.display_name",
            (student_id, display_name, now()),
        )

    def roster(self) -> dict[str, str]:
        return {r["student_id"]: r["display_name"] for r in self._all("SELECT student_id, display_name FROM roster ORDER BY display_name COLLATE NOCASE")}

    def set_plan(self, student_id: str, concepts: list[str], note: str, due: str | None) -> None:
        self._exec(
            "INSERT INTO study_plans (student_id, concepts_json, note, due, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(student_id) DO UPDATE SET concepts_json = excluded.concepts_json, note = excluded.note, due = excluded.due, updated_at = excluded.updated_at",
            (student_id, json.dumps(concepts), note, due, now()),
        )

    def plan(self, student_id: str) -> dict[str, Any] | None:
        rows = self._all("SELECT * FROM study_plans WHERE student_id = ?", (student_id,))
        if not rows:
            return None
        row = rows[0]
        return {"concepts": json.loads(row["concepts_json"]), "note": row["note"] or "", "due": row["due"], "updated_at": row["updated_at"]}

    def plans(self) -> dict[str, dict[str, Any]]:
        return {r["student_id"]: r for r in self._all("SELECT student_id, concepts_json, due, updated_at FROM study_plans")}

    def last_active(self) -> dict[str, str]:
        return {r["student_id"]: r["at"] for r in self._all("SELECT student_id, MAX(started_at) AS at FROM sessions GROUP BY student_id")}

    # privacy ----------------------------------------------------------------------
    def sessions_of(self, student_id: str) -> list[str]:
        return [r["session_id"] for r in self._all("SELECT session_id FROM sessions WHERE student_id = ?", (student_id,))]

    def forget(self, student_id: str) -> dict[str, int]:
        counts = {}
        for table in ("turns", "alerts", "sessions", "pending_interrupts", "roster", "study_plans"):
            counts[table] = self._exec(f"DELETE FROM {table} WHERE student_id = ?", (student_id,)).rowcount
        return counts

    def purge_expired(self) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
        old = self._all("SELECT DISTINCT student_id FROM sessions WHERE started_at < ? AND student_id NOT IN (SELECT student_id FROM sessions WHERE started_at >= ?)", (cutoff, cutoff))
        for row in old:
            self.forget(row["student_id"])
        return len(old)
