# Operations guide (R6: deployment and operations)

## Services (`docker compose up --build`)

| Service | Port | Purpose |
|---|---|---|
| `app` | 8000 | FastAPI: student view, teacher view, streaming chat, approvals, `/metrics`, `/healthz` |
| `chroma` | internal | vector store, ready for the dense half of hybrid retrieval (R2) |
| `prometheus` | 9090 | scrapes `/metrics`, evaluates `observability/prometheus/alert_rules.yml` |
| `grafana` | 3000 | provisioned dashboard `observability/grafana/dashboards/socratic.json` |
| `eval` (profile `eval`) | — | runs `evalkit.runner`; the only container that mounts `eval_heldout/` |
| `mcp-*` (commented out) | 8101–8104 | the four FastMCP servers; enable each when R4's server module exists |

Persistent state lives in the `app-index` volume: NCERT index, learner store, LangGraph checkpoints (`checkpoints.sqlite`) and operational records (`ops.db`). Scrubbed traces go to `./results/traces/`.

## One versioned config

`config/models.yaml` holds every model ID, sampling setting, budget and prompt file (with version). Bump `config_version` when anything changes. Every eval row records the version and the resolved model IDs. An UPPER_CASE environment variable overrides one value for a single run.

## Streaming and "who decided"

`POST /api/chat` streams server-sent events: one `step` event per graph node as it finishes, then the `reply`. The student view lights up each box and shows whether a model, code or a person made that decision (`NODE_DECIDER` in `socratic_tutor/web/server.py`; R3 keeps it in sync with the graph).

## Stop and resume (L8 demo)

Every session is a LangGraph thread stored in the SQLite checkpointer.

1. Start a turn; stop the app mid-run (`docker compose stop app`, or Ctrl-C locally).
2. Start it again.
3. `GET /api/session/<id>/state` shows the checkpoint and the node that would run next.
4. `POST /api/session/<id>/resume` continues from that checkpoint.

The demo is clearest once the graph has several real LLM nodes (R3); with the current placeholder nodes a turn finishes too fast to interrupt.

## Teacher approval tied to the exact payload (L14 demo)

- Items come from the question bank (`status = pending_approval`) and from graph `interrupt()`s raised by the question setter.
- Each item shows the SHA-256 hash of its payload. Approve, edit and reject must send the hash the teacher saw.
- An edit stores a new version with a new hash. Any approval carrying the old hash is refused with HTTP 409 (`stale_approval`) and counted in `socratic_stale_approvals_total`.
- Before the question setter is wired in, `python scripts/seed_demo.py` adds three `[DEMO]` items (answer keys from the calculator) so the gate can be shown.

Demo: open an item → Save edit → press the earlier "Approve" in a second tab: refused → approve the new version: published.

## Alerts

| Alert | Rule | Meaning |
|---|---|---|
| `AnswerLeakSpike` (the required working alert) | more than 2 leaks in 10 minutes | the output guardrail or tutor prompt is letting answers through |
| `TutorErrors` | more than 5 errors in 10 minutes | something is broken |
| `DistressAlertWaiting` | any distress hand-off in 5 minutes | a teacher must check the teacher view now |

Alert demo: set `OPS_DEMO=1` in `.env`, restart, sign in to the teacher view, then in the browser console run `fetch('/api/ops/emit-test-leak?count=5', {method: 'POST'})`. These leaks carry `source="synthetic"`; the dashboard's 24-hour leak count shows `source="live"` only. Within about a minute Prometheus shows `AnswerLeakSpike` as firing. Take a screenshot for the report.

## Metrics (Prometheus names)

`socratic_requests_total{mode,outcome}`, `socratic_request_latency_seconds`, `socratic_sessions_started_total`, `socratic_answer_leaks_total{source}`, `socratic_guardrail_blocks_total{reason}`, `socratic_distress_alerts_total`, `socratic_stuck_students_count`, `socratic_pending_approvals`, `socratic_teacher_approval_latency_seconds`, `socratic_stale_approvals_total`, `socratic_llm_cost_dollars_total`, `socratic_llm_calls_total`, `socratic_turn_cost_dollars`, `socratic_mastery_delta`, `socratic_class_misconception_students{misconception_id}`, `socratic_errors_total{where}`.

The teacher view covers what the brief asks for: misconceptions by concept across the class, answer leaks, mastery by concept, waiting approvals, cost per session and alerts. Grafana covers the operator's view.

## Traces

`socratic_tutor/trace.py` writes one JSONL record per LLM call, tool call and turn to `results/traces/<date>.jsonl`, after removing phone numbers, e-mail addresses and "my name is …" names. The red-team case `ATK_28` checks that a phone number typed by a student never appears in a trace. Optional LangSmith: set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY`.

## Privacy operations

- `POST /api/forget_me` (the "Forget my data" button) deletes the learner record, every checkpoint thread of the student's sessions, and their operational rows.
- `OpsStore.purge_expired()` deletes operational records after 90 days of inactivity, matching MEMORY_POLICY.md. Run it from a daily cron or scheduled task in a real deployment.
- No message text is stored outside the scrubbed traces.

## CI (`.github/workflows/ci.yml`)

1. `tests`: pytest, fully offline.
2. `eval-gate`: fetch NCERT PDFs (cached; from the private `NCERT_PDF_ZIP_URL` secret, because ncert.nic.in refuses GitHub's servers), build the index, `scripts/check_threshold.py` fails the build if dev Recall@5 drops below `config/eval_thresholds.yaml` (0.85; current baseline 0.9028), then a stub smoke run of every suite.
3. `docker`: validates the compose file, builds the image, and checks that `eval_heldout` is not inside it.

The guide asks for one failed CI run with an explanation; see `docs/CI_FAILURE.md`.
