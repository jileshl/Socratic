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

---

## 3. What Is Strictly Forbidden / Never Stored
1. **Personally Identifiable Information (PII)**: Real names, email addresses, phone numbers, school names, geographic location, or photos.
2. **Raw Chat Transcripts in Long-Term Memory**: Free-form student messages are trimmed from active working memory after session termination and are scrubbed of any inadvertent PII before storage in traces.
3. **Sensitive Minor Attributes**: Age, gender, socioeconomic indicators, or disciplinary remarks.

---

## 4. Who Can Access the Memory Store
1. **The Orchestration Agent (`Supervisor`)**: Intended to read mastery state to route between Practice Mode and Quiz Mode.
2. **The Diagnostician & Tutor Agents**: Intended to read prior misconceptions and effective explanations.
3. **The Authenticated Classroom Teacher**: Intended to see aggregated, anonymized cohort analytics. Authentication, role-based access, and cohort aggregation are not implemented in the current app scaffold.
4. **Third-Party / Commercial Exclusion**: Learner data is never sold, shared with ad networks, or used to train external commercial foundation models.

---

## 5. Retention, Expiry, and Deletion ("Right to be Forgotten")
* **Default Retention Window**: `LearnerStore.purge_expired_profiles()` can purge profiles after **90 days of inactivity**. Session registration creates the learner row even before a quiz/mastery record exists, so session-only learners are included in expiry. A scheduled or application-level caller is still required; automatic expiry is not currently running.
* **Immediate Deletion API (`forget_me`)**:
  * `LearnerStore.forget_me(student_id, checkpointer)` removes learner-store profile, quiz-attempt, and session-link rows and calls `delete_thread()` for registered LangGraph thread IDs.
  * Callers must register each learner/thread association and pass the active checkpointer. The graph/app does not currently register sessions or expose a `/forget_me` command or UI route, so user-facing deletion and checkpoint cascade are not wired into the product yet.
  * No cryptographic erasure receipt is implemented. Confirmation must report only the deletion work the caller actually completed.
