"""Put a few clearly-labelled demo questions in the bank, waiting for teacher approval.

Until the question-setter agent proposes items through the graph, this lets the
team demo the approval gate (approve, edit-invalidates-approval, reject) in the
teacher view. Answer keys come from the tutor's own calculator, never typed in.

    python scripts/seed_demo.py
"""

from __future__ import annotations

from socratic_tutor.tools import math_tools, question_bank


def main() -> None:
    mirror = math_tools.solve_mirror_formula(u=-30.0, f=-20.0)
    lens = math_tools.solve_lens_formula(u=-60.0, f=20.0)
    parallel = math_tools.solve_equivalent_resistance([6.0, 3.0], mode="parallel")
    items = [
        ("concept_mirror_formula", "medium", "[DEMO] An object is 30 cm in front of a concave mirror of focal length 20 cm. Find the image distance.", f"v = {mirror['v']} cm"),
        ("concept_lens_formula", "medium", "[DEMO] An object is 60 cm from a convex lens of focal length 20 cm. Find the image distance.", f"v = +{lens['v']} cm"),
        ("concept_parallel_combination", "easy", "[DEMO] Find the equivalent resistance of 6 ohm and 3 ohm in parallel.", f"{parallel['req']} ohm"),
    ]
    for concept, difficulty, prompt, answer in items:
        out = question_bank.propose_question(concept, difficulty, prompt, answer)
        print(f"proposed {out['question_id']}: {prompt[7:60]}…  ({answer})")
    print("Open the teacher view → Approvals to review them.")


if __name__ == "__main__":
    main()
