# Data card

All project data is synthetic or written for the project. No real student data is stored in the repository.

| Dataset | Path | Size | Written by | Status |
|---|---|---|---|---|
| Concept graph | `data/concept_graph.json` | 30 concepts with prerequisites | R1 | draft; teacher review pending |
| Misconception catalogue | `data/misconceptions.json` | 36 (12 per chapter), each with a probe and a hint | R1, with teacher input | draft; teacher review pending |
| Retrieval queries | `data/retrieval_queries.jsonl` | 36 (24 dev, 12 held-out), labelled with NCERT section IDs | R2 | in use (BM25 baseline) |
| Gold questions, dev | `eval/dev/gold_questions.jsonl` (= `data/gold_questions.jsonl` + eval fields) | 24 | R1; enriched by R5 | in use |
| Gold questions, held-out | `eval_heldout/gold_questions.jsonl` | 40: 12 from R1's original held-out + 28 new | R1 (12), R5 (28) | R1 review pending |
| Simulated students | `eval/dev/…`, `eval_heldout/simulated_students.jsonl` | 20 + 20 | R5 | R1 review pending |
| Practice problems | `eval/dev/…`, `eval_heldout/practice_problems.jsonl` | 20 + 20 | R5 | in use |
| Quiz bank | `eval/quiz_bank.jsonl` | 40 multiple-choice items (2 forms × 20 misconceptions) | R5 | in use |
| Red-team attacks | `redteam/attacks.jsonl` | 34 in 11 categories | R5 (not the defence builder) | in use |
| Clean cases | `redteam/clean_cases.jsonl` | 24 | R5 | in use |
| Red-team fixtures | `redteam/fixtures/redteam_fixtures.json` | 4 poisoned passages, 1 planted learner record, 1 canary | R5 | used only during red-team cases |

## Fields added to the gold questions for evaluation

- `chapter`, `gold_section_ids`: parsed from the citations, used for Recall@5.
- `answer_specs`: the reference-solver call that computes each numeric answer.
- `sample_answers`: one correct and one incorrect student answer, used to measure grader agreement.

## Answer keys

Numeric keys are computed by `evalkit/reference_solver.py` using exact fractions. `tests/test_eval_datasets.py` checks every written answer against the code and cross-checks the solver against the tutor's own calculator.

## NCERT material

The NCERT PDFs are used inside the project but not redistributed. They are git-ignored and fetched by `scripts/fetch_ncert.py`. The PDFs that were committed earlier should also be removed from git history before the repository is shared (`git filter-repo --path-glob 'data/*.pdf' --invert-paths`, coordinated with the whole team because it rewrites history).

## Human labels

Judge-calibration labels (`results/labels/human_labels.csv`) are made by people in the teacher view. None are supplied in the repository.
