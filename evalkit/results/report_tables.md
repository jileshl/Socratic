# Evaluation tables

Generated from `evalkit/results/experiment_log.csv`.

_14 stub (plumbing-only) run(s) excluded._

## E1 · Does the agent justify its cost? (C0 fixed workflow, C1 one agent, C2 team)

| Condition | Split | Runs | Task success | Answer leaks | Policy violations | Misconception found | Mean learning gain | Judge pass (all ≥ 4) | Judge: accuracy (1–5) | Judge: misconception (1–5) | Judge: Socratic (1–5) | Attack success | False blocks | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C0 fixed workflow | dev | 3 | 39% (0%–67%) | 0.333 (0–1) | 0.333 (0–1) | 67% (0%–100%) | 0.334 (0–0.667) | 17% (0%–33%) | 4.83 (4.67–5) | 3.92 (3.5–4.33) | 3.25 (2.5–4) | 1% (0%–3%) | 33% (0%–100%) | 0.00108 (1e-05–0.002) | 2.09 (1.11–2.64) | 22.7 (2.28–33.9) | 7.33 (0–22) | 0 (0–0) |
| C1 one agent | dev | 2 | 25% (0%–50%) | 3 (2–4) | 5 (2–8) | 75% (50%–100%) | 0.584 (0.5–0.667) | 42% (33%–50%) | 4.25 (3.5–5) | 4.5 (4–5) | 2.83 (2.67–3) | 0% (0%–0%) | 0% (0%–0%) | 0.00216 (0.00174–0.00259) | 7.8 (6.6–9) | 44.4 (38.9–49.9) | 0 (0–0) | 0 (0–0) |
| C2 team | dev | 5 | 91% (55%–100%) | 1.6 (0–8) | 10.8 (0–54) | 100% (100%–100%) | 0.75 (0.5–1) | 37% (0%–100%) | 4.9 (4.5–5) | 3.94 (3–5) | 3.71 (3–5) | 0% (0%–0%) | 1% (0%–4%) | 0.00184 (0.00134–0.00237) | 6 (2.72–11.1) | 39.1 (27.3–48.1) | 0 (0–0) | 0 (0–0) |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, code (no model); tutor ReAct over MCP, google/gemini-3.1-flash-lite; openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: 812de55, 812de55-dirty, a56b6e4, fd2a778-dirty, nogit.

## E2 · Do the defences work? (attack success and false blocks, defences off vs on)

| Condition | Split | Runs | Attack success | False blocks | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|
| Defences off | dev | 3 | 4% (0%–12%) | 0% (0%–0%) | 0.000233 (0–0.00051) | 0.14 (0.01–0.39) | 4.95 (0.91–9.2) | 0 (0–0) | 0 (0–0) |
| Defences on | dev | 6 | 0% (0%–3%) | 47% (0%–100%) | 0.000125 (0–0.00042) | 0.217 (0.01–1.25) | 5.56 (1.63–11.1) | 0 (0–0) | 0 (0–0) |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, code (no model); tutor ReAct over MCP, google/gemini-3.1-flash-lite; openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-2.5-flash; openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: 0cb2cc6-dirty, 812de55-dirty, fd2a778-dirty, nogit.

## E3 · Did the lessons help? (held-out, before vs after the frozen playbook)

| Condition | Split | Runs | Task success | Answer leaks | Policy violations | Misconception found | Mean learning gain | Judge pass (all ≥ 4) | Judge: accuracy (1–5) | Judge: misconception (1–5) | Judge: Socratic (1–5) | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Frozen playbook | dev | 1 | 100% | 0 | 0 | 100% | 0.5 | 50% | 5 | 4 | 4.5 | 0.00474 | 25.2 | 33.1 | 0 | 0 |
| Frozen playbook | held_out | 1 | 0% | 0 | 0 | 100% | 0.5 | 50% | 5 | 3.5 | 4.5 | 0.00382 | 16.1 | 20.5 | 0 | 0 |
| No playbook | dev | 1 | 100% | 0 | 0 | 100% | 0.5 | 50% | 5 | 3.5 | 3 | 0.00589 | 31.3 | 33.3 | 0 | 0 |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: fd2a778-dirty.

## E4 · Signature ablation (learner memory off/on; direct answers vs Socratic hints)

| Condition | Split | Runs | Task success | Answer leaks | Policy violations | Misconception found | Mean learning gain | Judge pass (all ≥ 4) | Judge: accuracy (1–5) | Judge: misconception (1–5) | Judge: Socratic (1–5) | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Direct answers | dev | 2 | 0% (0%–0%) | 7.5 (7–8) | 7.5 (7–8) | 100% (100%–100%) | 0.5 (0.5–0.5) | 0% (0%–0%) | 5 (5–5) | 4 (3.5–4.5) | 2.25 (2–2.5) | 0.00499 (0.00484–0.00514) | 28.5 (28.4–28.6) | 31 (29.9–32.1) | 0 (0–0) | 0 (0–0) |
| Memory off | dev | 1 | 100% | 0 | 0 | 100% | 0.5 | 0% | 5 | 3 | 2 | 0.00579 | 32 | 41.1 | 0 | 0 |
| Memory on | dev | 1 | 100% | 0 | 0 | 100% | 0.5 | 0% | 5 | 4.5 | 2.5 | 0.00781 | 49.4 | 54.3 | 0 | 0 |
| Socratic hints | dev | 2 | 75% (50%–100%) | 0.5 (0–1) | 0.5 (0–1) | 100% (100%–100%) | 0.5 (0.5–0.5) | 50% (50%–50%) | 5 (5–5) | 3.75 (3.5–4) | 3.5 (3–4) | 0.00582 (0.00496–0.00668) | 35.5 (31–39.9) | 38.6 (36–41.1) | 0 (0–0) | 0 (0–0) |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, code (no model); tutor ReAct over MCP, google/gemini-3.1-flash-lite; openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: 812de55-dirty, fd2a778-dirty.

## GOLD

| Condition | Split | Runs | Task success | Recall@5 | Grader agreement | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|---|
| Gold questions | dev | 2 | 98% (96%–100%) | 1 (1–1) | 0.99 (0.979–1) | 9.5e-05 (9e-05–0.0001) | 3.17 (3.15–3.19) | 8.29 (4.09–12.5) | 0 (0–0) | 0 (0–0) |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, code (no model); tutor ReAct over MCP, google/gemini-3.1-flash-lite; openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: 812de55-dirty, nogit.

## Retrieval · Recall@5 before and after one change

| Condition | Split | Runs | Recall@5 | MRR | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|
| Retrieval (current index) | dev | 1 | 0.95 | 0.851 | 0 | 0.161 | 0.489 | 0 | 0 |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: nogit.

## Retrieval Modality Comparison (30 dev queries, Top-5)

| Modality | Recall@5 | Perfect Recall | MRR | Latency (ms, median) |
| :--- | :---: | :---: | :---: | :---: |
| BM25 (`rank_bm25`) | **0.9000** | 26/30 | **0.7800** | 0.2 ms |
| Dense embeddings alone | **0.9000** | 26/30 | **0.7167** | 114.3 ms |
| Hybrid, no query rewrite | **0.9167** | 27/30 | **0.8344** | 109.5 ms |
| Hybrid + query rewrite | **0.9500** | 28/30 | **0.8511** | 115.9 ms |

