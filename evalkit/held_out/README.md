# Held-out cases: the agent never reads this folder

The capstone guide (p.5): "Store held-out cases in a folder the agent cannot read."

- `gold_questions.jsonl` (40), `simulated_students.jsonl` (20), `retrieval_queries.jsonl` (12): the held-out rows,
  moved here from `data/` on 13 Nov 2026. The development rows stay in `data/`.
- The app's Docker image does not contain this folder (`.dockerignore`); only the evaluation service mounts it,
  read-only (`docker/docker-compose.yml`, profile `eval`).
- `tests/test_held_out.py` checks that no code under `socratic_tutor/` refers to it.
- Run the held-out set once, after the code and the playbook are frozen, by someone who did not tune the agent.
  If anything changes after the results are seen, these cases count as development cases from then on, and the
  report must say so (guide p.6).
