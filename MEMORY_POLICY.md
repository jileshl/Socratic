# Socratic Tutor — Learner Memory & Privacy Policy

## 1. Purpose & Guiding Principles
Socratic Tutor is an AI-assisted learning platform designed for minor students (Class 9 and 10, typically ages 14–16). 
Our memory architecture adheres to the **Principle of Data Minimization**: we retain only what is strictly necessary to model a student's conceptual mastery and tailor educational scaffolding.

The core policy holds:
> **The system remembers the student's learning progress, never their personal identity.**

---

## 2. What Is Stored
Data stored in the persistent `learner-store` is partitioned under a **Pseudonymous Identifier**. The production session layer should generate UUIDv4 identifiers; the current store accepts a caller-provided ID and does not validate UUID format.

| Category | Specific Attributes Stored | Purpose & Justification |
| :--- | :--- | :--- |
| **Concept Mastery** | Float score $[0.0, 1.0]$ per concept ID (e.g., `concept_mirror_formula: 0.75`). Quiz-derived mastery is the arithmetic mean of up to the latest three quiz scores; `update_mastery()` explicitly sets a supplied score. | Required by the Study Planner to navigate the concept prerequisite graph. |
| **Misconception Log** | Catalogued misconception ID, first/last-seen timestamps, resolution status | Prevents repeating failed teaching tactics; informs diagnostician. |
| **Scaffolding Lessons** | IDs of Reflexion lessons that successfully resolved a misconception | Adapts future hints to teaching strategies known to work for this student. |
| **Quiz Performance** | Score, concept ID, duration, and timestamp for recent attempts | Measures progression and computes per-concept failure streaks and stuck thresholds. |
| **Failure Streaks** | Consecutive below-threshold quiz results per concept; a passing result resets the streak. This counts quiz results, not distinct sessions. | Supports the teacher-validated three-consecutive-failures stuck-learner rule. |
| **Class-list name (teacher side, not learner memory)** | A first name or nickname the teacher types for a student's random ID (`roster` table in the ops store, `socratic_tutor/web/ops_store.py`). | Lets the teacher see names instead of IDs and lets a student pick their name on a shared class device. It is shown only in the teacher view and in the student page's "Learning as" list. It is never passed to a model, a trace or a log: the graph, the agents and the traces only ever see the random ID. |
| **Flashcard progress (student's browser only)** | For each card, how many times in a row the student said "I had it" (`localStorage`, keyed by the random ID). | Puts missed cards first. It never leaves the device, is not sent to the server or a model, and is cleared with the browser's site data. Points, levels and badges are not stored at all: they are worked out from the learner record on each request (`socratic_tutor/web/game.py`). |
| **Assigned study plan (teacher side)** | Ordered topic IDs, the teacher's note and an optional due date (`study_plans` table in the ops store). | The student's "My plan" view. The suggested part of the plan is not stored: code works it out from mastery and open misconceptions on every request (`socratic_tutor/web/study_plan.py`). |

---

## 3. What Is Strictly Forbidden / Never Stored
1. **Personally Identifiable Information (PII)**: Real names, email addresses, phone numbers, school names, geographic location, or photos. The one exception is the teacher's class list above: a first name or nickname the teacher chooses, kept outside learner memory, never sent to a model, and deleted with "Delete my data". Teachers should use first names or nicknames, not full names.
2. **Raw Chat Transcripts in Learner Profiles**: `LearnerStore` does not store raw student messages. The graph state can contain dialogue, however, and a caller-supplied LangGraph checkpointer may persist that state. The app currently does not configure a checkpointer, but checkpoint transcript expiry, PII scrubbing, and deletion are not generally enforced; do not claim those controls until implemented.
3. **Sensitive Minor Attributes**: Age, gender, socioeconomic indicators, or disciplinary remarks.

### Academic Distress Signals

An academic-distress indicator is sensitive learner data and is **not part of persistent learner memory**. The learner store has no distress field and must not store the triggering message or a distress label. Because the current graph places `teacher_alert_triggered` in its state, callers must not attach a persistent LangGraph checkpointer to student distress turns until checkpoint redaction is implemented and tested. This restriction is a policy requirement; the current code does not enforce it automatically.

The current input guardrail recognizes only a small set of phrases. It does not provide the required supportive micro-step, continued low-difficulty tutoring, or teacher-dashboard alert. No teacher currently receives a distress notification. If this feature is implemented, the proposed visibility is limited to the assigned safeguarding teacher; no agent, peer, or unrelated teacher should access an individual flag. No retention period for a stored flag is approved: do not persist one until the school/team approves an explicit expiry and deletion rule. Under the current no-persistence rule, the in-memory signal should be discarded with the request and must not be copied to traces, profiles, or checkpoints.

---

## 4. Who Can Access the Memory Store
1. **The Orchestration Agent (`Supervisor`)**: Intended to read pseudonymous learning progress to route between Practice Mode and Quiz Mode; it must not receive persistent distress data under the current policy.
2. **The Diagnostician & Tutor Agents**: Intended to read prior misconceptions and effective explanations, not raw distress messages or persistent distress labels.
3. **The Authenticated Classroom Teacher**: Intended to see aggregated, anonymized cohort analytics. Authentication, role-based access, and cohort aggregation are not implemented in the current app scaffold.
4. **Third-Party / Commercial Exclusion**: Learner data is never sold, shared with ad networks, or used to train external commercial foundation models.

---

## 5. Retention, Expiry, and Deletion ("Right to be Forgotten")
* **Default Retention Window**: `LearnerStore.purge_expired_profiles()` can purge profiles after **90 days of inactivity**. Session registration creates the learner row even before a quiz/mastery record exists, so session-only learners are included in expiry. A scheduled or application-level caller is still required; automatic expiry is not currently running.
* **Immediate Deletion API (`forget_me`)**:
  * `LearnerStore.forget_me(student_id, checkpointer)` removes learner-store profile, quiz-attempt, and session-link rows and calls `delete_thread()` for registered LangGraph thread IDs.
  * Callers must register each learner/thread association and pass the active checkpointer. The graph/app does not currently register sessions or expose a `/forget_me` command or UI route, so user-facing deletion and checkpoint cascade are not wired into the product yet.
  * No cryptographic erasure receipt is implemented. Confirmation must report only the deletion work the caller actually completed.
