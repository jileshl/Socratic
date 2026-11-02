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

## 4. Experiment switches (`socratic_tutor/runtime_flags.py`)

| Switch | Who must honour it | Already wired |
|---|---|---|
| `defences_on()` | input/output guardrails, hooks (R4) | `policy.check_input_guardrails`, `policy.check_answer_leak` |
| `memory_on()` | learner-store reads/writes (R2/R3) | not yet: E4 memory on/off is meaningless until it is |
| `playbook_on()` | tutor loading Reflexion lessons (R3) | not yet: E3 needs it |

## 5. Who decides each node

Update `NODE_DECIDER` in `socratic_tutor/web/server.py` when you add or change nodes (`model`, `code` or `person`).

## 6. Cost and tracing

Use `socratic_tutor.llm.get_llm()` (it asks OpenRouter to return each call's cost) and invoke models inside the graph so LangChain callbacks propagate. The app's meter, the eval's meter and the scrubbed trace writer then see every call without any extra code.

## 7. Held-out data

Nothing under `socratic_tutor/` may read `eval_heldout/`; a test enforces it. The Reflexion loop runs on `eval/dev/` students only.

## 8. MCP servers (R4)

`docker-compose.yml` has commented `mcp-math`, `mcp-textbook`, `mcp-learner` and `mcp-qbank` services. When a FastMCP server module exists, uncomment its service, fix the module path, and load it into the graph with `langchain-mcp-adapters` over HTTP.
