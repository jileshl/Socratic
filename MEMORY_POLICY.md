# Socratic Tutor: memory and privacy policy

*One page, as the guide asks (p.3, L9): what is stored about a minor, why, when, who can read it, and how it is corrected or deleted. Checked against `main` at #76 on 13 Nov 2026.*

**The rule:** the tutor remembers a student's learning, never their identity. Models, traces and the learner store only ever see a random ID (`stu_…`).

## 1. What is stored, and why

| Kept | Where | Why | When it is written |
| :--- | :--- | :--- | :--- |
| Mastery per topic, 0 to 1: the average of the last three quiz scores | learner store (`learner_store.py`, SQLite) | Plans the next topic on the concept graph; the tutor starts further up the hint ladder on a mastered topic | After each graded quiz answer, by the supervisor (code) |
| Misconceptions seen, first and last seen, sorted or not | learner store | The tutor addresses a repeated mix-up head-on; flashcards put the student's own mix-ups first | When the diagnostician names one |
| Teaching lessons that worked | learner store | Reuses explanations that helped this student | When a mix-up is sorted |
| Recent quiz attempts and failure streaks per topic | learner store | The teacher's rule: alert after 3 misses in a row on one topic | After each quiz answer |
| The conversation of a session | LangGraph checkpointer (`.index/checkpoints.sqlite`) | Short-term memory: the tutor reads the last few turns; a session can stop and resume; the page shows the chat again after a reload | Each turn |
| A first name or nickname, and a 4-digit sign-in code | teacher's class list (`ops.db`, `roster`) | The teacher sees names; a student picks theirs on a shared device and types the code once | When the teacher adds the student |
| Study plan from the teacher (topics, note, due date) | `ops.db`, `study_plans` | "My plan" | When the teacher assigns it |
| Turn records: time, cost, latency, topic, misconception ID, mastery change, outcome; alerts | `ops.db` | Dashboard, metrics, alerts | Each turn |
| Flashcard progress | the student's own browser (`localStorage`) | Missed cards come back sooner | On the device only; never sent anywhere |

**Short-term context** is trimmed: the tutor sees only the last four turns of the conversation, plus a one-line summary of the learner record (mastery, mastered topics, mix-ups seen), with no name.

## 2. Never stored
- Real names in the learner store, traces or prompts; phone numbers, e-mail addresses, school names, locations, photos. Phone numbers and e-mail addresses typed in chat are masked before any model or trace sees them (`policy.mask_personal_details`).
- Age, gender, family or money details, disciplinary remarks.
- **Distress:** no distress label or message is written to the learner record. A distress message raises a teacher alert (in `ops.db`, with a fixed wording, not the message) and gets a calm fixed reply. The conversation turn itself is in the session's checkpoint like any other turn and is deleted with it.

## 3. Who can read it
- **The student:** their own record, under "My progress". A named student needs their sign-in code once per device, so a classmate on the same device can't open their record.
- **The teacher** (PIN sign-in): each student's record, class summaries, alerts, plans and the sign-in codes.
- **The agents:** the supervisor (code) reads and writes the learner record (also exposed as the learner-store MCP server, whose tools only the supervisor may use); the tutor gets the one-line summary above; no agent sees names.
- **Nobody else:** the data stays on the school's machine. It is never sold or used to train models. Model calls go to OpenRouter with the random ID only.

## 4. Retention, correction and deletion
- **Expiry:** a learner record unused for 90 days is deleted automatically when the app starts (`purge_expired_profiles`).
- **Correction:** mastery is recomputed from the last three quiz scores, so a wrong score washes out; the teacher can rename a student or change a plan; misconceptions are marked "sorted" when the student shows they've fixed them.
- **Deletion:** "Delete my data" (My progress) deletes a device's own record: the learner record, quiz attempts, session checkpoints and ops rows, with a signed erasure receipt. For a **named** student, the teacher deletes it from the teacher page ("Delete <name>'s data", two clicks), which also removes them from the class list; the student page can't, so a classmate can't wipe someone else's record.
- **Memory off:** experiment E4 runs the same students with the learner record emptied, to measure what memory adds.

## 5. Open points before real students
A school would need to confirm: consent from parents, a real helpline number (it is a placeholder today), per-student logins instead of four-digit codes, and who at the school is responsible for alerts.
