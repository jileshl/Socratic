# Evaluation tables

Generated from `evalkit/results/experiment_log.csv`.

_14 stub (plumbing-only) run(s) excluded._

## E1 · Does the agent justify its cost? (C0 fixed workflow, C1 one agent, C2 team)

| Condition | Split | Runs | Task success | Answer leaks | Policy violations | Misconception found | Mean learning gain | Judge pass (all ≥ 4) | Judge: accuracy (1–5) | Judge: misconception (1–5) | Judge: Socratic (1–5) | Attack success | False blocks | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C0 fixed workflow | dev | 2 | 25% (0%–50%) | 0 (0–0) | 0 (0–0) | 50% (0%–100%) | 0 | 0% | 5 | 3.5 | 2.5 | 1% (0%–3%) | 50% (0%–100%) | 0.00101 (1e-05–0.002) | 1.81 (1.11–2.52) | 18.1 (2.28–33.9) | 11 (0–22) | 0 (0–0) |
| C1 one agent | dev | 1 | 50% | 2 | 2 | 50% | 0.5 | 50% | 3.5 | 4 | 3 | 0% | 0% | 0.00259 | 6.6 | 38.9 | 0 | 0 |
| C2 team | dev | 4 | 89% (55%–100%) | 2 (0–8) | 13.5 (0–54) | 100% (100%–100%) | 0.688 (0.5–1) | 21% (0%–50%) | 4.88 (4.5–5) | 3.67 (3–5) | 3.39 (3–4.5) | 0% (0%–0%) | 1% (0%–4%) | 0.00184 (0.00134–0.00237) | 4.72 (2.72–6.87) | 39.7 (27.3–48.1) | 0 (0–0) | 0 (0–0) |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: a56b6e4, fd2a778-dirty, nogit.

## E2 · Do the defences work? (attack success and false blocks, defences off vs on)

| Condition | Split | Runs | Attack success | False blocks | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|
| Defences off | dev | 2 | 6% (0%–12%) | 0% (0%–0%) | 9.5e-05 (0–0.00019) | 0.2 (0.01–0.39) | 2.83 (0.91–4.74) | 0 (0–0) | 0 (0–0) |
| Defences on | dev | 5 | 1% (0%–3%) | 56% (0%–100%) | 6.6e-05 (0–0.00021) | 0.258 (0.01–1.25) | 4.45 (1.63–8.35) | 0 (0–0) | 0 (0–0) |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-2.5-flash; openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: 0cb2cc6-dirty, fd2a778-dirty, nogit.

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
| Direct answers | dev | 1 | 0% | 7 | 7 | 100% | 0.5 | 0% | 5 | 4.5 | 2 | 0.00484 | 28.4 | 32.1 | 0 | 0 |
| Memory off | dev | 1 | 100% | 0 | 0 | 100% | 0.5 | 0% | 5 | 3 | 2 | 0.00579 | 32 | 41.1 | 0 | 0 |
| Memory on | dev | 1 | 100% | 0 | 0 | 100% | 0.5 | 0% | 5 | 4.5 | 2.5 | 0.00781 | 49.4 | 54.3 | 0 | 0 |
| Socratic hints | dev | 1 | 100% | 0 | 0 | 100% | 0.5 | 50% | 5 | 3.5 | 3 | 0.00496 | 31 | 36 | 0 | 0 |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: fd2a778-dirty.

## GOLD

| Condition | Split | Runs | Task success | Recall@5 | Grader agreement | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|---|
| Gold questions | dev | 1 | 96% | 1 | 0.979 | 0.0001 | 3.19 | 12.5 | 0 | 0 |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: nogit.

## Retrieval · Recall@5 before and after one change

| Condition | Split | Runs | Recall@5 | MRR | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|
| Retrieval (current index) | dev | 1 | 0.95 | 0.851 | 0 | 0.161 | 0.489 | 0 | 0 |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: nogit.

## Retrieval Modality Comparison (30 dev queries, Top-5)

| Modality | Recall@5 | Perfect Recall | MRR | Latency (ms, median) |
| :--- | :---: | :---: | :---: | :---: |
| BM25 (`rank_bm25`) | **0.9000** | 26/30 | **0.7800** | 0.2 ms |
| Dense embeddings alone | **0.9000** | 26/30 | **0.7167** | 111.6 ms |
| Hybrid, no query rewrite | **0.9167** | 27/30 | **0.8344** | 111.6 ms |
| Hybrid + query rewrite | **0.9500** | 28/30 | **0.8511** | 113.2 ms |

