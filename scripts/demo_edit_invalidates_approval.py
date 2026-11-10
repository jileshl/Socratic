"""The guide's live demo for the approval gate: "an edit invalidating an earlier approval" (capstone guide p.3).

It runs the whole sequence on TEMPORARY files (a temporary question bank and a temporary checkpoint
database), so no question is ever written to the real bank (importing question_bank only makes sure the
real bank's table exists, as every import of it does), and prints each step:
    1. two questions are proposed (pending: students can't see them)
    2. the set is submitted: it waits, with hash H1
    3. the teacher edits one answer key: a new version, hash H2, waiting again
    4. an approval signed for H1 is REFUSED as stale; nothing is published
    5. an approval signed for H2 publishes both questions, with the edited key
    6. a second click on approve changes nothing

Run it from the repository root, like the other scripts:
    PowerShell:  $env:PYTHONPATH = "."; python scripts/demo_edit_invalidates_approval.py
    bash:        PYTHONPATH=. python scripts/demo_edit_invalidates_approval.py
"""

import os
import sqlite3
import tempfile
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from socratic_tutor import approval_gate
from socratic_tutor.tools import question_bank

# The demo signs its decisions with its own throwaway key (the real key lives in .env as APPROVAL_SIGNING_KEY).
DEMO_KEY: str = "demo-only-key"
TEACHER: str = "teacher_demo"


def statuses() -> str:
    """Every question's status in the demo bank, e.g. 'Q_1a2b3c4d=pending_approval, ...'."""
    connection = sqlite3.connect(question_bank.DB_PATH)
    rows = connection.execute("SELECT id, status FROM questions").fetchall()
    connection.close()
    parts: list[str] = []
    for row in rows:
        parts.append(row[0] + "=" + row[1])
    return ", ".join(parts)


def run_demo(work_dir: Path) -> list[str]:
    """Run the six steps in work_dir and return the printed lines (the tests check them)."""
    lines: list[str] = []
    # The demo's own question bank, in work_dir.
    question_bank.DB_PATH = work_dir / "demo_question_bank.db"
    question_bank._init_db()
    # The demo's own checkpoint database, in work_dir.
    connection = sqlite3.connect(work_dir / "demo_checkpoints.sqlite", check_same_thread=False)
    graph = approval_gate.build_approval_graph(SqliteSaver(connection))
    try:
        # 1. Two questions, as the question setter would propose them.
        first = question_bank.propose_question(
            "concept_ohms_law", "easy", "A 12 V battery is connected across a 4 ohm resistor. What is the current?", "3 A")
        second = question_bank.propose_question(
            "concept_mirror_formula", "medium",
            "An object is 30 cm in front of a concave mirror of focal length 20 cm. Where is the image?", "-60 cm")
        lines.append("1. proposed " + first["question_id"] + " and " + second["question_id"] + ": " + statuses())

        # 2. Submit the set: it waits for the teacher.
        submitted = approval_gate.submit_set(graph, [first["question_id"], second["question_id"]], set_id="set_demo")
        hash_one = submitted["payload_hash"]
        lines.append("2. submitted set_demo: waiting, hash H1 = " + hash_one[:12])

        # 3. The teacher edits the second answer key: a new version with a new hash.
        changes = {second["question_id"]: {"gold_answer": "-60.0 cm"}}
        edit = approval_gate.sign_decision("set_demo", "edit", hash_one, TEACHER, changes=changes, key=DEMO_KEY)
        edited = approval_gate.decide(graph, "set_demo", edit)
        hash_two = edited["payload_hash"]
        lines.append("3. edited the key of " + second["question_id"] + ": " + edited["status"] + ", hash H2 = " + hash_two[:12])

        # 4. An approval for the OLD version is refused: the edit invalidated it.
        old_approval = approval_gate.sign_decision("set_demo", "approve", hash_one, TEACHER, key=DEMO_KEY)
        refused = approval_gate.decide(graph, "set_demo", old_approval)
        lines.append("4. approve with H1: " + refused["status"] + " (" + refused["note"] + ") " + statuses())

        # 5. An approval for the new version publishes both questions, with the edited key.
        new_approval = approval_gate.sign_decision("set_demo", "approve", hash_two, TEACHER, key=DEMO_KEY)
        published = approval_gate.decide(graph, "set_demo", new_approval)
        stored_key = question_bank.get_questions([second["question_id"]])[0]["gold_answer"]
        lines.append("5. approve with H2: " + published["status"] + "; " + statuses() + "; key now " + stored_key)

        # 6. A second click changes nothing.
        again = approval_gate.decide(graph, "set_demo", new_approval)
        lines.append("6. approve again: " + again["status"])
    finally:
        connection.close()
    return lines


def main() -> None:
    """Run the demo in a fresh temporary folder and print each step."""
    # The gate reads the key from the environment, like the real server does.
    os.environ[approval_gate.SIGNING_KEY_VARIABLE] = DEMO_KEY
    with tempfile.TemporaryDirectory() as work_dir:
        for line in run_demo(Path(work_dir)):
            print(line)


if __name__ == "__main__":
    main()
