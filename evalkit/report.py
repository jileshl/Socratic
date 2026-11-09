"""Build the evaluation-report tables from results/experiment_log.csv.

    python -m evalkit.report                 # writes evalkit/results/report_tables.md
    python -m evalkit.report --include-stub  # plumbing check only, never for the report

Rows are grouped by experiment, condition and split. With several repeats, each
cell shows the mean and, in brackets, the min–max spread across repeats (the
guide asks for the spread of the final held-out comparison over 3 repeats).
Stub runs are excluded by default. Nothing here is estimated: an empty cell
means that run did not measure it.
"""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path

from socratic_tutor import config

EXPERIMENT_TITLES = {
    "E1": "E1 · Does the agent justify its cost? (C0 fixed workflow, C1 one agent, C2 team)",
    "E2": "E2 · Do the defences work? (attack success and false blocks, defences off vs on)",
    "E3": "E3 · Did the lessons help? (held-out, before vs after the frozen playbook)",
    "E4": "E4 · Signature ablation (learner memory off/on; direct answers vs Socratic hints)",
    "RET": "Retrieval · Recall@5 before and after one change",
}

COLUMNS = [
    ("Task success", lambda r: _ratio(r, "task_success", "task_total")),
    ("Answer leaks", lambda r: _num(r, "answer_leaks")),
    ("Policy violations", lambda r: _num(r, "policy_violations")),
    ("Misconception found", lambda r: _ratio(r, "misconception_hits", "task_total")),
    ("Mean learning gain", lambda r: _num(r, "mean_learning_gain")),
    ("Judge pass (all ≥ 4)", lambda r: _ratio(r, "judge_pass", "task_total")),
    ("Judge: accuracy (1–5)", lambda r: _num(r, "judge_accuracy")),
    ("Judge: misconception (1–5)", lambda r: _num(r, "judge_misconception")),
    ("Judge: Socratic (1–5)", lambda r: _num(r, "judge_socratic")),
    ("Attack success", lambda r: _ratio(r, "attack_success", "attacks_total")),
    ("False blocks", lambda r: _ratio(r, "false_blocks", "clean_total")),
    ("Recall@5", lambda r: _num(r, "recall_at_5")),
    ("MRR", lambda r: _num(r, "mrr")),
    ("Grader agreement", lambda r: _num(r, "grader_agreement")),
    ("Cost / case (USD)", lambda r: _num(r, "cost_per_case_usd")),
    ("p50 latency (s)", lambda r: _num(r, "latency_p50_s")),
    ("p95 latency (s)", lambda r: _num(r, "latency_p95_s")),
    ("Errors", lambda r: _num(r, "errors")),
    ("Timeouts", lambda r: _num(r, "timeouts")),
]


def _num(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "")
    try:
        return float(value) if value not in ("", None) else None
    except ValueError:
        return None


def _ratio(row: dict[str, str], top: str, bottom: str) -> float | None:
    a, b = _num(row, top), _num(row, bottom)
    return a / b if a is not None and b else None


def _fmt(values: list[float | None], as_rate: bool) -> str:
    present = [v for v in values if v is not None]
    if not present:
        return "—"
    show = (lambda v: f"{v:.0%}") if as_rate else (lambda v: f"{v:.3g}")
    mean = statistics.mean(present)
    if len(present) == 1:
        return show(mean)
    return f"{show(mean)} ({show(min(present))}–{show(max(present))})"


def build(log_path: Path, include_stub: bool) -> str:
    if not log_path.exists():
        return "No runs logged yet. Run `python -m evalkit.runner <experiment>` first.\n"
    with open(log_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    excluded = [r for r in rows if r.get("stub", "").lower() == "true"]
    if not include_stub:
        rows = [r for r in rows if r.get("stub", "").lower() != "true"]

    groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[(row.get("experiment") or "?", row.get("condition") or row["config"], row["split"])].append(row)

    lines = ["# Evaluation tables", "", f"Generated from `{log_path.relative_to(config.BASE_DIR) if log_path.is_relative_to(config.BASE_DIR) else log_path}`.", ""]
    if excluded and not include_stub:
        lines += [f"_{len(excluded)} stub (plumbing-only) run(s) excluded._", ""]
    for experiment in sorted({key[0] for key in groups}):
        keys = sorted(k for k in groups if k[0] == experiment)
        used = [(name, fn) for name, fn in COLUMNS if any(fn(r) is not None for k in keys for r in groups[k])]
        lines += [f"## {EXPERIMENT_TITLES.get(experiment, experiment)}", ""]
        header = ["Condition", "Split", "Runs"] + [name for name, _ in used]
        lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        for key in keys:
            runs = groups[key]
            cells = [key[1], key[2], str(len(runs))]
            for name, fn in used:
                as_rate = name in {"Task success", "Misconception found", "Judge pass (all ≥ 4)", "Attack success", "False blocks"}
                cells.append(_fmt([fn(r) for r in runs], as_rate))
            lines.append("| " + " | ".join(cells) + " |")
        models = sorted({(r["specialist_model"], r["supervisor_model"], r["judge_model"]) for k in keys for r in groups[k]})
        shas = sorted({r["git_sha"] for k in keys for r in groups[k]})
        lines += ["", f"Models (specialist, supervisor, judge): {'; '.join(', '.join(m) for m in models)}. Commits: {', '.join(shas)}.", ""]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build report tables from the experiment log")
    parser.add_argument("--log", type=Path, default=config.EVAL_RESULTS_DIR / "experiment_log.csv")
    parser.add_argument("--out", type=Path, default=config.EVAL_RESULTS_DIR / "report_tables.md")
    parser.add_argument("--include-stub", action="store_true")
    args = parser.parse_args()
    text = build(args.log, args.include_stub)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
