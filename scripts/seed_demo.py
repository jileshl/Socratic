"""Clearly-labelled demo data for the live demo and the backup recording.

    python -m scripts.seed_demo            questions waiting for teacher approval
    python -m scripts.seed_demo --class    also the demo class: personas A/B + six demo students
    python -m scripts.seed_demo --clear    remove every demo student (questions stay)

The teacher view's "Demo guide" tab does the same (only when OPS_DEMO=1).
What is and is not added is described in socratic_tutor/web/demo_data.py.
"""

from __future__ import annotations

import argparse

from socratic_tutor.learner_store import LearnerStore
from socratic_tutor.web import demo_data
from socratic_tutor.web.ops_store import OpsStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Clearly-labelled demo data")
    parser.add_argument("--class", dest="demo_class", action="store_true", help="also add the demo class and personas A/B")
    parser.add_argument("--clear", action="store_true", help="remove every demo student")
    args = parser.parse_args()
    if args.clear:
        print(demo_data.clear_demo_class(LearnerStore(), OpsStore()))
        return
    if args.demo_class:
        print(demo_data.seed_demo_class(LearnerStore(), OpsStore()))
    for item in demo_data.propose_demo_questions():
        print(f"proposed {item['question_id']}: {item['prompt'][7:60]}…  ({item['answer']})")
    print("Open the teacher view → Approvals to review them.")


if __name__ == "__main__":
    main()
