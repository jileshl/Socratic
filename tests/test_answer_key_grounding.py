"""The question setter's answer keys come from math-tools, and only the right numbers are read (#49 review)."""

import pytest

from socratic_tutor.graph import _calculate_or_verify_answer


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Find the equivalent resistance of 6 ohm and 3 ohm in parallel.", "2 ohm"),
        # A battery voltage in the question must not be read as a resistor.
        ("A 6 V battery is connected to two resistors of 4 ohm and 12 ohm in series. Find the total resistance.", "16 ohm"),
        ("Three resistors of 2 ohm, 3 ohm and 6 ohm are in parallel across a 12 V battery. Find the total resistance.", "1 ohm"),
        # Lens power: a concave lens has a negative power.
        ("A concave lens has a focal length of 0.5 m. Find its power.", "-2 D"),
        ("A convex lens has a focal length of 0.25 m. Find its power.", "4 D"),
        ("A concave lens has a focal length of 25 cm. Find its power.", "-4 D"),
    ],
)
def test_answer_key_is_computed_from_the_question(question, expected):
    key, verified = _calculate_or_verify_answer(question, "", "")
    assert verified and key == expected
