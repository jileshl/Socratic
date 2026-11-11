"""Put a few clearly-labelled demo questions in the bank, waiting for teacher approval as ONE question set.

This lets the team demo the approval gate (approve, edit-invalidates-approval, reject) in the teacher view
without a model call. (In the app, the teacher's "Propose a set" button asks the question setter instead.)
Answer keys come from the tutor's own calculator, never typed in.

    python -m scripts.seed_demo
"""

from __future__ import annotations

from typing import Any

from socratic_tutor import approval_gate
from socratic_tutor.tools import math_tools, question_bank


def main() -> None:
    # Flowchart (R4 plumbing PR-2):
    #
    #   [S1] the three demo rows, keys from the calculator, saved as 'pending_approval'
    #   [S2] approval_gate.submit_set: they wait as ONE set on its own thread (a new random set id each run)
    #   [S3] print the set id, or why it couldn't be submitted

    # [S1] the demo questions; each key is computed by the calculator.
    mirror = math_tools.solve_mirror_formula("cm", u=-30.0, f=-20.0)
    lens = math_tools.solve_lens_formula("cm", u=-60.0, f=20.0)
    parallel = math_tools.solve_parallel_resistance([6.0, 3.0])
    items = [
        ("concept_mirror_formula", "medium", "[DEMO] An object is 30 cm in front of a concave mirror of focal length 20 cm. Find the image distance.", f"{mirror['value']:g} cm"),
        ("concept_lens_formula", "medium", "[DEMO] An object is 60 cm from a convex lens of focal length 20 cm. Find the image distance.", f"{lens['value']:g} cm"),
        ("concept_parallel_combination", "easy", "[DEMO] Find the equivalent resistance of 6 ohm and 3 ohm in parallel.", f"{parallel['value']:g} ohm"),
    ]
    question_ids: list[str] = []
    for concept, difficulty, prompt, answer in items:
        out = question_bank.propose_question(concept, difficulty, prompt, answer)
        question_ids.append(out["question_id"])
        print(f"proposed {out['question_id']}: {prompt[7:60]}…  ({answer})")
    # [S2] one set, waiting for the teacher on the shared approval graph (.index/checkpoints.sqlite).
    submitted: dict[str, Any] = approval_gate.submit_set(approval_gate.get_approval_graph(), question_ids)
    # [S3] what happened.
    if submitted["ok"]:
        print(f"They wait for approval as one set: {submitted['set_id']}.")
    else:
        print("The set could not be submitted: " + str(submitted["error"]))
    print("Open the teacher view → Approvals to review them.")


if __name__ == "__main__":
    main()
