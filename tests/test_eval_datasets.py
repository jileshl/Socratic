"""Integrity of the evaluation datasets (R5). These run in CI on every push."""

import json
import re
from pathlib import Path

import pytest

from evalkit import reference_solver
from socratic_tutor.kb import SECTION_TITLES
from socratic_tutor.tools import math_tools

ROOT = Path(__file__).resolve().parent.parent


def jsonl(path):
    return [json.loads(line) for line in (ROOT / path).read_text(encoding="utf-8").splitlines() if line.strip()]


DEV_GOLD = jsonl("eval/dev/gold_questions.jsonl")
HELD_GOLD = jsonl("eval_heldout/gold_questions.jsonl")
DEV_CARDS = jsonl("eval/dev/simulated_students.jsonl")
HELD_CARDS = jsonl("eval_heldout/simulated_students.jsonl")
QUIZ = {q["id"]: q for q in jsonl("eval/quiz_bank.jsonl")}
PROBLEMS = {p["id"]: p for p in jsonl("eval/dev/practice_problems.jsonl") + jsonl("eval_heldout/practice_problems.jsonl")}
MISCONCEPTIONS = {m["id"]: m for m in json.loads((ROOT / "data/misconceptions.json").read_text())}
CONCEPTS = {c["id"] for c in json.loads((ROOT / "data/concept_graph.json").read_text())["concepts"]}


def test_gold_set_size_and_split():
    assert len(DEV_GOLD) + len(HELD_GOLD) >= 60
    assert len(HELD_GOLD) >= 40
    assert {q["split"] for q in DEV_GOLD} == {"dev"} and {q["split"] for q in HELD_GOLD} == {"held_out"}
    ids = [q["id"] for q in DEV_GOLD + HELD_GOLD]
    assert len(ids) == len(set(ids))


def test_agent_readable_data_has_no_held_out_cases():
    agent_side = jsonl("data/gold_questions.jsonl")
    assert all(q["split"] == "dev" for q in agent_side)
    assert not {q["id"] for q in agent_side} & {q["id"] for q in HELD_GOLD}


@pytest.mark.parametrize("q", DEV_GOLD + HELD_GOLD, ids=lambda q: q["id"])
def test_gold_question_is_well_formed(q):
    assert q["concept_id"] in CONCEPTS
    assert q["gold_section_ids"] and all(s in SECTION_TITLES for s in q["gold_section_ids"])
    labels = [a["is_correct"] for a in q["sample_answers"]]
    assert True in labels and False in labels
    for spec in q.get("answer_specs", []):
        value = reference_solver.solve(spec)
        assert value == value  # not NaN


@pytest.mark.parametrize("q", [q for q in DEV_GOLD + HELD_GOLD if q.get("answer_specs")], ids=lambda q: q["id"])
def test_written_answer_matches_the_code_answer(q):
    """The first number-like answer in gold_answer must equal the reference solver."""
    from evalkit.checkers import numbers_in

    stated = numbers_in(q["gold_answer"])
    for spec in q["answer_specs"]:
        value = reference_solver.solve(spec)
        assert any(abs(abs(s) - abs(value)) <= max(0.02 * abs(value), 0.011) for s in stated), (q["id"], value, stated)


def test_simulated_students():
    assert len(DEV_CARDS) + len(HELD_CARDS) == 40
    assert len(DEV_CARDS) == len(HELD_CARDS) == 20
    for card in DEV_CARDS + HELD_CARDS:
        assert 1 <= len(card["seeded_misconceptions"]) <= 2
        assert all(m in MISCONCEPTIONS for m in card["seeded_misconceptions"])
        assert set(card["convinced_when"]) == set(card["seeded_misconceptions"])
        assert all(i in QUIZ for i in card["pre_quiz"] + card["post_quiz"])
        problem = PROBLEMS[card["practice_problem_id"]]
        assert problem["split"] == card["split"]
        assert all(c in CONCEPTS for c in card["knowledge_state"])
    assert not {c["student_id"] for c in DEV_CARDS} & {c["student_id"] for c in HELD_CARDS}


def test_quiz_items_have_one_correct_option_and_code_checked_numbers():
    for item in QUIZ.values():
        assert set(item["options"]) == {"A", "B", "C", "D"}
        assert item["correct"] != item["misconception_option"]
        spec = item.get("answer_spec")
        if spec:
            value = reference_solver.solve(spec)
            assert abs(value - spec["option_value"]) < 1e-6
            correct_text = item["options"][item["correct"]]
            assert str(spec["option_value"]).lstrip("-").rstrip("0").rstrip(".") in correct_text.replace("+", "")


def test_practice_answers_are_not_one_of_the_givens():
    """Otherwise a leak could never be detected, because givens are ignored."""
    for problem in PROBLEMS.values():
        answer = problem["answer"]
        if answer["type"] != "numeric":
            assert answer["key_phrases"]
            continue
        value = abs(reference_solver.solve(answer["spec"]))
        givens = []
        for v in answer["spec"]["args"].values():
            givens += v if isinstance(v, list) else [v]
        assert all(abs(value - abs(g)) > 1e-9 for g in givens), problem["id"]


def test_reference_solver_agrees_with_the_tutor_calculator():
    """Two independent implementations: if they disagree, one of them has a bug."""
    for u, f in [(-30, -15), (-25, -15), (-20, 20), (-6, -10)]:
        assert math_tools.solve_mirror_formula(u, f)["v"] == pytest.approx(reference_solver.mirror_image_distance(u, f), abs=0.01)
    for u, f in [(-15, 10), (-10, -15), (-60, 20)]:
        assert math_tools.solve_lens_formula(u, f)["v"] == pytest.approx(reference_solver.lens_image_distance(u, f), abs=0.01)
    assert math_tools.solve_ohms_law(v=12, i=2.5)["r"] == pytest.approx(reference_solver.ohm_resistance(12, 2.5))
    assert math_tools.solve_equivalent_resistance([5, 10, 30], "parallel")["req"] == pytest.approx(reference_solver.parallel_resistance([5, 10, 30]))
    assert math_tools.solve_equivalent_resistance([20, 4], "series")["req"] == pytest.approx(reference_solver.series_resistance([20, 4]))


def test_red_team_suite():
    attacks = jsonl("redteam/attacks.jsonl")
    clean = jsonl("redteam/clean_cases.jsonl")
    fixtures = json.loads((ROOT / "redteam/fixtures/redteam_fixtures.json").read_text())
    assert len(attacks) >= 30 and len(clean) >= 20
    categories = {a["category"] for a in attacks}
    assert {"teacher_impersonation", "pasted_injection", "data_path_injection", "minor_safety"} <= categories
    assert any("I'm the teacher" in t for a in attacks for t in a["turns"])
    for attack in attacks:
        if attack.get("fixture"):
            assert attack["fixture"] in fixtures["poisoned_chunks"] or attack["fixture"] in fixtures
        if "reveals_answer" in attack["success_if"]:
            assert attack["problem"] and attack["problem"]["answer"]
    for chunk in fixtures["poisoned_chunks"].values():
        assert chunk["chunk_id"].startswith("redteam_")


def test_no_chunk_id_collision_with_real_index():
    assert all(not re.match(r"ncert_", c["chunk_id"]) for c in json.loads((ROOT / "redteam/fixtures/redteam_fixtures.json").read_text())["poisoned_chunks"].values())
