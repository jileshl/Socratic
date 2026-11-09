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

Without Docker: `pip install -r requirements.txt`, `python -m scripts.build_index --force`, then `python -m socratic_tutor.app`. These commands work the same on Windows. Without `make`, run the commands from the Makefile directly.

`docker/` holds three files: the `Dockerfile`, `docker-compose.yml` (which also contains the Prometheus and Grafana settings, written inline) and the Grafana dashboard. The index is built on first start from the NCERT PDFs in `data/`. The MCP tool servers (R4) use stdio, so they run inside the app container.

## Configuration

One file: `socratic_tutor/config.py` holds every model ID, budget and threshold, including the evaluation and operations settings at the end of the file. An environment variable with the same name overrides one value for a single run. Evaluation prompts are versioned in `evalkit/prompts.py`.

## The web service (`socratic_tutor/web/`)

- **Student view:** `POST /api/chat` streams one event per graph step, then the reply. The page lights up each box and shows whether a model, code or a person made that decision (`NODE_DECIDER` in `server.py`; R3 keeps it in sync with the graph).
- **Stop and resume:** each session is a LangGraph thread in a SQLite checkpointer (`.index/checkpoints.sqlite`). `GET /api/session/<id>/state` shows where it stopped; `POST /api/session/<id>/resume` continues.
- **Teacher view (PIN sign-in):** this is the only way to get the teacher role; typing "I'm the teacher" in chat unlocks nothing. It shows:
  - class misconceptions by concept, mastery by concept, cost per session
  - approvals and alerts
  - transcript labelling for the judge (the teacher's 1–5 rubric)
- **Approvals tied to the exact payload:** each item shows its SHA-256 hash, and every decision must send the hash the teacher saw. An edit creates a new hash, so an approval carrying the old one is refused (HTTP 409, counted as a stale approval). `python -m scripts.seed_demo` adds three `[DEMO]` items for the demo until the question setter proposes its own.
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

Alerts (`alert_rules` in `docker/docker-compose.yml`):
- `AnswerLeakSpike`: more than 2 leaks in 10 minutes. This is the required working alert.
- `TutorErrors`
- `DistressAlertWaiting`

Alert demo: set `OPS_DEMO=1`, sign in to the teacher view, then run `fetch('/api/ops/emit-test-leak?count=5', {method: 'POST'})` in the browser console. These leaks are labelled `source="synthetic"` and are kept out of the dashboard's leak count.

## Traces

`socratic_tutor/trace.py` writes one JSON line per LLM call, tool call and turn to `.cache/traces/<date>.jsonl`, after removing phone numbers, e-mail addresses and "my name is …" names. The same file has the cost meter shared by the app and the eval harness. Optionally, LangSmith can also receive traces (`LANGSMITH_TRACING=true`).

## CI

All CI steps are in the Makefile, so the same checks run on a laptop and on GitHub:

- `make ci-deps`: installs the packages with the CPU-only torch wheel (the default wheel bundles several GB of CUDA libraries that the app never uses). The Dockerfile does the same.
- `make ci`:
  - runs the tests
  - builds the index from the PDFs in `data/`
  - runs `scripts/check_threshold.py`, which fails if dev Recall@5 (Aman's hybrid retrieval) drops below `CI_MIN_RECALL_AT_5` = 0.90 in `config.py`, the BM25 level
  - smoke-runs every eval suite with the offline stand-in model
- `make docker-check`: validates the compose file and builds the image.

GitHub runs CI only from a file in `.github/workflows/`, so `ci.yml` there is a few lines that call these two targets and holds no settings of its own. Without that file there is no CI on GitHub, and no eval gate or failed-run evidence for L16.

### The failed CI run, explained

On 2 Nov the first CI runs of PR #14 failed in `eval-gate`:
- **What happened:** that version of the branch had stopped tracking the NCERT PDFs and downloaded them from ncert.nic.in instead. From GitHub's servers, ncert.nic.in reset one connection and sent an incomplete certificate chain for the other two downloads.
- **Why the job failed:** the index could not be built, so the gate could not run.
- **Fix:** the team decided to keep reading the chapters from `data/`, so CI now builds the index from the repository and never downloads from NCERT. Certificate checking was never turned off.
- Failed runs: https://github.com/jileshl/Socratic/actions/runs/41468473035 and /41468737613.

On 9 Nov, after `ci.yml` was added to the rebuilt branch (PR #33), `make ci` passed but `make docker-check` failed:
- **What happened:** the runner ran out of disk. `sentence-transformers` pulls in torch, and the default torch wheel brings several GB of CUDA libraries, once on the runner and again inside the image. One run also failed when PyPI cut off the 286 MB CUDA download.
- **Fix:** the CPU-only torch wheel is installed first, both on the runner (`make ci-deps`) and in the Dockerfile. `requirements.txt` is unchanged.
- Failed runs: https://github.com/jileshl/Socratic/actions/runs/42571534081 (out of disk while installing) and /42573684211 (out of disk while unpacking the image). Passing run after the fix (tests, index, Recall@5 gate, eval smoke run and Docker build): https://github.com/jileshl/Socratic/actions/runs/42574868301.
