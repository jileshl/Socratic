# Evaluation guide (R5: evaluation and red team)

Everything here follows the capstone's evaluation protocol: a golden set split into dev and held-out, code checks first, a judge only where code cannot decide (calibrated against people), four experiments as config files, repeats on the final held-out comparison, and honest reporting of failures, costs and latency.

## What is measured, and how

| Question | Data | Decided by |
|---|---|---|
| Does the tutor find the student's misconception? | 40 simulated students (20 dev, 20 held-out), each with 1–2 seeded misconceptions | code: the diagnosed ID matches a seeded ID |
| Does it leak answers in practice mode? | the practice problem each simulated student brings | code: the final number (sign ignored, givens ignored) or every key phrase of a conceptual answer appears in a tutor reply |
| Does the student's quiz score improve? | 40 multiple-choice items, two parallel forms per misconception (pre and post) | code: chosen option = correct option; options shuffled per student so position bias cannot help |
| Are citations real and on topic? | NCERT section IDs in each reply | code: the section exists and belongs to the chapter being taught |
| Is the teaching good? | the session transcript | LLM judge (different model family), five yes/no criteria, calibrated with Cohen's kappa against 20+ human labels |
| Does retrieval find the right section? | 36 labelled retrieval queries; 64 gold questions | code: Recall@5, MRR |
| Does the grader agree with the answer key? | two labelled sample answers per gold question | code: grader verdict vs label |
| Do attacks succeed? | 34 attacks (teacher impersonation, answer extraction, encoding, pasted and data-path injection, prompt extraction, privacy, tool abuse, minor safety) | code: canary text, revealed answer, planted marker, DB state, missing teacher alert, etc. |
| Is legitimate work blocked? | 24 clean look-alike cases | code: refusal or block on a legitimate message |

A session counts as a **task success** when the post-quiz is fully correct and no answer leaked.

## Datasets

| File | Count | Who can read it |
|---|---|---|
| `eval/dev/gold_questions.jsonl` | 24 | dev (also `data/gold_questions.jsonl`, which the team already had) |
| `eval_heldout/gold_questions.jsonl` | 40 (12 from the team's original held-out + 28 new) | eval container only |
| `eval/dev/simulated_students.jsonl` | 20 | dev |
| `eval_heldout/simulated_students.jsonl` | 20 | eval container only |
| `eval/dev/practice_problems.jsonl` / `eval_heldout/practice_problems.jsonl` | 20 / 20 | dev / eval container only |
| `eval/quiz_bank.jsonl` | 40 | measurement only; the tutor never sees it |
| `redteam/attacks.jsonl`, `redteam/clean_cases.jsonl` | 34 / 24 | red-team runs |
| `redteam/fixtures/redteam_fixtures.json` | 4 poisoned passages, 1 planted learner record | added to the index or store only during the case that needs them, then removed |

Every numeric answer key is computed by `evalkit/reference_solver.py`, which is separate from the tutor's own calculator. `tests/test_eval_datasets.py` checks that the two agree and that each written answer matches the code answer.

**Held-out boundary.** `eval_heldout/` is excluded from the app image (`.dockerignore`) and mounted read-only only into the `eval` service. A test fails if any file under `socratic_tutor/` refers to it. Simulated students in both splits share misconceptions on purpose: E3 tests whether lessons learned per misconception on dev students carry over to new students.

**Separation of duties.** The guide requires that the person tuning the agent does not write the held-out cases, and the person building the defences does not write the attacks. R5 wrote the held-out additions, students, quiz and attacks. R1 should check the held-out questions against the written policy (see "Review before held-out runs").

## Running the experiments

Each experiment is a config in `eval/configs/`; the code is the same.

```bash
# dev runs (local is fine)
python -m evalkit.runner --config eval/configs/e1_c2.yaml --split dev

# held-out runs: only in the eval container
docker compose --profile eval run --rm eval --config eval/configs/e1_c2.yaml --split heldout --repeats 3

python -m evalkit.report          # tables for the evaluation report → results/report_tables.md
```

| Experiment | Configs | Notes |
|---|---|---|
| E1 does the agent justify its cost? | `e1_c0.yaml`, `e1_c1.yaml`, `e1_c2.yaml` | same model, guardrail and budget for all three; C0 and C1 are in `evalkit/systems.py` |
| E2 do the defences work? | `e2_defences_off.yaml`, `e2_defences_on.yaml` | attack success on 34 attacks, false blocks on 24 clean cases |
| E3 did the lessons help? | `e3_no_playbook.yaml`, `e3_playbook.yaml` | held-out only, after the playbook is frozen (committed); report lesson-generation cost from the Reflexion run |
| E4 signature ablation | `e4_memory_off.yaml` / `e4_memory_on.yaml` (two sessions per student); `e4_direct.yaml` / `e4_socratic.yaml` | compare leaks with quiz gains |
| Retrieval before/after | `retrieval.yaml` | run before and after one retrieval change; the git commit in the log tells them apart |
| Grading and retrieval on gold | `gold.yaml` | |

`--limit N` runs only the first N cases of each suite (quick checks). `--note "…"` is stored with the run.

Each run writes `results/runs/<run_id>/cases.jsonl` (every case, with transcripts), `summary.json`, and one row in `results/experiment_log.csv` with: git commit, config version, exact model IDs, switches, task success, leaks, policy violations, misconception hits, learning gain, judge verdicts, attack success, false blocks, Recall@5, MRR, grader agreement, cost per case, p50/p95 latency, errors and timeouts. Failed and timed-out cases are kept.

Costs come from OpenRouter's own usage accounting. If a provider does not report a cost, the cell is left blank; nothing is estimated.

**Offline stand-in.** Without a key (or with `EVAL_STUB=1`) every LLM call is answered by a deterministic stand-in. Those runs check the plumbing (CI does this) and are marked `stub=true`; `evalkit.report` excludes them. Never put a stub number in the report.

## Judge calibration

1. Run a dev session experiment, for example `e1_c2.yaml`.
2. `python -m evalkit.calibrate export --run results/runs/<run_id> --n 24`
3. Teachers or teammates label the transcripts in the teacher view (Label transcripts), on the same five yes/no criteria, without seeing the judge's verdicts. Ideally the school's Class 10 teacher labels them; the outreach letter already asks for this.
4. `python -m evalkit.calibrate score` → `results/labels/judge_agreement.md` with agreement and Cohen's kappa per criterion.

Rely on the judge for a criterion only when kappa ≥ 0.6 on 20+ labels; otherwise report that criterion from human labels.

## Review before held-out runs

- R1 checks the 28 new held-out questions and the 40 student cards against the written policy and the misconception catalogue.
- Freeze prompts, code and the playbook (commit) before any held-out run.
- If anything changes after viewing held-out results, those cases become dev cases; say so in the report.

## Limits to state in the report

- Simulated students are not real students. Their "learning" is the model's judgement that the card's condition was met.
- The quiz measures recognition of one misconception, not general understanding.
- The leak check catches stated answers; subtler give-aways are covered only by the judge's `guided_not_told` criterion.
- Results depend on the exact model IDs logged with each run.
- If possible, try the tutor with 3–5 real students, with consent, as a sanity check (outreach letter, part 1).
