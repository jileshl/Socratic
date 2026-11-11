"""Tests for socratic_tutor/solver_key.py: the solver computes every answer key (R4 plumbing PR-2, decision I2).

No test calls a model: the "model replies" here are plain dicts, and llm.get_llm is made to fail if anything
tries. The concept list is never read from data/.
"""

from __future__ import annotations

from typing import Any

import pytest

from socratic_tutor import llm, solver_key
from socratic_tutor.tools import math_tools_server
from socratic_tutor.tools.question_bank_server import answer_key_problem


MIRROR_QUESTION: str = (
    "An object is placed 30 cm in front of a concave mirror of focal length 20 cm. Find the image distance."
)
MIRROR_CALCULATION: dict[str, Any] = {
    "formula": "mirror_formula", "values": {"u": -30, "f": -20}, "length_unit": "cm", "find": "v",
}


@pytest.fixture(autouse=True)
def no_model_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any model call in these tests is a bug: make it fail loudly."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a model call in a test")

    monkeypatch.setattr(llm, "get_llm", refuse)


def test_mirror_draft_gets_the_solvers_key() -> None:
    # u = -30 cm, f = -20 cm: 1/v = 1/f - 1/u = -1/60, so v = -60 cm.
    result: dict[str, Any] = solver_key.solve_answer_key(MIRROR_QUESTION, MIRROR_CALCULATION)
    assert result["ok"] is True
    assert result["gold_answer"] == "-60 cm"
    assert result["solved_for"] == "v"
    # The key is one the grader's code can read.
    assert answer_key_problem(result["gold_answer"]) is None


def test_a_battery_voltage_is_not_a_resistor() -> None:
    # Regression for #49's regex helper, which counted "12 V" as a third resistor (2 ohm instead of 2.4 ohm).
    question: str = (
        "Two resistors of 4 ohm and 6 ohm are connected in parallel to a 12 V battery. "
        "Find the equivalent resistance."
    )
    calculation: dict[str, Any] = {"formula": "parallel_resistance", "values": {"resistors": [4, 6]}}
    result: dict[str, Any] = solver_key.solve_answer_key(question, calculation)
    assert result["ok"] is True
    assert result["gold_answer"] == "2.4 ohm"


def test_a_magnification_question_gets_m_not_v() -> None:
    # Regression: the regex helper gave a magnification question the image distance as its key.
    question: str = (
        "An object is placed 30 cm in front of a concave mirror of focal length 20 cm. Find the magnification."
    )
    wrong: dict[str, Any] = {
        "formula": "mirror_formula", "values": {"u": -30, "f": -20}, "length_unit": "cm", "find": "m",
    }
    refused: dict[str, Any] = solver_key.solve_answer_key(question, wrong)
    assert refused["ok"] is False
    assert "works out v" in refused["error"]
    # The right formula, with v given in the text, gives m = -v/u = -2.
    asked: str = "A concave mirror forms an image at 60 cm when the object is at 30 cm. Find the magnification."
    right: dict[str, Any] = {
        "formula": "mirror_magnification", "values": {"v": -60, "u": -30}, "length_unit": "cm", "find": "m",
    }
    result: dict[str, Any] = solver_key.solve_answer_key(asked, right)
    assert result["ok"] is True
    assert result["gold_answer"] == "-2"


def test_lens_power_has_no_type_error() -> None:
    # Regression: the regex helper called solve_lens_power(f_m=...) and crashed with a TypeError.
    in_metres: dict[str, Any] = solver_key.solve_answer_key(
        "A convex lens has a focal length of 0.5 m. Find its power.",
        {"formula": "lens_power", "values": {"f": 0.5}, "length_unit": "m", "find": "p"},
    )
    assert in_metres["ok"] is True
    assert in_metres["gold_answer"] == "2 D"
    # 50 cm is converted to metres inside the solver: still 2 D.
    in_cm: dict[str, Any] = solver_key.solve_answer_key(
        "A convex lens has a focal length of 50 cm. Find its power.",
        {"formula": "lens_power", "values": {"f": 50}, "length_unit": "cm", "find": "p"},
    )
    assert in_cm["ok"] is True
    assert in_cm["gold_answer"] == "2 D"


