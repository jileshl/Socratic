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


def test_grader_handles_labelled_and_multi_part_numeric_answers_without_llm(monkeypatch) -> None:
    """Gold answers with labels ('v =', 'P =', 'I =') and student attempts with labels grade in code without LLM."""
    def fail_on_llm(*args, **kwargs):
        raise AssertionError("LLM should not be called for labelled numeric answers")

    monkeypatch.setattr(grader.llm, "chat_json", fail_on_llm)

    # 1. Labelled gold answer with 'I ='
    res1 = grader.grade_answer("2.5 A", "I = 2.5 A", is_numeric=True)
    assert res1["is_correct"] is True
    assert res1["score"] == 1.0

    # 2. Both student and gold answer have variable label
    res2 = grader.grade_answer("I = 2.5 A", "I = 2.5 A", is_numeric=True)
    assert res2["is_correct"] is True
    assert res2["score"] == 1.0

    # 3. Multi-part gold answer: "v = -37.5 cm; m = -1.5 (real, inverted, enlarged)."
    res3 = grader.grade_answer("-37.5 cm", "v = -37.5 cm; m = -1.5 (real, inverted, enlarged).", is_numeric=True)
    assert res3["is_correct"] is True
    assert res3["score"] == 1.0

    # 4. Student includes label "v = -37.5 cm"
    res4 = grader.grade_answer("v = -37.5 cm", "v = -37.5 cm; m = -1.5 (real, inverted, enlarged).", is_numeric=True)
    assert res4["is_correct"] is True
    assert res4["score"] == 1.0

    # 5. Labelled power of lens "P = +1.5 D"
    res5 = grader.grade_answer("+1.5 D", "P = +1.5 D", is_numeric=True)
    assert res5["is_correct"] is True
    assert res5["score"] == 1.0

    # 6. Wrong value for labelled question
    res6 = grader.grade_answer("10 A", "I = 2.5 A", is_numeric=True)
    assert res6["is_correct"] is False
    assert res6["score"] == 0.0

    # 7. Wrong sign for labelled question
    res7 = grader.grade_answer("v = +37.5 cm", "v = -37.5 cm", is_numeric=True)
    assert res7["is_correct"] is False
    assert res7["score"] == 0.0


