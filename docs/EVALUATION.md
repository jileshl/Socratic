# Evaluation (R5: evaluation and red team)

Follows the capstone's evaluation protocol: a gold set split into dev and held-out, code checks first, an LLM judge only where code cannot decide (calibrated against people), every experiment as a named configuration, repeats on the final held-out comparison, and honest reporting of failures, costs and latency.

## Where things are

| What | Where |
|---|---|
| Datasets (all in the team's `data/` folder, `split` field = `dev` / `held_out`) | `data/gold_questions.jsonl` (64: 24 dev, 40 held-out), `data/gold_question_checks.jsonl`, `data/simulated_students.jsonl` (40: 20 / 20), `data/practice_problems.jsonl`, `data/quiz_bank.jsonl`, `data/retrieval_queries.jsonl` (R2), `data/redteam/` |
| Evaluation code | `evalkit/` |
| Experiment definitions (E1–E4, retrieval, gold, smoke) | `evalkit/experiments.py` (one file) |
| Evaluation prompts, versioned | `evalkit/prompts.py` |
| Model IDs, budgets, CI threshold | `socratic_tutor/config.py` (the team's single config) |
| Results (git-ignored) | `evalkit/results/` |

**No duplicates.** New gold questions and student cards are appended to the team's files; rows written by others are not changed (a test checks this). `gold_question_checks.jsonl` holds only what the questions do not already say: the code answer key and one labelled wrong answer per question. Section IDs come from each question's citations, and a student's practice problem, quizzes and "change of mind" condition come from their seeded misconception, all derived at run time in `evalkit/datasets.py`.

**Held-out answers stay away from the agent.** A test fails if any file under `socratic_tutor/` opens the evaluation datasets. The Reflexion loop uses dev students only.

## What is measured, and how

| Question | Decided by |
|---|---|
| Does the tutor find the student's misconception? | code: diagnosed ID = a seeded ID |
| Does it leak answers in practice mode? | code: the final number (sign and givens ignored) or every key phrase of a conceptual answer appears in a reply |
| Does the student's quiz score improve? | code: multiple choice, two parallel forms per misconception, options shuffled per student |
| Are citations real and on topic? | code: section exists and belongs to the chapter being taught |
| Is the teaching good? | LLM judge from a different model family, scored on **the teacher's rubric** (consultation questionnaire 4.1): conceptual accuracy, identified misconception, Socratic guidance, each 1–5 |
| Does retrieval find the right section? | code: Recall@5, MRR |
| Does the grader agree with the answer key? | code: grader verdict on the gold answer and on one labelled wrong answer |
| Do attacks succeed? Is legitimate work blocked? | code: canary text, revealed answer, planted marker, database state, missing teacher alert; refusal on clean cases |

A session is a **task success** when the post-quiz is fully correct and no answer leaked. Simulated students include the teacher's three problem-solving archetypes (questionnaire 6.3: formula matcher, rote memoriser, intuitive) in the teacher's 2 : 1 : 4 ratio.

## Running

```bash
python -m evalkit.runner --list
python -m evalkit.runner e1_c2 --split dev
python -m evalkit.runner e1_c2 --split held_out --repeats 3
python -m evalkit.report              # tables for REPORT.md -> evalkit/results/report_tables.md
```

`make eval E=e1_c2 SPLIT=held_out REPEATS=3` does the same. With Docker: `docker compose -f docker/docker-compose.yml --profile eval run --rm eval e1_c2 --split dev`.

| Experiment | Names |
|---|---|
| E1 does the agent justify its cost? | `e1_c0` (fixed workflow), `e1_c1` (one agent, all tools), `e1_c2` (team) |
| E2 do the defences work? | `e2_off`, `e2_on` (34 attacks, 24 clean cases) |
| E3 did the lessons help? | `e3_no_playbook`, `e3_playbook` (held-out, playbook frozen first) |
| E4 signature ablation | `e4_memory_off` / `e4_memory_on` (two sessions per student), `e4_direct` / `e4_socratic` |

The E2–E4 switches are applied from the evaluation side (`evalkit/ablations.py`) by temporarily replacing a function the agents already call. No agent code changes and the deployed app is never affected.

Each run writes every case (with transcripts) and one row in `evalkit/results/experiment_log.csv`: git commit, prompt version, exact model IDs, switches, task success, leaks, policy violations, misconception hits, learning gain, judge scores, attack success, false blocks, Recall@5, MRR, grader agreement, cost per case, p50/p95 latency, errors and timeouts. Failed and timed-out cases are kept. Costs come from OpenRouter's own accounting; a cost that is not reported stays blank and is never estimated.

**Offline stand-in.** Without a key (or with `EVAL_STUB=1`) every LLM call is answered by a deterministic stand-in. CI uses this to test the plumbing. Those rows are marked `stub` and `evalkit.report` leaves them out.

## Judge calibration

1. Run a dev session experiment, e.g. `e1_c2`.
2. `python -m evalkit.calibrate export --run evalkit/results/runs/<run_id> --n 24`
3. The teacher (or teammates) score the transcripts 1–5 on the three dimensions in the teacher view, under "Label transcripts", without seeing the judge's scores.
4. `python -m evalkit.calibrate score` writes agreement per dimension: quadratic-weighted Cohen's kappa, exact agreement, and agreement within 1 point.

Rely on the judge for a dimension only when weighted kappa ≥ 0.6 on 20+ labels; otherwise report that dimension from the human labels.

## Before held-out runs

- R1 checks the 28 new held-out questions and the 36 new student cards against the policy and misconception catalogue.
- Freeze prompts, code and the playbook (commit) first. If anything changes after seeing held-out results, those cases become dev cases; say so in the report.

## Limits to state in the report

Simulated students are not real students. The quiz measures one misconception, not general understanding. Code catches stated answers; subtler give-aways rely on the judge. Results depend on the model IDs logged with each run.
