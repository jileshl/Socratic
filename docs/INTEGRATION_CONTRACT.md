# Integration contract: what the app and the eval harness read from the agent (for R3 and R4)

The web service (R6) and the evaluation harness (R5) treat the graph as a black box. They work with the current placeholder graph and will report real numbers as soon as the nodes do real work, provided these points hold.

## 1. `build_graph(checkpointer=...)`

Keep the signature. The app passes a `SqliteSaver` (stop/resume); the harness passes an `InMemorySaver`. Each session is a thread (`thread_id` = session ID).

## 2. State fields that are read (`socratic_tutor/state.py`)

| Field | Read by | Meaning |
|---|---|---|
| `response` | app, eval | the reply shown to the student (the app resets it to "" each turn) |
| `citations` | app, eval | list of strings containing NCERT section IDs such as "9.2.4"; the eval checks they exist and are from the right chapter |
| `identified_misconception` | app, eval | `{"id": "MISCON_…", ...}` from `data/misconceptions.json` (or the ID string); scored against the simulated student's seeded misconception |
| `steps` | app, eval | node names in order (`operator.add`); drives the live boxes |
| `injection_detected` | app, eval | the input guardrail blocked the message |
| `teacher_alert_triggered` | app, eval | distress or stuck: creates a teacher alert immediately |
| `answer_leak_flag` | app | the output guardrail caught a leak in practice mode: counted in `socratic_answer_leaks_total` |
| `current_concept_id` | app | the concept being worked on, for the mastery-change metric |
| `next_recommended_concept` | app | shown to the student |

## 3. Teacher approval through `interrupt()` (R4)

When the question setter proposes a set, pause with `interrupt(payload)`, where the payload is JSON-serialisable (for example `{"set_id": ..., "questions": [{"concept_id", "difficulty", "prompt", "gold_answer"}]}`). The app stores it with its SHA-256 hash and resumes with:

```python
Command(resume={"action": "approve" | "reject", "payload_hash": "<hash>", "payload": {...}})
```

After resuming, `question_bank.publish` must run only for `action == "approve"`, and should recompute the hash of what it is about to publish and refuse if it differs. Edits happen in the teacher view and produce a new hash before any approval.

## 4. Experiment switches (no agent code changes needed)

E2–E4 switch features off from the evaluation side (`evalkit/ablations.py`) by temporarily replacing these functions during a run. Keep their names, or tell R5 when you rename one:

| Switch | Patch point | Owner |
|---|---|---|
| Defences off (E2) | `socratic_tutor.policy.check_input_guardrails`, `check_answer_leak` | R4 |
| Memory off (E4) | `LearnerStore.get_profile` returns an empty profile; `update_*`, `record_*`, `add_*`, `set_*` do nothing | R2 |
| Playbook on/off (E3) | `ReflexionPlaybook.get_lessons_for_misconception` | R3 |

For these to measure anything, the graph must actually read the learner store and the playbook.

## 5. Who decides each node

Update `NODE_DECIDER` in `socratic_tutor/web/server.py` when you add or change nodes (`model`, `code` or `person`).

## 6. Cost and tracing

Invoke models inside the graph so LangChain callbacks propagate; the app's cost meter and the scrubbed trace writer (`socratic_tutor/trace.py`) then see every call. **Request to R3:** in `socratic_tutor/llm.py`, add `extra_body={"usage": {"include": True}}` to `ChatOpenAI(...)` so OpenRouter returns each call's cost. Until then, cost per session for the team's graph shows as blank (never estimated).

## 7. Held-out data

Nothing under `socratic_tutor/` may open the evaluation datasets (gold questions, student cards, quizzes, practice problems, red team); `tests/test_eval_isolation.py` enforces it. The Reflexion loop runs on dev students only.

## 8. MCP servers (R4)

The math-tools server uses stdio, so it runs inside the app container; no extra Docker service is needed. If a server later moves to HTTP, add it as a service in `docker/docker-compose.yml`.
