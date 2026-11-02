"""Judge calibration: compare the LLM judge with human labels (Cohen's kappa).

Step 1 — export transcripts for people to label:
    python -m evalkit.calibrate export --run results/runs/<run_id> [--n 24]
  writes results/labels/to_label.csv (and the teacher view's "Label transcripts"
  page reads the same file). People label each transcript on the same five
  yes/no criteria as the judge, without seeing the judge's verdicts.

Step 2 — compute agreement once at least 20 transcripts are labelled:
    python -m evalkit.calibrate score
  reads results/labels/human_labels.csv, re-runs nothing, and compares with the
  judge verdicts stored in the run. Writes results/labels/judge_agreement.md.

Rule of thumb used in the report: rely on the judge for a criterion only when
kappa >= 0.6 on 20+ labels; otherwise report that criterion from human labels or
not at all.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from evalkit.llm_client import JUDGE_CRITERIA
from evalkit.metrics import compute_cohens_kappa
from socratic_tutor import config

LABEL_DIR = config.RESULTS_DIR / "labels"
TO_LABEL = LABEL_DIR / "to_label.csv"
HUMAN = LABEL_DIR / "human_labels.csv"
MIN_LABELS = 20


def _transcript_text(turns: list) -> str:
    return "\n".join(f"{speaker}: {text}" for speaker, text in turns)


def export(run_dir: Path, n: int, seed: int = 7) -> Path:
    rows = [json.loads(line) for line in (run_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    sessions = [r for r in rows if r.get("suite") == "sessions" and r.get("transcript") and r.get("judge", {}).get("verdicts")]
    if len(sessions) < n:
        print(f"Only {len(sessions)} judged sessions in this run; exporting all of them.")
    random.Random(seed).shuffle(sessions)
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(TO_LABEL, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["item_id", "run_id", "case_id", "misconception", "transcript"])
        for row in sessions[:n]:
            writer.writerow([f"{run_dir.name}::{row['case_id']}", run_dir.name, row["case_id"], "; ".join(row.get("seeded", [])), _transcript_text(row["transcript"])])
    print(f"Wrote {min(n, len(sessions))} transcripts to {TO_LABEL}. Label them in the teacher view (Label transcripts) or in the CSV.")
    return TO_LABEL


def _judge_verdicts() -> dict[str, dict[str, str]]:
    verdicts: dict[str, dict[str, str]] = {}
    for run_dir in (config.RESULTS_DIR / "runs").glob("*"):
        path = run_dir / "cases.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            v = row.get("judge", {}).get("verdicts")
            if v:
                verdicts[f"{run_dir.name}::{row['case_id']}"] = v
    return verdicts


def score() -> str:
    if not HUMAN.exists():
        raise SystemExit(f"No human labels yet ({HUMAN}). Label at least {MIN_LABELS} transcripts first.")
    with open(HUMAN, newline="", encoding="utf-8") as handle:
        labels = list(csv.DictReader(handle))
    judge = _judge_verdicts()
    lines = ["# Judge agreement with human labels", "", f"Judge model: `{config.JUDGE_MODEL}`. Labels file: `results/labels/human_labels.csv`.", ""]
    lines += ["| Criterion | Labelled items | Raw agreement | Cohen's kappa | Use judge? |", "|---|---|---|---|---|"]
    for criterion in JUDGE_CRITERIA:
        human, model = [], []
        for row in labels:
            verdicts = judge.get(row["item_id"])
            if not verdicts or row.get(criterion, "") not in {"yes", "no"}:
                continue
            human.append(1 if row[criterion] == "yes" else 0)
            model.append(1 if verdicts.get(criterion) == "yes" else 0)
        n = len(human)
        if n == 0:
            lines.append(f"| {criterion} | 0 | — | — | no labels |")
            continue
        agreement = sum(a == b for a, b in zip(human, model)) / n
        if len(set(human)) == 1 and len(set(model)) == 1:
            # every label identical on both sides: kappa is undefined, not perfect
            lines.append(f"| {criterion} | {n} | {agreement:.0%} | undefined (no variation) | label more varied transcripts |")
            continue
        kappa = compute_cohens_kappa(human, model)
        decision = "yes" if n >= MIN_LABELS and kappa >= 0.6 else ("not enough labels" if n < MIN_LABELS else "no: report from human labels")
        lines.append(f"| {criterion} | {n} | {agreement:.0%} | {kappa:.2f} | {decision} |")
    labellers = sorted({row.get("labeller", "") for row in labels if row.get("labeller")})
    lines += ["", f"Labellers: {', '.join(labellers) if labellers else '(not recorded)'}."]
    text = "\n".join(lines) + "\n"
    (LABEL_DIR / "judge_agreement.md").write_text(text, encoding="utf-8")
    print(text)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge calibration against human labels")
    sub = parser.add_subparsers(dest="command", required=True)
    p_export = sub.add_parser("export")
    p_export.add_argument("--run", type=Path, required=True)
    p_export.add_argument("--n", type=int, default=24)
    sub.add_parser("score")
    args = parser.parse_args()
    if args.command == "export":
        export(args.run, args.n)
    else:
        score()


if __name__ == "__main__":
    main()
