"""Clearly-labelled demo data for the live demo and the backup recording (R6).

Used by the teacher view's "Demo guide" tab (POST /api/ops/demo-data, only with OPS_DEMO=1)
and by `python -m scripts.seed_demo`.

What is added, and what is not:
- Questions: answer keys come from the tutor's own calculator, never typed in. They wait
  for teacher approval like any other question, so the approval demo is real.
- Demo students: every ID starts with "stu_demo_" and every alert says [DEMO]. They get
  learner records (mastery and misconceptions) and two open alerts, so the class overview
  and the alerts tab have something to show. No sessions, turns, costs or leaks are
  invented, so the dashboard's session, cost and leak numbers stay real.
- Names: each demo student gets a plain first name in the teacher's class list (their IDs, which
  start with "stu_demo_", and the [DEMO] alerts keep them apart from real students), and one demo
  student gets an assigned study plan marked [DEMO].
- Personas A and B (Signature challenge A: same question, different help):
  A has mastered the laws of reflection but thinks concave mirrors always invert (MISCON_LIGHT_03);
  B is still weak on the laws of reflection, a prerequisite (MISCON_LIGHT_01).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from socratic_tutor import approval_gate
from socratic_tutor.tools import math_tools, question_bank

DEMO_PREFIX = "stu_demo_"
PERSONA_A = "stu_demo_a"
PERSONA_B = "stu_demo_b"

# student_id -> (mastery by concept, misconceptions seen)
DEMO_STUDENTS: dict[str, tuple[dict[str, float], list[str]]] = {
    PERSONA_A: ({"concept_reflection_laws": 0.9, "concept_spherical_mirrors": 0.8, "concept_concave_ray_diagrams": 0.35}, ["MISCON_LIGHT_03"]),
    PERSONA_B: ({"concept_reflection_laws": 0.3, "concept_spherical_mirrors": 0.2}, ["MISCON_LIGHT_01"]),
    "stu_demo_class01": ({"concept_concave_ray_diagrams": 0.4, "concept_mirror_formula": 0.5}, ["MISCON_LIGHT_03", "MISCON_LIGHT_05"]),
    "stu_demo_class02": ({"concept_concave_ray_diagrams": 0.5, "concept_lens_formula": 0.6}, ["MISCON_LIGHT_03", "MISCON_LIGHT_11"]),
    "stu_demo_class03": ({"concept_parallel_combination": 0.3, "concept_ohms_law": 0.6}, ["MISCON_ELEC_07", "MISCON_ELEC_08"]),
    "stu_demo_class04": ({"concept_parallel_combination": 0.45, "concept_series_combination": 0.7}, ["MISCON_ELEC_08"]),
    "stu_demo_class05": ({"concept_myopia": 0.5, "concept_scattering": 0.7}, ["MISCON_EYE_11"]),
    "stu_demo_class06": ({"concept_refraction_laws": 0.55, "concept_refractive_index": 0.4}, ["MISCON_LIGHT_07", "MISCON_LIGHT_08"]),
}
# Names the "teacher" typed for the demo class.
DEMO_NAMES: dict[str, str] = {
    PERSONA_A: "Aarav",
    PERSONA_B: "Diya",
    "stu_demo_class01": "Meera",
    "stu_demo_class02": "Kabir",
    "stu_demo_class03": "Rohan",
    "stu_demo_class04": "Isha",
    "stu_demo_class05": "Arjun",
    "stu_demo_class06": "Zara",
}
# One assigned study plan, so the plan views have something to show (teacher rule 2: Ohm's law first).
DEMO_PLAN = (
    "stu_demo_class03",
    ["concept_ohms_law", "concept_series_combination", "concept_parallel_combination"],
    "[DEMO] Ohm's law first, then series, then parallel. Try the quiz after each one.",
)
DEMO_ALERTS: list[tuple[str, str, str]] = [
    ("stu_demo_class03", "stuck", "[DEMO] Stuck on parallel resistors for 3 sessions (teacher rule: remediate Ohm's law first)."),
    ("stu_demo_class05", "distress", "[DEMO] Distress language detected; please check in with this student."),
]


def propose_demo_questions() -> list[dict[str, Any]]:
    """Questions for the approval demo. Every key is computed by math-tools.

    R4 plumbing PR-2: the keys are written "value unit" ("-60 cm"), the form the grader's code reads ("v = -60 cm"
    can't be read, so a demo quiz answer fell back to the model), and the questions wait for the teacher as ONE
    question set on the approval gate (the teacher view lists and decides whole sets). Each item carries the set id.
    """
    mirror = math_tools.solve_mirror_formula("cm", u=-30.0, f=-20.0)
    lens = math_tools.solve_lens_formula("cm", u=-60.0, f=20.0)
    parallel = math_tools.solve_parallel_resistance([6.0, 3.0])
    series = math_tools.solve_series_resistance([4.0, 12.0])
    power = math_tools.solve_lens_power("m", f=-0.5)
    items = [
        ("concept_mirror_formula", "medium", "[DEMO] An object is 30 cm in front of a concave mirror of focal length 20 cm. Find the image distance.", f"{mirror['value']:g} cm"),
        ("concept_lens_formula", "medium", "[DEMO] An object is 60 cm from a convex lens of focal length 20 cm. Find the image distance.", f"{lens['value']:g} cm"),
        ("concept_parallel_combination", "easy", "[DEMO] Find the equivalent resistance of 6 ohm and 3 ohm in parallel.", f"{parallel['value']:g} ohm"),
        ("concept_series_combination", "easy", "[DEMO] A 6 V battery is connected to resistors of 4 ohm and 12 ohm in series. Find the total resistance.", f"{series['value']:g} ohm"),
        ("concept_lens_power", "easy", "[DEMO] A concave lens has a focal length of 0.5 m. Find its power.", f"{power['value']:g} D"),
    ]
    out = []
    question_ids: list[str] = []
    for concept, difficulty, prompt, answer in items:
        proposed = question_bank.propose_question(concept, difficulty, prompt, answer)
        question_ids.append(proposed["question_id"])
        out.append({"question_id": proposed["question_id"], "prompt": prompt, "answer": answer})
    # PR-2: the demo questions wait for approval as one set (a new random set id each time).
    submitted: dict[str, Any] = approval_gate.submit_set(approval_gate.get_approval_graph(), question_ids)
    set_id: str = ""
    if submitted.get("ok") is True:
        set_id = str(submitted["set_id"])
    for item in out:
        item["set_id"] = set_id
    return out


def seed_demo_class(learners: Any, ops: Any) -> dict[str, int]:
    """Learner records for the personas and the demo class, plus two [DEMO] alerts."""
    for student_id, (mastery, misconceptions) in DEMO_STUDENTS.items():
        for concept_id, score in mastery.items():
            learners.update_mastery(student_id, concept_id, score)
        for misconception_id in misconceptions:
            learners.record_misconception(student_id, misconception_id)
    for student_id, name in DEMO_NAMES.items():
        ops.add_student(student_id, name)
    plan_student, plan_concepts, plan_note = DEMO_PLAN
    ops.set_plan(plan_student, plan_concepts, plan_note, None)
    added = 0
    for student_id, kind, detail in DEMO_ALERTS:
        if not ops.has_open_alert(student_id, kind):
            ops.add_alert(student_id, None, kind, detail)
            added += 1
    return {"students": len(DEMO_STUDENTS), "alerts": added}


def clear_demo_class(learners: Any, ops: Any) -> dict[str, int]:
    """Remove every stu_demo_ student: learner record, name, plan, alerts and any sessions they had."""
    with sqlite3.connect(learners.db_path) as conn:
        ids = {row[0] for row in conn.execute("SELECT student_id FROM learners WHERE student_id LIKE ?", (DEMO_PREFIX + "%",))}
    ids |= {row["student_id"] for row in ops._all("SELECT DISTINCT student_id FROM alerts WHERE student_id LIKE ?", (DEMO_PREFIX + "%",))}
    ids |= {sid for sid in ops.roster() if sid.startswith(DEMO_PREFIX)}
    for student_id in ids:
        learners.forget_student(student_id)
        ops.forget(student_id)
    return {"students_removed": len(ids)}
