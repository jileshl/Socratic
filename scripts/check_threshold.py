"""CI eval gate: fail the build when a measured metric falls below its floor.

    python -m scripts.check_threshold            # floor: CI_MIN_RECALL_AT_5 in socratic_tutor/config.py

Runs the retrieval suite (no LLM calls, so no API key is needed in CI),
prints the result, and exits with status 1 if Recall@5 is below the floor.
"""

from __future__ import annotations

import statistics
import sys

from evalkit import suites
from socratic_tutor import config


def main() -> int:
    rows = suites.run_retrieval("dev")
    recall = statistics.mean(r["recall_at_5"] for r in rows)
    floor = float(config.CI_MIN_RECALL_AT_5)
    misses = [r["case_id"] for r in rows if r["recall_at_5"] < 1.0]
    print(f"Retrieval gate: Recall@5 = {recall:.4f} on {len(rows)} dev queries (floor {floor:.2f})")
    if misses:
        print(f"Queries without full recall: {', '.join(misses)}")
    if recall < floor:
        print(f"FAIL: Recall@5 {recall:.4f} is below the floor {floor:.2f} (CI_MIN_RECALL_AT_5 in socratic_tutor/config.py)")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