def test_keys_are_value_unit_never_name_equals() -> None:
    # Five drafts across both catalogues: no key is "name = value", and the grader can read every one.
    cases: list[tuple[str, dict[str, Any]]] = [
        (MIRROR_QUESTION, MIRROR_CALCULATION),
        ("A convex lens of focal length 20 cm forms an image of an object placed 30 cm in front of it. Find v.",
         {"formula": "lens_formula", "values": {"u": -30, "f": 20}, "length_unit": "cm", "find": "v"}),
        ("A potential difference of 12 V is applied across a 4 ohm resistor. Find the current.",
         {"formula": "ohms_law", "values": {"v": 12, "r": 4}, "find": "i"}),
        ("A 20 ohm resistor carries a current of 5 A for 30 s. Find the heat produced.",
         {"formula": "joule_heating", "values": {"r": 20, "i": 5, "t": 30}, "find": "h"}),
        ("Two lenses of power 2 D and -1.5 D are placed in contact. Find the total power.",
         {"formula": "combine_lens_powers", "values": {"powers": [2, -1.5]}}),
    ]
    expected: list[str] = ["-60 cm", "60 cm", "3 A", "15000 J", "0.5 D"]
    for position in range(len(cases)):
        question, calculation = cases[position]
        result: dict[str, Any] = solver_key.solve_answer_key(question, calculation)
        assert result["ok"] is True, result
        assert result["gold_answer"] == expected[position]
        assert "=" not in result["gold_answer"]
        assert answer_key_problem(result["gold_answer"]) is None


def test_a_draft_the_solver_cannot_compute_is_refused() -> None:
    # The object at the focus: the image is at infinity, so there is no key, and the solver's reason is kept.
    question: str = "An object is placed 15 cm in front of a concave mirror of focal length 15 cm. Find v."
    calculation: dict[str, Any] = {
        "formula": "mirror_formula", "values": {"u": -15, "f": -15}, "length_unit": "cm", "find": "v",
    }
    result: dict[str, Any] = solver_key.solve_answer_key(question, calculation)
    assert result["ok"] is False
    assert "infinity" in result["error"]
    assert "gold_answer" not in result


def test_the_models_own_key_is_never_used() -> None:
    # A wrong key from the model, next to a good calculation: the draft gets the solver's key.
    reply: dict[str, Any] = {
        "question_text": MIRROR_QUESTION, "gold_answer": "999 cm", "calculation": MIRROR_CALCULATION,
    }
    made: dict[str, Any] = solver_key.draft_from_model_reply("concept_mirror_formula", "easy", reply)
    assert made["ok"] is True
    assert made["draft"]["gold_answer"] == "-60 cm"
    # A key but no calculation: refused (decision P2-4), never proposed with the model's key.
    no_calculation: dict[str, Any] = {"question_text": MIRROR_QUESTION, "gold_answer": "-60 cm"}
    refused: dict[str, Any] = solver_key.draft_from_model_reply("concept_mirror_formula", "easy", no_calculation)
    assert refused["ok"] is False
    assert "without a calculation" in refused["error"]
    # A calculation the solver refuses (the object at the focus): refused too, never keyed with the model's key.
    at_focus: dict[str, Any] = {
        "question_text": "An object is placed 15 cm in front of a concave mirror of focal length 15 cm. Find v.",
        "gold_answer": "-15 cm",
        "calculation": {"formula": "mirror_formula", "values": {"u": -15, "f": -15}, "length_unit": "cm", "find": "v"},
    }
    not_keyed: dict[str, Any] = solver_key.draft_from_model_reply("concept_mirror_formula", "easy", at_focus)
    assert not_keyed["ok"] is False
    assert "draft" not in not_keyed


def test_given_values_must_be_in_the_question() -> None:
    # P2-5: u = -25 for a "30 cm" question would give a right key for a number the student never sees.
    wrong: dict[str, Any] = {
        "formula": "mirror_formula", "values": {"u": -25, "f": -20}, "length_unit": "cm", "find": "v",
    }
    refused: dict[str, Any] = solver_key.solve_answer_key(MIRROR_QUESTION, wrong)
    assert refused["ok"] is False
    assert "u = -25" in refused["error"]
    # A value given in SI units (0.0005 m) for a number written in mm (0.5 mm) counts as written.
    question: str = "A copper wire has a diameter of 0.5 mm. Find its cross-sectional area."
    result: dict[str, Any] = solver_key.solve_answer_key(
        question, {"formula": "wire_area", "values": {"diameter": 0.0005}},
    )
    assert result["ok"] is True
    assert result["gold_answer"].endswith(" m^2")


