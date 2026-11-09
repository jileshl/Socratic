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


def test_node_grader_looks_up_key_from_question_bank(monkeypatch, tmp_path) -> None:
    from socratic_tutor.graph import node_grader
    from socratic_tutor.tools import question_bank

    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "question_bank.db")
    question_bank._init_db()

    proposed = question_bank.propose_question(
        concept_id="concept_ohms_law",
        difficulty="easy",
        prompt="12 V across 6 ohm: current?",
        gold_answer="2 A",
    )
    qid = proposed["question_id"]
    question_bank.publish_approved_question(qid)

    state = {
        "student_attempt": "2 A",
        "current_question_id": qid,
        "mode": "quiz",
    }
    result = node_grader(state)
    assert result["grade_result"]["is_correct"] is True
    assert result["grade_result"]["score"] == 1.0

    state_wrong = {
        "student_attempt": "5 A",
        "current_question_id": qid,
        "mode": "quiz",
    }
    result_wrong = node_grader(state_wrong)
    assert result_wrong["grade_result"]["is_correct"] is False
    assert result_wrong["grade_result"]["score"] == 0.0

