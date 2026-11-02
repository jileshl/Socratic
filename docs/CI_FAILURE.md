# One failed CI run, explained (L16 evidence)

The guide asks for "one failed CI run with an explanation". Fill this in from a real run. Do not describe a failure that did not happen.

## How to produce it honestly

Pick one of these, push it on a branch, and let CI fail:

1. **Retrieval regression (the eval gate).** Make a plausible change that hurts retrieval, for example chunk by page instead of by section, or drop section titles from the BM25 text in `socratic_tutor/retrieval.py`. The `eval-gate` job fails when Recall@5 falls below 0.85.
2. **A real bug caught by a test**, if one happens naturally during the last week (a better story than a staged one).

Then fix it, push again, and record both runs below.

## Record

- Failed run: [link to the GitHub Actions run — TO FILL]
- Commit: [sha — TO FILL]
- Job and step that failed: [e.g. eval-gate → "Eval gate (Recall@5 floor)" — TO FILL]
- Output: [paste the gate's two lines: measured Recall@5 and the floor — TO FILL]
- Why it failed: [one or two sentences — TO FILL]
- Fix: [commit and one sentence — TO FILL]
- Passing run after the fix: [link — TO FILL]
