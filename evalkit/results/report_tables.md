# Evaluation tables

Generated from `evalkit/results/experiment_log.csv`.

_13 stub (plumbing-only) run(s) excluded._

## E1 · Does the agent justify its cost? (C0 fixed workflow, C1 one agent, C2 team)

| Condition | Split | Runs | Task success | Answer leaks | Policy violations | Misconception found | Mean learning gain | Judge pass (all ≥ 4) | Judge: accuracy (1–5) | Judge: misconception (1–5) | Judge: Socratic (1–5) | Attack success | False blocks | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C0 fixed workflow | dev | 1 | 50% | 0 | 0 | 100% | 0 | 0% | 5 | 3.5 | 2.5 | 0% | 0% | 0.002 | 2.52 | 33.9 | 0 | 0 |
| C1 one agent | dev | 1 | 50% | 2 | 2 | 50% | 0.5 | 50% | 3.5 | 4 | 3 | 0% | 0% | 0.00259 | 6.6 | 38.9 | 0 | 0 |
| C2 team | dev | 1 | 100% | 0 | 0 | 100% | 0.5 | 50% | 5 | 3 | 4.5 | 0% | 0% | 0.00134 | 4.62 | 27.3 | 0 | 0 |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: fd2a778-dirty.

## E2 · Do the defences work? (attack success and false blocks, defences off vs on)

| Condition | Split | Runs | Attack success | False blocks | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|
| Defences off | dev | 1 | 0% | 0% | 0.00019 | 0.01 | 4.74 | 0 | 0 |
| Defences on | dev | 1 | 0% | 0% | 0.00021 | 0.01 | 6.39 | 0 | 0 |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: fd2a778-dirty.

## E3 · Did the lessons help? (held-out, before vs after the frozen playbook)

| Condition | Split | Runs | Task success | Answer leaks | Policy violations | Misconception found | Mean learning gain | Judge pass (all ≥ 4) | Judge: accuracy (1–5) | Judge: misconception (1–5) | Judge: Socratic (1–5) | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Frozen playbook | dev | 1 | 100% | 0 | 0 | 100% | 0.5 | 50% | 5 | 4 | 4.5 | 0.00474 | 25.2 | 33.1 | 0 | 0 |
| Frozen playbook | held_out | 1 | 100% | 0 | 0 | 100% | 0.5 | 50% | 5 | 3.5 | 4.5 | 0.00382 | 16.1 | 20.5 | 0 | 0 |
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

## Retrieval · Recall@5 before and after one change

| Condition | Split | Runs | Recall@5 | MRR | Cost / case (USD) | p50 latency (s) | p95 latency (s) | Errors | Timeouts |
|---|---|---|---|---|---|---|---|---|---|
| Retrieval (current index) | dev | 1 | 0.95 | 0.851 | 0 | 0.06 | 0.065 | 0 | 0 |
| Retrieval (current index) | held_out | 1 | 1 | 0.861 | 0 | 0.06 | 0.064 | 0 | 0 |

Models (specialist, supervisor, judge): openai/gpt-4o-mini, openai/gpt-4.1-mini, google/gemini-3.1-flash-lite. Commits: 049113d-dirty.

## Retrieval Modality Comparison (30 dev queries, Top-5)

| Modality | Recall@5 | Perfect Recall | MRR | Latency (ms, median) |
| :--- | :---: | :---: | :---: | :---: |
| BM25 (`rank_bm25`) | **0.9000** | 26/30 | **0.7800** | 0.1 ms |
| Dense embeddings alone | **0.9000** | 26/30 | **0.7167** | 60.0 ms |
| Hybrid, no query rewrite | **0.9167** | 27/30 | **0.8344** | 60.1 ms |
| Hybrid + query rewrite | **0.9500** | 28/30 | **0.8511** | 61.4 ms |

