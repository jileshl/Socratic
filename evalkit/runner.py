"""Run one experiment and log the results.

    python -m evalkit.runner e1_c2 --split dev
    python -m evalkit.runner e1_c2 --split held_out --repeats 3
    python -m evalkit.runner --list

Experiments are defined in evalkit/experiments.py.

Each repeat writes evalkit/results/runs/<run_id>/cases.jsonl (one record per case,
with transcripts) and summary.json, and appends one row to
evalkit/results/experiment_log.csv.
Failed and timed-out cases are kept and counted, as the guide requires.

Runs made with the offline stand-in (no API key, or EVAL_STUB=1) are marked
stub=true. They test the plumbing only; evalkit.report leaves them out.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from evalkit import ablations, datasets, experiments, llm_client, prompts, suites
from evalkit.systems import make_system
from socratic_tutor import config

LOG_COLUMNS = [
    "run_id", "timestamp_utc", "git_sha", "config", "experiment", "condition", "system", "split", "repeat",
    "stub", "prompt_version", "supervisor_model", "specialist_model", "judge_model", "simulated_student_model", "flags",
    "suites", "n_cases", "task_success", "task_total", "answer_leaks", "policy_violations", "misconception_hits",
    "mean_learning_gain", "judge_pass", "judge_accuracy", "judge_misconception", "judge_socratic", "attack_success", "attacks_total", "false_blocks", "clean_total",
    "recall_at_5", "mrr", "grader_agreement", "cost_total_usd", "cost_per_case_usd", "llm_calls",
    "latency_p50_s", "latency_p95_s", "errors", "timeouts", "note",
]


def git_sha() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=config.BASE_DIR, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=config.BASE_DIR, timeout=5).stdout.strip()
        return (sha or "nogit") + ("-dirty" if dirty else "")
    except Exception:
        return "nogit"


def _run_cases(items: list[Any], fn: Callable[[Any], dict[str, Any]], workers: int, case_id: Callable[[Any], str], suite: str) -> list[dict[str, Any]]:
    """Run cases with a per-case timeout; errors and timeouts become result rows."""
    results: list[dict[str, Any]] = []

    def safe(item: Any) -> dict[str, Any]:
        try:
            return fn(item)
        except Exception as exc:
            return {"case_id": case_id(item), "suite": suite, "success": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-2000:], "latency_s": None}

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [(item, pool.submit(safe, item)) for item in items]
        for item, future in futures:
            try:
                results.append(future.result(timeout=config.CASE_TIMEOUT_SECONDS))
            except FutureTimeout:
                results.append({"case_id": case_id(item), "suite": suite, "success": False, "timeout": True, "latency_s": float(config.CASE_TIMEOUT_SECONDS)})
    return results


def run_once(cfg: dict[str, Any], split: str, repeat: int, limit: int | None, workers: int, note: str) -> dict[str, Any]:
    llm_client.patch_team_llm_for_stub()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}_{cfg['name']}_{split}_r{repeat}"
    run_dir = config.EVAL_RESULTS_DIR / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    flags = {k: bool(v) for k, v in cfg["switches"].items()}
    system_name = cfg.get("system", "c2")
    options = {"sessions_per_student": cfg["sessions_per_student"], "judge": cfg["judge"]}
    tag = f"{cfg['name']}-{repeat}-{stamp[-7:-1]}"
    cases: list[dict[str, Any]] = []

    with ablations.applied(defences=flags.get("defences", True), memory=flags.get("memory", True), playbook=flags.get("playbook", False)):
        for suite in cfg["suites"]:
            if suite == "sessions":
                cards = datasets.simulated_students(split)[:limit]
                cases += _run_cases(cards, lambda c: suites.run_session_case(c, make_system(system_name), split, tag, options), workers, lambda c: c["student_id"], suite)
            elif suite == "gold":
                questions = datasets.gold_questions(split)[:limit]
                cases += _run_cases(questions, lambda q: suites.run_gold_case(q, options), workers, lambda q: q["id"], suite)
            elif suite == "redteam":
                attacks = datasets.redteam_attacks()[:limit]
                system = make_system(system_name)
                cases += _run_cases(attacks, lambda a: suites.run_redteam_case(a, system, tag), 1, lambda a: a["id"], suite)
            elif suite == "clean":
                clean = datasets.clean_cases()[:limit]
                system = make_system(system_name)
                cases += _run_cases(clean, lambda c: suites.run_clean_case(c, system, tag), 1, lambda c: c["id"], suite)
            elif suite == "retrieval":
                cases += suites.run_retrieval(split)[:limit]
            else:
                raise ValueError(f"Unknown suite {suite!r}")

    with open(run_dir / "cases.jsonl", "w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False, default=str) + "\n")

    row = summarise(cases, cfg, split, repeat, run_id, flags, note)
    (run_dir / "summary.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
    append_log(row)
    return row


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[index], 3)


def summarise(cases: list[dict[str, Any]], cfg: dict[str, Any], split: str, repeat: int, run_id: str, flags: dict[str, bool], note: str) -> dict[str, Any]:
    by = lambda suite: [c for c in cases if c.get("suite") == suite]  # noqa: E731
    sessions, gold, redteam, clean, retrieval = by("sessions"), by("gold"), by("redteam"), by("clean"), by("retrieval")
    ok = lambda rows: [r for r in rows if not r.get("error") and not r.get("timeout")]  # noqa: E731
    task_rows = sessions or gold
    costs = [c.get("cost_usd") for c in cases if c.get("cost_usd") is not None]
    cost_known = bool(cases) and all(c.get("cost_usd") is not None for c in ok(cases))
    latencies = [c["latency_s"] for c in cases if c.get("latency_s") is not None]
    judged = [c for c in ok(sessions) if c.get("judge", {}).get("scores")]
    mean_score = lambda dim: round(statistics.mean(c["judge"]["scores"][dim] for c in judged), 2) if judged else ""  # noqa: E731
    graded = [g for c in ok(gold) for g in c.get("grading", [])]
    return {
        "run_id": run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "config": cfg["name"],
        "experiment": cfg.get("experiment", ""),
        "condition": cfg.get("condition", cfg["name"]),
        "system": cfg.get("system", "c2"),
        "split": split,
        "repeat": repeat,
        "stub": llm_client.stub_mode(),
        "prompt_version": prompts.PROMPT_VERSION,
        "supervisor_model": config.SUPERVISOR_MODEL,
        "specialist_model": config.SPECIALIST_MODEL,
        "judge_model": config.JUDGE_MODEL,
        "simulated_student_model": config.SIMULATED_STUDENT_MODEL,
        "flags": json.dumps(ablations.describe(**{k: flags.get(k, d) for k, d in (("defences", True), ("memory", True), ("playbook", False))}), sort_keys=True),
        "suites": "+".join(cfg["suites"]),
        "n_cases": len(cases),
        "task_success": sum(bool(c.get("success")) for c in task_rows) if task_rows else "",
        "task_total": len(task_rows) if task_rows else "",
        "answer_leaks": sum(c.get("answer_leaks", 0) for c in sessions) if sessions else "",
        "policy_violations": sum(c.get("policy_violations", 0) for c in sessions) if sessions else "",
        "misconception_hits": sum(bool(c.get("misconception_hit")) for c in sessions) if sessions else "",
        "mean_learning_gain": round(statistics.mean(c["learning_gain"] for c in ok(sessions)), 3) if ok(sessions) else "",
        "judge_pass": sum(bool(c["judge"]["passed"]) for c in judged) if judged else "",
        "judge_accuracy": mean_score("conceptual_accuracy"),
        "judge_misconception": mean_score("identified_misconception"),
        "judge_socratic": mean_score("socratic_guidance"),
        "attack_success": sum(bool(c.get("attack_succeeded")) for c in redteam) if redteam else "",
        "attacks_total": len(redteam) if redteam else "",
        "false_blocks": sum(bool(c.get("false_block")) for c in clean) if clean else "",
        "clean_total": len(clean) if clean else "",
        "recall_at_5": round(statistics.mean(c["recall_at_5"] for c in (retrieval or ok(gold))), 4) if (retrieval or ok(gold)) else "",
        "mrr": round(statistics.mean(c["reciprocal_rank"] for c in retrieval), 4) if retrieval else "",
        "grader_agreement": round(sum(g["agree"] for g in graded) / len(graded), 3) if graded else "",
        "cost_total_usd": round(sum(costs), 4) if cost_known else "",
        "cost_per_case_usd": round(sum(costs) / len(cases), 5) if cost_known and cases else "",
        "llm_calls": sum(c.get("llm_calls", 0) or 0 for c in cases),
        "latency_p50_s": "" if _pct(latencies, 0.5) is None else _pct(latencies, 0.5),
        "latency_p95_s": "" if _pct(latencies, 0.95) is None else _pct(latencies, 0.95),
        "errors": sum(bool(c.get("error")) for c in cases),
        "timeouts": sum(bool(c.get("timeout")) for c in cases),
        "note": note,
    }


def append_log(row: dict[str, Any]) -> Path:
    path = config.EVAL_RESULTS_DIR / "experiment_log.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_COLUMNS, extrasaction="ignore")
        if new:
            writer.writeheader()
        writer.writerow(row)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one evaluation experiment (see evalkit/experiments.py)")
    parser.add_argument("experiment", nargs="?", help="experiment name, e.g. e1_c2")
    parser.add_argument("--list", action="store_true", help="list the experiments and exit")
    parser.add_argument("--split", choices=datasets.SPLITS, default="dev")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases of each suite (smoke tests)")
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--note", default="")
    parser.add_argument("--stub", action="store_true", help="use the offline stand-in model (plumbing check; never reported)")
    args = parser.parse_args()
    if args.stub:
        import os

        os.environ["EVAL_STUB"] = "1"

    if args.list or not args.experiment:
        for name, spec in experiments.EXPERIMENTS.items():
            print(f"{name:16} {spec['experiment']:6} {spec['condition']}")
        return
    cfg = experiments.get(args.experiment)
    workers = args.workers or int(cfg["workers"])
    if args.split == "held_out":
        print(
            "HELD-OUT RUN. Do not change prompts, code or lessons after looking at these results. "
            "If you do, treat these cases as development cases from now on and say so in the report."
        )
    if llm_client.stub_mode():
        print("STUB MODE: no API key found (or EVAL_STUB=1). Results test the plumbing only and are excluded from the report.")
    for repeat in range(1, args.repeats + 1):
        started = time.perf_counter()
        row = run_once(cfg, args.split, repeat, args.limit, workers, args.note)
        shown = {k: row[k] for k in ("run_id", "n_cases", "task_success", "task_total", "answer_leaks", "attack_success", "false_blocks", "recall_at_5", "cost_total_usd", "errors", "timeouts")}
        print(json.dumps(shown), f"({time.perf_counter() - started:.0f}s)")


if __name__ == "__main__":
    main()
