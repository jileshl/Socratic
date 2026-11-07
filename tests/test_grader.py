"""Tests for the grader's numeric branch, which now uses math_tools.check_numeric_answer.

These cases never reach the LLM: the numeric check decides them in code.
"""

from socratic_tutor.agents import grader


def test_grader_marks_a_numeric_answer_with_units_in_code() -> None:
    """"-30cm" against the key "-30 cm" is correct. Before, float("-30cm") failed and the LLM graded it."""
    result = grader.grade_answer("-30cm", "-30 cm", is_numeric=True)
    assert result["is_correct"] is True
    assert result["score"] == 1.0
    assert "Matches" in result["feedback"]


def test_grader_explains_a_wrong_sign() -> None:
    """"30 cm" against "-30 cm" is wrong, and the feedback says why."""
    result = grader.grade_answer("30 cm", "-30 cm", is_numeric=True)
    assert result["is_correct"] is False
    assert result["score"] == 0.0
    assert "Wrong sign" in result["feedback"]
