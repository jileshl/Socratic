"""CI eval gate: fail the build when a measured metric falls below its floor.

    python scripts/check_threshold.py            # uses config/eval_thresholds.yaml

Runs the retrieval suite (no LLM calls, so no API key is needed in CI),
prints the result, and exits with status 1 if Recall@5 is below the floor.
"""

from __future__ import annotations

import statistics
import sys

import yaml

from evalkit import suites
from socratic_tutor import config


def main() -> int:
    thresholds = yaml.safe_load((config.BASE_DIR / "config" / "eval_thresholds.yaml").read_text(encoding="utf-8"))
    rule = thresholds["retrieval"]
    rows = suites.run_retrieval(rule.get("split", "dev"))
    recall = statistics.mean(r["recall_at_5"] for r in rows)
    floor = float(rule["recall_at_5_min"])
    misses = [r["case_id"] for r in rows if r["recall_at_5"] < 1.0]
    print(f"Retrieval gate: Recall@5 = {recall:.4f} on {len(rows)} {rule.get('split', 'dev')} queries (floor {floor:.2f})")
    if misses:
        print(f"Queries without full recall: {', '.join(misses)}")
    if recall < floor:
        print(f"FAIL: Recall@5 {recall:.4f} is below the floor {floor:.2f} in config/eval_thresholds.yaml")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