def test_a_sign_against_concave_or_convex_is_refused_not_flipped() -> None:
    # P2-13: a concave mirror needs f < 0. With f = +20 the solver would give v = 12 cm, a wrong key.
    wrong: dict[str, Any] = {
        "formula": "mirror_formula", "values": {"u": -30, "f": 20}, "length_unit": "cm", "find": "v",
    }
    refused: dict[str, Any] = solver_key.solve_answer_key(MIRROR_QUESTION, wrong)
    assert refused["ok"] is False
    assert "must be negative" in refused["error"]
    # A convex lens with a negative power is refused too.
    lens: dict[str, Any] = solver_key.solve_answer_key(
        "A convex lens has a power of 2 D. Find its focal length.",
        {"formula": "lens_power", "values": {"p": -2}, "length_unit": "m", "find": "f"},
    )
    assert lens["ok"] is False
    assert "must be positive" in lens["error"]


def test_a_text_naming_both_kinds_is_not_sign_checked() -> None:
    # "concave" and "convex" both in the text: the words can't tell which one f belongs to, so no sign check.
    question: str = (
        "A convex mirror and a concave mirror are on a table. The concave mirror has a focal length of 20 cm "
        "and an object is 30 cm in front of it. Find v."
    )
    result: dict[str, Any] = solver_key.solve_answer_key(question, MIRROR_CALCULATION)
    assert result["ok"] is True
    assert result["gold_answer"] == "-60 cm"


def test_unknown_formulas_inputs_and_shapes_are_refused() -> None:
    # Each bad calculation is refused with a reason; nothing raises.
    bad: list[Any] = [
        {"formula": "magic", "values": {"u": -30}, "find": "v"},
        {"formula": "mirror_formula", "values": {"x": 30, "f": -20}, "length_unit": "cm", "find": "v"},
        {"formula": "mirror_formula", "values": {"u": True, "f": -20}, "length_unit": "cm", "find": "v"},
        {"formula": "mirror_formula", "values": {"u": "-30", "f": "-20"}, "length_unit": "cm", "find": "v"},
        {"formula": "mirror_formula", "values": {"u": -30, "f": -20}, "length_unit": "cm"},
        {"formula": "mirror_formula", "values": {"u": -30, "f": -20}, "unit": "cm", "find": "v"},
        {"formula": "", "values": {"u": -30, "f": -20}},
        {"values": {"u": -30, "f": -20}},
        {"formula": "mirror_formula", "values": [], "find": "v"},
        {"formula": "mirror_formula", "values": {}, "find": "v"},
        "mirror_formula u=-30 f=-20",
        None,
        42,
    ]
    for calculation in bad:
        result: dict[str, Any] = solver_key.solve_answer_key(MIRROR_QUESTION, calculation)
        assert result["ok"] is False, calculation
        assert isinstance(result["error"], str) and result["error"] != ""
    # An empty question text is refused too.
    assert solver_key.solve_answer_key("", MIRROR_CALCULATION)["ok"] is False


def test_the_flat_calculation_shape_of_pr53_is_accepted() -> None:
    # Jilesh's #53 shape: the values next to "formula", and short formula names ("mirror", "parallel").
    flat: dict[str, Any] = {"formula": "mirror_formula", "u": -30, "f": -20, "length_unit": "cm", "find": "v"}
    assert solver_key.solve_answer_key(MIRROR_QUESTION, flat)["gold_answer"] == "-60 cm"
    alias: dict[str, Any] = {"formula": "Mirror", "u": -30, "f": -20, "length_unit": "cm", "find": "v"}
    assert solver_key.solve_answer_key(MIRROR_QUESTION, alias)["gold_answer"] == "-60 cm"
    parallel: dict[str, Any] = solver_key.solve_answer_key(
        "Two resistors of 4 ohm and 6 ohm are joined in parallel. Find the equivalent resistance.",
        {"formula": "parallel", "resistors": [4, 6]},
    )
    assert parallel["gold_answer"] == "2.4 ohm"


