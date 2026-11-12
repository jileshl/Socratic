"""Judge calibration: compare the LLM judge with human labels.

Uses the rubric our consulting teacher agreed to (questionnaire section 4.1):
conceptual accuracy, identified misconception and Socratic guidance, each 1-5.

Step 1 — export transcripts for people to label:
    python -m evalkit.calibrate export --real [--n 24]
  takes the judged sessions of every real-model run in experiment_log.csv
  (stub runs are skipped: their tutor and judge replies are placeholders), or
    python -m evalkit.calibrate export --run evalkit/results/runs/<run_id> [--run ...] [--n 24]
  for chosen runs.
  writes evalkit/results/labels/to_label.csv. The teacher view's "Label
  transcripts" page reads the same file. Labellers score each transcript on
  the three dimensions without seeing the judge's scores.

Step 2 — once 20+ transcripts are labelled:
    python -m evalkit.calibrate score
  compares the human scores with the judge scores stored in the runs and writes
  evalkit/results/labels/judge_agreement.md.

Agreement is reported per dimension as quadratic-weighted Cohen's kappa (a
4-vs-5 disagreement counts less than a 1-vs-5 one), exact agreement and
agreement within one point. Rule used in the report: rely on the judge for a
dimension only when weighted kappa >= 0.6 on 20+ labels; otherwise report that
dimension from the human labels.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from evalkit.metrics import compute_weighted_kappa
from evalkit.prompts import JUDGE_DIMENSIONS
from socratic_tutor import config

LABEL_DIR = config.EVAL_RESULTS_DIR / "labels"
TO_LABEL = LABEL_DIR / "to_label.csv"
HUMAN = LABEL_DIR / "human_labels.csv"
MIN_LABELS = 20
SCORES = (1, 2, 3, 4, 5)


def _transcript_text(turns: list) -> str:
    return "\n".join(f"{speaker}: {text}" for speaker, text in turns)


def real_runs() -> list[Path]:
    """Run folders logged with the real models (stub = False), oldest first."""
    log = config.EVAL_RESULTS_DIR / "experiment_log.csv"
    if not log.exists():
        return []
    with open(log, newline="", encoding="utf-8") as handle:
        ids = [row["run_id"] for row in csv.DictReader(handle) if row.get("stub") == "False"]
    return [config.EVAL_RESULTS_DIR / "runs" / run_id for run_id in ids if (config.EVAL_RESULTS_DIR / "runs" / run_id / "cases.jsonl").exists()]


def export(run_dirs: Path | list[Path], n: int, seed: int = 7) -> Path:
    run_dirs = [run_dirs] if isinstance(run_dirs, Path) else list(run_dirs)
    sessions: list[tuple[str, dict]] = []
    for run_dir in run_dirs:
        rows = [json.loads(line) for line in (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        sessions += [(run_dir.name, r) for r in rows if r.get("suite") == "sessions" and r.get("transcript") and r.get("judge", {}).get("scores")]
    if len(sessions) < n:
        print(f"Only {len(sessions)} judged sessions in {len(run_dirs)} run(s); exporting all of them.")
    random.Random(seed).shuffle(sessions)
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(TO_LABEL, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["item_id", "run_id", "case_id", "misconception", "transcript"])
        for run_name, row in sessions[:n]:
            writer.writerow([f"{run_name}::{row['case_id']}", run_name, row["case_id"], "; ".join(row.get("seeded", [])), _transcript_text(row["transcript"])])
    print(f"Wrote {min(n, len(sessions))} transcripts to {TO_LABEL}. Label them in the teacher view (Label transcripts) or in a copy of the CSV.")
    return TO_LABEL


def _judge_scores() -> dict[str, dict[str, int]]:
    scores: dict[str, dict[str, int]] = {}
    for run_dir in (config.EVAL_RESULTS_DIR / "runs").glob("*"):
        path = run_dir / "cases.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("judge", {}).get("scores"):
                scores[f"{run_dir.name}::{row['case_id']}"] = row["judge"]["scores"]
    return scores


def score() -> str:
    if not HUMAN.exists():
        raise SystemExit(f"No human labels yet ({HUMAN}). Label at least {MIN_LABELS} transcripts first.")
    with open(HUMAN, newline="", encoding="utf-8") as handle:
        labels = list(csv.DictReader(handle))
    judge = _judge_scores()
    lines = ["# Judge agreement with human labels", "", f"Judge model: `{config.JUDGE_MODEL}`. Rubric: the teacher's three dimensions, 1–5.", ""]
    lines += ["| Dimension | Labelled items | Exact agreement | Within 1 point | Weighted kappa | Use judge? |", "|---|---|---|---|---|---|"]
    for dimension in JUDGE_DIMENSIONS:
        human, model = [], []
        for row in labels:
            judged = judge.get(row["item_id"])
            try:
                h = int(row.get(dimension, ""))
            except ValueError:
                continue
            if judged and dimension in judged:
                human.append(h)
                model.append(int(judged[dimension]))
        n = len(human)
        if n == 0:
            lines.append(f"| {dimension} | 0 | — | — | — | no labels |")
            continue
        exact = sum(a == b for a, b in zip(human, model)) / n
        within = sum(abs(a - b) <= 1 for a, b in zip(human, model)) / n
        if len(set(human)) == 1 and len(set(model)) == 1:
            lines.append(f"| {dimension} | {n} | {exact:.0%} | {within:.0%} | undefined (no variation) | label more varied transcripts |")
            continue
        kappa = compute_weighted_kappa(human, model, SCORES)
        decision = "yes" if n >= MIN_LABELS and kappa >= 0.6 else ("not enough labels" if n < MIN_LABELS else "no: report from human labels")
        lines.append(f"| {dimension} | {n} | {exact:.0%} | {within:.0%} | {kappa:.2f} | {decision} |")
    labellers = sorted({row.get("labeller", "") for row in labels if row.get("labeller")})
    lines += ["", f"Labellers: {', '.join(labellers) if labellers else '(not recorded)'}."]
    text = "\n".join(lines) + "\n"
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    (LABEL_DIR / "judge_agreement.md").write_text(text, encoding="utf-8")
    print(text)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge calibration against human labels")
    sub = parser.add_subparsers(dest="command", required=True)
    p_export = sub.add_parser("export")
    which = p_export.add_mutually_exclusive_group(required=True)
    which.add_argument("--run", type=Path, action="append", help="a run folder; repeat for several")
    which.add_argument("--real", action="store_true", help="every real-model run in experiment_log.csv")
    p_export.add_argument("--n", type=int, default=24)
    sub.add_parser("score")
    args = parser.parse_args()
    if args.command == "export":
        export(real_runs() if args.real else args.run, args.n)
    else:
        score()


if __name__ == "__main__":
    main()
