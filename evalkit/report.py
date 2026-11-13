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
import json
import os
import statistics
import time
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


def benchmark_retrieval(split: str = "dev", top_k: int = 5) -> str:
    """Benchmark retrieval modalities (BM25, Dense, Hybrid-no-rewrite, Hybrid) and return Markdown table."""
    from evalkit.metrics import compute_recall_at_k
    from socratic_tutor.retrieval import HybridRetriever

    from evalkit import datasets

    try:
        records = datasets.split_rows("retrieval_queries.jsonl")
    except FileNotFoundError:
        return ""
    records = [r for r in records if split == "all" or r.get("split") == split]
    if not records:
        return ""

    try:
        retriever = HybridRetriever()
        if not retriever.index.chunks:
            return ""
    except Exception:
        return ""

    modes = [
        ("BM25 (`rank_bm25`)", lambda q: retriever.search_bm25(q, top_k=top_k)),
        ("Dense embeddings alone", lambda q: retriever.search_dense(q, top_k=top_k)),
        ("Hybrid, no query rewrite", lambda q: retriever.search_hybrid(q, top_k=top_k, rewrite=False)),
        ("Hybrid + query rewrite", lambda q: retriever.search_hybrid(q, top_k=top_k, rewrite=True)),
    ]

    lines = [
        f"## Retrieval Modality Comparison ({len(records)} {split} queries, Top-{top_k})",
        "",
        f"| Modality | Recall@{top_k} | Perfect Recall | MRR | Latency (ms, median) |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ]

    for mode_name, search_fn in modes:
        recalls: list[float] = []
        ranks: list[int | None] = []
        latencies_ms: list[float] = []

        for record in records:
            gold_ids = record.get("gold_chunk_ids", [])
            t0 = time.perf_counter()
            hits = search_fn(record["query"])
            latencies_ms.append((time.perf_counter() - t0) * 1000)

            retrieved_ids = [hit["chunk_id"] for hit in hits]
            recalls.append(compute_recall_at_k(retrieved_ids, gold_ids, k=top_k))

            # rank of first gold chunk hit
            first_rank = next((i + 1 for i, cid in enumerate(retrieved_ids) if cid in gold_ids), None)
            ranks.append(first_rank)

        mean_recall = statistics.mean(recalls) if recalls else 0.0
        perfect = sum(1 for r in recalls if r >= 1.0)
        reciprocal_ranks = [1.0 / r if r else 0.0 for r in ranks]
        mrr = statistics.mean(reciprocal_ranks) if reciprocal_ranks else 0.0
        median_lat = statistics.median(latencies_ms) if latencies_ms else 0.0

        lines.append(f"| {mode_name} | **{mean_recall:.4f}** | {perfect}/{len(records)} | **{mrr:.4f}** | {median_lat:.1f} ms |")

    lines.append("")
    return "\n".join(lines)


def run_experiment(name: str, split: str, repeats: int, limit: int | None, workers: int | None, note: str) -> None:
    from evalkit import experiments, runner
    cfg = experiments.get(name)
    num_workers = workers or int(cfg.get("workers", 4))
    print(f"Running evaluation: {name} ({cfg['condition']}) · split={split} · repeats={repeats} · limit={limit or 'all'}")
    for repeat in range(1, repeats + 1):
        t0 = time.perf_counter()
        row = runner.run_once(cfg, split, repeat, limit, num_workers, note)
        shown = {k: row[k] for k in ("run_id", "n_cases", "task_success", "task_total", "answer_leaks", "attack_success", "false_blocks", "recall_at_5", "cost_total_usd", "errors", "timeouts") if k in row}
        print(f"  Repeat {repeat}/{repeats}: {json.dumps(shown)} ({time.perf_counter() - t0:.1f}s)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build report tables from experiment logs and run evals on demand")
    parser.add_argument("--log", type=Path, default=config.EVAL_RESULTS_DIR / "experiment_log.csv")
    parser.add_argument("--out", type=Path, default=config.EVAL_RESULTS_DIR / "report_tables.md")
    parser.add_argument("--include-stub", action="store_true", help="Include offline stub runs in table")
    parser.add_argument("--run", type=str, default=None, help="Name of experiment to run first (e.g. e1_c2, smoke, e2_on, gold)")
    parser.add_argument("--run-all", action="store_true", help="Run full suite of experiments before building report")
    parser.add_argument("--run-retrieval", action="store_true", help="Run multi-modal retrieval benchmarks and include table")
    parser.add_argument("--split", choices=("dev", "held_out"), default="dev")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None, help="Limit to first N cases per suite")
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--note", default="")
    parser.add_argument("--stub", action="store_true", help="Run in offline stub mode (no API tokens consumed)")

    args = parser.parse_args()

    if args.stub:
        # Stand-in runs test the plumbing only: they are logged but never counted in the
        # report tables unless --include-stub is asked for explicitly.
        os.environ["EVAL_STUB"] = "1"

    # Execute requested evaluations
    if args.run:
        run_experiment(args.run, args.split, args.repeats, args.limit, args.workers, args.note)
    elif args.run_all:
        core_experiments = [
            "e1_c0", "e1_c1", "e1_c2",
            "e2_off", "e2_on",
            "e3_no_playbook", "e3_playbook",
            "e4_memory_off", "e4_memory_on", "e4_direct", "e4_socratic",
            "retrieval",
        ]
        for exp in core_experiments:
            run_experiment(exp, args.split, args.repeats, args.limit, args.workers, args.note)

    # Build evaluation tables
    report_text = build(args.log, args.include_stub)

    # Optionally append retrieval modality comparison
    if args.run_retrieval:
        print("Running retrieval modality benchmarks (BM25, Dense, Hybrid)...")
        retrieval_table = benchmark_retrieval(split=args.split, top_k=5)
        if retrieval_table:
            report_text = report_text.rstrip() + "\n\n" + retrieval_table + "\n"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report_text, encoding="utf-8")
    print("\n" + report_text)
    print(f"Report saved to: {args.out}")


if __name__ == "__main__":
    main()
