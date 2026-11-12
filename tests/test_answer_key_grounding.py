"""The question setter's answer keys come from math-tools, and only the right numbers are read (#49 review).

R4 plumbing PR-2: the regex helper (graph._calculate_or_verify_answer) is replaced by socratic_tutor/solver_key.py.
The model now writes a calculation (formula + given values); code checks every given value against the question
text (with its unit) and the solver computes the key. The same questions and keys as before are checked here.
"""

from typing import Any

import pytest

from socratic_tutor import solver_key


@pytest.mark.parametrize(
    "question, calculation, expected",
    [
        ("Find the equivalent resistance of 6 ohm and 3 ohm in parallel.",
         {"formula": "parallel_resistance", "values": {"resistors": [6, 3]}}, "2 ohm"),
        # A battery voltage in the question must not be read as a resistor.
        ("A 6 V battery is connected to two resistors of 4 ohm and 12 ohm in series. Find the total resistance.",
         {"formula": "series_resistance", "values": {"resistors": [4, 12]}}, "16 ohm"),
        ("Three resistors of 2 ohm, 3 ohm and 6 ohm are in parallel across a 12 V battery. Find the total resistance.",
         {"formula": "parallel_resistance", "values": {"resistors": [2, 3, 6]}}, "1 ohm"),
        # Lens power: a concave lens has a negative focal length, so a negative power.
        ("A concave lens has a focal length of 0.5 m. Find its power.",
         {"formula": "lens_power", "values": {"f": -0.5}, "length_unit": "m", "find": "p"}, "-2 D"),
        ("A convex lens has a focal length of 0.25 m. Find its power.",
         {"formula": "lens_power", "values": {"f": 0.25}, "length_unit": "m", "find": "p"}, "4 D"),
        ("A concave lens has a focal length of 25 cm. Find its power.",
         {"formula": "lens_power", "values": {"f": -25}, "length_unit": "cm", "find": "p"}, "-4 D"),
    ],
)
def test_answer_key_is_computed_from_the_question(question: str, calculation: dict[str, Any], expected: str) -> None:
    result: dict[str, Any] = solver_key.solve_answer_key(question, calculation)
    assert result["ok"] is True, result
    assert result["gold_answer"] == expected


def test_a_concave_lens_with_a_positive_focal_length_is_refused() -> None:
    # The sign is never flipped from the words (that would hide a bad draft); a contradicting sign is refused.
    result: dict[str, Any] = solver_key.solve_answer_key(
        "A concave lens has a focal length of 0.5 m. Find its power.",
        {"formula": "lens_power", "values": {"f": 0.5}, "length_unit": "m", "find": "p"},
    )
    assert result["ok"] is False
    assert "must be negative" in result["error"]