def test_keys_the_grader_cannot_read_are_refused() -> None:
    # Resistivity comes out in "ohm m", which the grader's unit table doesn't know: refused, not proposed.
    question: str = "A wire of length 1 m and cross-section 1 x 10^-6 m^2 has a resistance of 10 ohm. Find rho."
    calculation: dict[str, Any] = {
        "formula": "resistivity", "values": {"r": 10, "length": 1, "area": 1e-6}, "find": "rho",
    }
    result: dict[str, Any] = solver_key.solve_answer_key(question, calculation)
    assert result["ok"] is False
    assert "ohm m" in result["error"]
    # The refusal never quotes the computed number.
    assert "1e-05" not in result["error"]


def test_drafts_take_concept_and_difficulty_from_the_request() -> None:
    # The model says another concept and difficulty; the draft keeps the requested ones (rule 1: code decides).
    reply: dict[str, Any] = {
        "concept_id": "concept_x", "difficulty": "hard",
        "question_text": MIRROR_QUESTION, "calculation": MIRROR_CALCULATION,
    }
    made: dict[str, Any] = solver_key.draft_from_model_reply("concept_mirror_formula", "easy", reply)
    assert made["ok"] is True
    assert made["draft"] == {
        "concept_id": "concept_mirror_formula",
        "difficulty": "easy",
        "prompt": MIRROR_QUESTION,
        "gold_answer": "-60 cm",
    }


def test_drafts_for_concept_asks_once_per_draft() -> None:
    # Three drafts: one model call each, for easy, medium and hard; one bad reply fails alone.
    calls: list[tuple[str, str]] = []

    def fake_model(concept_id: str, difficulty: str) -> dict[str, Any]:
        calls.append((concept_id, difficulty))
        if difficulty == "medium":
            return {"question_text": MIRROR_QUESTION}  # no calculation: refused
        return {"question_text": MIRROR_QUESTION, "calculation": MIRROR_CALCULATION}

    made: dict[str, Any] = solver_key.drafts_for_concept("concept_mirror_formula", 3, fake_model)
    assert calls == [
        ("concept_mirror_formula", "easy"),
        ("concept_mirror_formula", "medium"),
        ("concept_mirror_formula", "hard"),
    ]
    assert len(made["drafts"]) == 2
    assert len(made["refused"]) == 1
    assert made["refused"][0]["difficulty"] == "medium"
    # More than five, or none: no model call at all.
    calls.clear()
    assert solver_key.drafts_for_concept("concept_mirror_formula", 6, fake_model)["drafts"] == []
    assert solver_key.drafts_for_concept("concept_mirror_formula", 0, fake_model)["drafts"] == []
    assert calls == []


def test_a_model_error_reply_is_refused() -> None:
    # llm.chat_json returns {"error": ...} on any failure; a reply that isn't a dict is refused too.
    error_reply: dict[str, Any] = {"error": "Failed to complete chat_json: timeout"}
    assert solver_key.draft_from_model_reply("concept_mirror_formula", "easy", error_reply)["ok"] is False
    assert solver_key.draft_from_model_reply("concept_mirror_formula", "easy", "not json")["ok"] is False

    # A model call that raises is one refused draft, not a crash.
    def broken_model(concept_id: str, difficulty: str) -> dict[str, Any]:
        raise TimeoutError("no answer")

    made: dict[str, Any] = solver_key.drafts_for_concept("concept_mirror_formula", 1, broken_model)
    assert made["drafts"] == []
    assert "TimeoutError" in made["refused"][0]["error"]


def test_the_formula_list_names_every_catalogue_formula() -> None:
    # The model is shown every formula it may use, and the fixed result of each one-way formula.
    text: str = solver_key.formula_list_for_the_model()
    for name in math_tools_server.OPTICS_FORMULAS:
        assert name in text
    for name in math_tools_server.ELECTRICITY_FORMULAS:
        assert name in text
    for name in solver_key.ONE_WAY_RESULTS:
        assert name + ": find is " + solver_key.ONE_WAY_RESULTS[name] in text
