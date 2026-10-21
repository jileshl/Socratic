# Socratic Tutor — Learner Memory & Privacy Policy

## 1. Purpose & Guiding Principles
Socratic Tutor is an AI-assisted learning platform designed for minor students (Class 9 and 10, typically ages 14–16). 
Our memory architecture adheres to the **Principle of Data Minimization**: we retain only what is strictly necessary to model a student's conceptual mastery and tailor educational scaffolding.

The core policy holds:
> **The system remembers the student's learning progress, never their personal identity.**

---

## 2. What Is Stored
Data stored in the persistent `learner-store` is strictly partitioned under a **Pseudonymous Identifier (UUIDv4)** generated upon session initialization.

| Category | Specific Attributes Stored | Purpose & Justification |
| :--- | :--- | :--- |
| **Concept Mastery** | Float score $[0.0, 1.0]$ per concept ID (e.g., `concept_mirror_formula: 0.75`) | Required by the Study Planner to navigate the concept prerequisite graph. |
| **Misconception Log** | Catalogued misconception ID (e.g., `MISCON_LIGHT_04`), timestamp, resolution status | Prevents repeating failed teaching tactics; informs diagnostician. |
| **Scaffolding Lessons** | IDs of Reflexion lessons that successfully resolved a misconception | Adapts future hints to teaching strategies known to work for this student. |
| **Quiz Performance** | Pre-quiz score, post-quiz score, date of attempt | Measures progression and flags students stuck on a concept for $\ge 3$ sessions. |

---

## 3. What Is Strictly Forbidden / Never Stored
1. **Personally Identifiable Information (PII)**: Real names, email addresses, phone numbers, school names, geographic location, or photos.
2. **Raw Chat Transcripts in Long-Term Memory**: Free-form student messages are trimmed from active working memory after session termination and are scrubbed of any inadvertent PII before storage in traces.
3. **Sensitive Minor Attributes**: Age, gender, socioeconomic indicators, or disciplinary remarks.

---

## 4. Who Can Access the Memory Store
1. **The Orchestration Agent (`Supervisor`)**: Reads mastery state to route between Practice Mode and Quiz Mode.
2. **The Diagnostician & Tutor Agents**: Reads prior misconceptions and effective explanations.
3. **The Authenticated Classroom Teacher**: Aggregated, anonymized cohort analytics (e.g., *"14 students in Class 10A struggle with sign conventions"*). Individual records can only be viewed in the context of academic intervention when a student is stuck.
4. **Third-Party / Commercial Exclusion**: Learner data is never sold, shared with ad networks, or used to train external commercial foundation models.

---

## 5. Retention, Expiry, and Deletion ("Right to be Forgotten")
* **Default Retention Window**: Learner profiles automatically expire and are purged after **90 days of inactivity** unless explicitly renewed by the school/student.
* **Immediate Deletion Command (`/forget_me`)**:
  * Any student or parent can issue the command `/forget_me` or click "Reset My Profile" in the UI.
  * This triggers a hard cascade delete:
    1. Removes all entries associated with the student's pseudonymous UUID from the SQLite checkpointer.
    2. Deletes the concept mastery vector and misconception history from the `learner-store`.
    3. Confirms deletion to the user with a cryptographic erasure receipt.
