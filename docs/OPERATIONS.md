# Operations (R6: deployment and operations)

## Start everything

```bash
cp .env.example .env              # add OPENROUTER_API_KEY, change TEACHER_PIN
docker compose -f docker/docker-compose.yml up --build      # or: make up
```

| URL | What |
|---|---|
| http://localhost:8000 | student view (practice and quiz) |
| http://localhost:8000/teacher | teacher view (PIN from `.env`) |
| http://localhost:3000 | Grafana, dashboard "Socratic Tutor" |
| http://localhost:9090 | Prometheus, alert `AnswerLeakSpike` |

Without Docker: `pip install -r requirements.txt`, `PYTHONPATH=. python scripts/build_index.py --force`, then `PYTHONPATH=. python -m socratic_tutor.app`. On Windows without `make`, run the commands from the Makefile directly.

All Docker files are in `docker/`: `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `prometheus/` and `grafana/`. The index is built on first start from the NCERT PDFs in `data/`. The MCP tool servers (R4) use stdio, so they run inside the app container.

## Configuration

One file: `socratic_tutor/config.py` holds every model ID, budget and threshold, including the evaluation and operations settings at the end of the file. An environment variable with the same name overrides one value for a single run. Evaluation prompts are versioned in `evalkit/prompts.py`.

## The web service (`socratic_tutor/web/`)

- **Student view:** `POST /api/chat` streams one event per graph step, then the reply. The page lights up each box and shows whether a model, code or a person made that decision (`NODE_DECIDER` in `server.py`; R3 keeps it in sync with the graph).
- **Stop and resume:** each session is a LangGraph thread in a SQLite checkpointer (`.index/checkpoints.sqlite`). `GET /api/session/<id>/state` shows where it stopped; `POST /api/session/<id>/resume` continues.
- **Teacher view (PIN sign-in):** this is the only way to get the teacher role; typing "I'm the teacher" in chat unlocks nothing. It shows:
  - class misconceptions by concept, mastery by concept, cost per session
  - approvals and alerts
  - transcript labelling for the judge (the teacher's 1–5 rubric)
- **Approvals tied to the exact payload:** each item shows its SHA-256 hash, and every decision must send the hash the teacher saw. An edit creates a new hash, so an approval carrying the old one is refused (HTTP 409, counted as a stale approval). `python scripts/seed_demo.py` adds three `[DEMO]` items for the demo until the question setter proposes its own.
- **Alerts:**
  - distress: immediately
  - stuck: 3 sessions on one concept, or 10+ minutes in a session without progress (both teacher-validated)
- **Forget my data:** deletes the learner record, every checkpoint thread of the student and their operational rows.

## Metrics and alerts

Prometheus scrapes `/metrics`. The main metrics are:
- turns, latency
- answer leaks, guardrail blocks, distress alerts
- stuck students, waiting approvals, approval latency, stale approvals
- LLM cost and calls, mastery change
- class misconceptions, errors

Alerts (`docker/prometheus/alert_rules.yml`):
- `AnswerLeakSpike`: more than 2 leaks in 10 minutes. This is the required working alert.
- `TutorErrors`
- `DistressAlertWaiting`

Alert demo: set `OPS_DEMO=1`, sign in to the teacher view, then run `fetch('/api/ops/emit-test-leak?count=5', {method: 'POST'})` in the browser console. These leaks are labelled `source="synthetic"` and are kept out of the dashboard's leak count.

## Traces

`socratic_tutor/trace.py` writes one JSON line per LLM call, tool call and turn to `.cache/traces/<date>.jsonl`, after removing phone numbers, e-mail addresses and "my name is …" names. The same file has the cost meter shared by the app and the eval harness. Optionally, LangSmith can also receive traces (`LANGSMITH_TRACING=true`).

## CI (`.github/workflows/ci.yml`)

1. `tests`: pytest, offline.
2. `eval-gate`:
   - builds the index from the PDFs in `data/`
   - `scripts/check_threshold.py` fails the build if dev Recall@5 (Aman's hybrid retrieval) drops below `CI_MIN_RECALL_AT_5` = 0.90, the BM25 level
   - then a stub smoke run of every eval suite
3. `docker`: validates the compose file and builds the image.

### The failed CI run, explained

On 2 Nov the first CI runs of PR #14 failed in `eval-gate`:
- **What happened:** that version of the branch had stopped tracking the NCERT PDFs and downloaded them from ncert.nic.in instead. From GitHub's servers, ncert.nic.in reset one connection and sent an incomplete certificate chain for the other two downloads.
- **Why the job failed:** the index could not be built, so the gate could not run.
- **Fix:** the team decided to keep reading the chapters from `data/`, so CI now builds the index from the repository and never downloads from NCERT. Certificate checking was never turned off.
- Failed runs: https://github.com/jileshl/Socratic/actions/runs/41468473035 and /41468737613. Passing run after the fix: [link — TO FILL after the first green run].
