"""Integrity of the evaluation datasets (R5). All of them live in data/."""

import json
import subprocess
from pathlib import Path

import pytest

from evalkit import answer_keys, datasets
from evalkit.checkers import numbers_in
from socratic_tutor.kb import SECTION_TITLES
from socratic_tutor.tools import math_tools

ROOT = Path(__file__).resolve().parent.parent
GOLD = datasets.gold_questions("dev") + datasets.gold_questions("held_out")
CARDS = datasets.simulated_students("dev") + datasets.simulated_students("held_out")
CONCEPTS = set(datasets.concepts())


def test_gold_set_size_and_split():
    assert len(GOLD) >= 60
    assert len(datasets.gold_questions("held_out")) >= 40
    ids = [q["id"] for q in GOLD]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("q", GOLD, ids=lambda q: q["id"])
def test_gold_question_is_well_formed(q):
    assert q["concept_id"] in CONCEPTS
    assert q["gold_section_ids"] and all(s in SECTION_TITLES for s in q["gold_section_ids"])
    assert [a["is_correct"] for a in q["sample_answers"]] == [True, False]


@pytest.mark.parametrize("q", [q for q in GOLD if q["answer_specs"]], ids=lambda q: q["id"])
def test_written_answer_matches_the_code_answer(q):
    stated = numbers_in(q["gold_answer"])
    for spec in q["answer_specs"]:
        value = answer_keys.solve(spec)
        assert any(abs(abs(s) - abs(value)) <= max(0.02 * abs(value), 0.011) for s in stated), (q["id"], value, stated)


def test_every_check_row_points_at_a_real_question():
    checks = [json.loads(l) for l in (ROOT / "data/gold_question_checks.jsonl").read_text().splitlines() if l.strip()]
    assert {c["id"] for c in checks} == {q["id"] for q in GOLD}


def test_simulated_students():
    assert len(CARDS) == 40
    assert len(datasets.simulated_students("dev")) == len(datasets.simulated_students("held_out")) == 20
    for card in CARDS:
        assert 1 <= len(card["seeded_misconceptions"]) <= 2
        assert all(m in datasets.misconceptions() for m in card["seeded_misconceptions"])
        assert card["pre_quiz"] and len(card["pre_quiz"]) == len(card["post_quiz"])
        assert card["practice_problem"]["split"] == card["split"]
        assert all(c in CONCEPTS for c in card["knowledge_state"])
    ids = [c["student_id"] for c in CARDS]
    assert len(ids) == len(set(ids))


def test_quiz_items_and_practice_answers():
    for item in datasets.quiz_bank().values():
        assert set(item["options"]) == {"A", "B", "C", "D"} and item["correct"] != item["misconception_option"]
        if item.get("answer_spec"):
            assert answer_keys.solve(item["answer_spec"]) == pytest.approx(item["answer_spec"]["option_value"])
    for card in CARDS:
        answer = card["practice_problem"]["answer"]
        if answer["type"] == "numeric":  # the answer must differ from every given, or a leak could never be seen
            value = abs(answer_keys.solve(answer["spec"]))
            givens = [abs(g) for g in answer_keys.givens(answer["spec"])]
            assert all(abs(value - g) > 1e-9 for g in givens), card["practice_problem"]["id"]
        else:
            assert answer["key_phrases"]


def test_every_answer_key_is_computed_by_math_tools():
    """No formula is written twice: every key is a call into the team's calculator."""
    specs = [s for q in GOLD for s in q["answer_specs"]]
    specs += [c["practice_problem"]["answer"]["spec"] for c in CARDS if c["practice_problem"]["answer"]["type"] == "numeric"]
    specs += [i["answer_spec"] for i in datasets.quiz_bank().values() if i.get("answer_spec")]
    specs += [a["problem"]["answer"]["spec"] for a in datasets.redteam_attacks() if a.get("problem")]
    assert specs
    for spec in specs:
        assert hasattr(math_tools, spec["fn"]), spec
        answer_keys.solve(spec)


def test_red_team_suite():
    attacks, clean, fixtures = datasets.redteam_attacks(), datasets.clean_cases(), datasets.redteam_fixtures()
    assert len(attacks) >= 30 and len(clean) >= 20
    assert {"teacher_impersonation", "pasted_injection", "data_path_injection", "minor_safety"} <= {a["category"] for a in attacks}
    assert any("I'm the teacher" in t for a in attacks for t in a["turns"])
    for attack in attacks:
        if attack.get("fixture"):
            assert attack["fixture"] in fixtures["poisoned_chunks"] or attack["fixture"] in fixtures
    assert all(c["chunk_id"].startswith("redteam_") for c in fixtures["poisoned_chunks"].values())


def test_team_rows_were_only_appended_to(tmp_path):
    """Rows written by teammates must stay byte-for-byte unchanged; new rows go at the end."""
    for name in ("data/gold_questions.jsonl", "data/simulated_students.jsonl"):
        try:
            base = subprocess.run(["git", "show", f"origin/main:{name}"], capture_output=True, text=True, cwd=ROOT, check=True).stdout
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("origin/main not available")
        # Since 13 Nov the held-out rows live in evalkit/held_out/ (a folder the agent cannot read): every row
        # on main must still exist, unchanged, in one of the two files.
        current = (ROOT / name).read_text(encoding="utf-8")
        held = ROOT / "evalkit" / "held_out" / name.split("/")[-1]
        rows = set(current.splitlines()) | (set(held.read_text(encoding="utf-8").splitlines()) if held.exists() else set())
        missing = [line for line in base.splitlines() if line.strip() and line not in rows]
        assert not missing, f"{name}: {len(missing)} existing row(s) were changed or lost"
