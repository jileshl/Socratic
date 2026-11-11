"""Tests for the grader: the numeric check in code, the LLM fallback, and what the student is shown.

The student is shown only grader.CORRECT_FEEDBACK or grader.WRONG_FEEDBACK. The checker's or the LLM's own text
is worked out from the answer key, so it is kept in "detail" instead (grader.py's flowchart, boxes [F1]-[F4]).
No test calls a model: an autouse fixture makes every LLM call fail, and the LLM tests put a fake in its place.
"""

from typing import Any, Callable

import pytest

from socratic_tutor.agents import grader

# Phrases from math_tools.check_numeric_answer's detail texts. Each one is worked out from the key.
CHECKER_PHRASES: list[str] = [
    "Matches", "Off by", "Wrong sign", "Wrong kind of unit", "The key is", "unit is missing", "%",
]

# Wrong answers against a key, and the phrase the checker's detail should contain: (answer, key, phrase).
WRONG_ANSWERS: list[tuple[str, str, str]] = [
    ("-20 cm", "-30 cm", "Off by 33.3%"),
    ("30 cm", "-30 cm", "Wrong sign: the key is negative"),
    ("-30 s", "-30 cm", "the key is a length (cm)"),
    ("-20", "-30 cm", "The unit is missing: write it (cm)"),
    ("5 cm", "0 cm", "The key is 0"),
]

# LLM replies that are not a clear "correct": each one must fail closed.
UNUSABLE_LLM_REPLIES: list[Any] = [
    {},
    {"is_correct": "yes", "score": 1.0, "feedback": "Yes, it is -30 cm."},
    {"is_correct": 1, "score": 1.0, "feedback": "Right, -30 cm."},
    {"is_correct": None, "feedback": "The key is -30 cm."},
    {"score": 0.9, "feedback": "Nearly: the key is -30 cm."},
    {"error": "Failed to parse JSON: Expecting value", "raw": "The answer is -30 cm."},
    ["correct", "-30 cm"],
    "correct",
    1,
    None,
]


def no_llm(prompt: str, system_prompt: str, **kwargs: Any) -> dict[str, Any]:
    """Stands in for llm.chat_json in every test, so no test can reach a real model."""
    raise AssertionError("The grader called the LLM. Numeric cases are decided in code; LLM tests must use fake_llm.")


@pytest.fixture(autouse=True)
def _block_the_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """No live model calls in this file: replace llm.chat_json before every test."""
    monkeypatch.setattr(grader.llm, "chat_json", no_llm)


def test_the_llm_is_asked_for_is_correct(monkeypatch: pytest.MonkeyPatch) -> None:
    """[G3] The system prompt names all three keys. Without "is_correct", [F2] would mark every LLM-graded answer wrong."""
    system_prompts_seen: list[str] = []

    def chat_json(prompt: str, system_prompt: str, **kwargs: Any) -> dict[str, Any]:
        # Record the system prompt that the LLM path really sends.
        system_prompts_seen.append(system_prompt)
        return {"feedback": "Matches the rubric.", "is_correct": True, "score": 1.0}

    monkeypatch.setattr(grader.llm, "chat_json", chat_json)
    result: dict[str, Any] = grader.grade_answer("Real and inverted.", "Real and inverted.")
    # The LLM path ran once, with the grader's own system prompt.
    assert len(system_prompts_seen) == 1
    # Each key is named in quotes, as the JSON reply must spell it.
    for key in ('"feedback"', '"is_correct"', '"score"'):
        assert key in system_prompts_seen[0], "The grader prompt doesn't ask for " + key
    # A reply in that shape is read as correct.
    assert result["is_correct"] is True
    assert result["feedback"] == grader.CORRECT_FEEDBACK


def fake_llm(reply: Any, prompts_seen: list[str]) -> Callable[..., Any]:
    """A stand-in for llm.chat_json that returns `reply`, and records each prompt in `prompts_seen`."""
    def chat_json(prompt: str, system_prompt: str, **kwargs: Any) -> Any:
        # Record the prompt, so the test can check that the LLM path really ran.
        prompts_seen.append(prompt)
        return reply
    return chat_json


def assert_safe_for_the_student(feedback: str) -> None:
    """The student's text is one of the two fixed sentences, with no number and no checker phrase in it."""
    # Exactly one of the two fixed sentences, so nothing from the grader's own text gets in.
    assert feedback in (grader.CORRECT_FEEDBACK, grader.WRONG_FEEDBACK), "Not a fixed sentence: " + feedback
    # No digit at all: a number in the student's text could be the key, or a step towards it.
    for character in feedback:
        assert not character.isdigit(), "A number reached the student: " + feedback
    # No phrase that the checker builds from the key.
    for phrase in CHECKER_PHRASES:
        assert phrase not in feedback, "The checker's text reached the student: " + feedback


def test_grader_marks_a_numeric_answer_with_units_in_code() -> None:
    """"-30cm" against the key "-30 cm" is correct. Before, float("-30cm") failed and the LLM graded it."""
    result = grader.grade_answer("-30cm", "-30 cm", is_numeric=True)
    assert result["is_correct"] is True
    assert result["score"] == 1.0
    # The checker's text is kept for the logs; the student gets the fixed praise.
    assert "Matches" in result["detail"]
    assert result["feedback"] == grader.CORRECT_FEEDBACK


def test_grader_explains_a_wrong_sign() -> None:
    """"30 cm" against "-30 cm" is wrong. "detail" says why; the student isn't told, because that names the key."""
    result = grader.grade_answer("30 cm", "-30 cm", is_numeric=True)
    assert result["is_correct"] is False
    assert result["score"] == 0.0
    assert "Wrong sign" in result["detail"]
    assert result["feedback"] == grader.WRONG_FEEDBACK


@pytest.mark.parametrize(("answer", "key", "phrase"), WRONG_ANSWERS)
def test_a_wrong_numeric_answer_does_not_give_the_key_away(answer: str, key: str, phrase: str) -> None:
    """[G2] -> [F] A wrong answer: the student sees the fixed sentence; "detail" keeps the checker's text."""
    result: dict[str, Any] = grader.grade_answer(answer, key, is_numeric=True)
    assert result["is_correct"] is False
    assert result["feedback"] == grader.WRONG_FEEDBACK
    # E.g. after "-20 cm", "Off by 33.3%" would leave only -30 cm or -15 cm as the key.
    assert_safe_for_the_student(result["feedback"])
    assert phrase in result["detail"], "The checker's text should be kept in detail: " + result["detail"]


def test_the_llm_feedback_goes_to_detail_not_to_the_student(monkeypatch: pytest.MonkeyPatch) -> None:
    """[G3] -> [F] The LLM sees the key and may state it in its feedback; the student gets the fixed sentence."""
    prompts_seen: list[str] = []
    llm_text: str = "Close, but the image is at -30 cm, not -20 cm."
    reply: dict[str, Any] = {"is_correct": False, "score": 0.3, "feedback": llm_text}
    monkeypatch.setattr(grader.llm, "chat_json", fake_llm(reply, prompts_seen))
    result: dict[str, Any] = grader.grade_answer("The image is at -20 cm.", "Real and inverted, at -30 cm.")
    # The LLM path ran once, and the key was in its prompt: that is why its text can state the key.
    assert len(prompts_seen) == 1
    assert "-30 cm" in prompts_seen[0]
    assert result["is_correct"] is False
    assert result["feedback"] == grader.WRONG_FEEDBACK
    assert_safe_for_the_student(result["feedback"])
    # The LLM's text and its score are kept for the logs and the teacher.
    assert result["detail"] == llm_text
    assert result["score"] == 0.3


def test_an_llm_that_says_correct_gets_only_the_fixed_praise(monkeypatch: pytest.MonkeyPatch) -> None:
    """[F2] is_correct True from the LLM: the student gets "Correct! Well done.", not the LLM's own text."""
    prompts_seen: list[str] = []
    llm_text: str = "Yes: real, inverted, at -30 cm."
    reply: dict[str, Any] = {"is_correct": True, "score": 1.0, "feedback": llm_text}
    monkeypatch.setattr(grader.llm, "chat_json", fake_llm(reply, prompts_seen))
    result: dict[str, Any] = grader.grade_answer("Real and inverted, at -30 cm.", "Real and inverted, at -30 cm.")
    assert len(prompts_seen) == 1
    assert result["is_correct"] is True
    assert result["feedback"] == grader.CORRECT_FEEDBACK
    assert result["detail"] == llm_text


@pytest.mark.parametrize("reply", UNUSABLE_LLM_REPLIES)
def test_an_unusable_llm_result_fails_closed(monkeypatch: pytest.MonkeyPatch, reply: Any) -> None:
    """[F1]-[F2] Not a dict, or is_correct not exactly True: not correct, and the student gets the fixed sentence."""
    prompts_seen: list[str] = []
    monkeypatch.setattr(grader.llm, "chat_json", fake_llm(reply, prompts_seen))
    result: dict[str, Any] = grader.grade_answer("-30 cm", "Real and inverted, at -30 cm.")
    assert len(prompts_seen) == 1
    # Plain False, so the logs, the learner record and the eval agree with what the student was told.
    assert result["is_correct"] is False
    assert result["feedback"] == grader.WRONG_FEEDBACK
    assert_safe_for_the_student(result["feedback"])


@pytest.mark.parametrize("reply", [["correct"], "correct", 1, None])
def test_a_non_dict_llm_result_is_a_grader_error(monkeypatch: pytest.MonkeyPatch, reply: Any) -> None:
    """[F1] A reply that isn't a dict is marked "error", so callers treat it as a grader failure, not a wrong answer."""
    monkeypatch.setattr(grader.llm, "chat_json", fake_llm(reply, []))
    result: dict[str, Any] = grader.grade_answer("-30 cm", "Real and inverted, at -30 cm.")
    assert "error" in result
    # The reply is kept for the logs.
    assert result["raw"] == reply


def test_a_json_error_from_the_llm_stays_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat_json's own error dict keeps its "error", so a broken reply isn't counted as the student's mistake."""
    reply: dict[str, Any] = {"error": "Failed to parse JSON: Expecting value", "raw": "The answer is -30 cm."}
    monkeypatch.setattr(grader.llm, "chat_json", fake_llm(reply, []))
    result: dict[str, Any] = grader.grade_answer("-30 cm", "Real and inverted, at -30 cm.")
    assert result["error"] == reply["error"]
    assert result["detail"] == ""
    assert result["feedback"] == grader.WRONG_FEEDBACK


def test_the_two_sentences_are_the_ones_the_graph_already_shows() -> None:
    """The fixed sentences are the graph's own fallback texts, so what the student reads doesn't change."""
    assert grader.CORRECT_FEEDBACK == "Correct! Well done."
    assert grader.WRONG_FEEDBACK == "Not quite right. Let's review the concept."


@pytest.mark.parametrize(("answer", "key"), [("-30 cm", "-30 cm"), ("-0.3 m", "-30 cm")])
def test_a_correct_numeric_answer_gets_the_fixed_praise(answer: str, key: str) -> None:
    """[F4] A correct answer, in the key's unit or another one, gets "Correct! Well done."."""
    result: dict[str, Any] = grader.grade_answer(answer, key, is_numeric=True)
    assert result["is_correct"] is True
    assert result["score"] == 1.0
    assert result["feedback"] == grader.CORRECT_FEEDBACK
    assert "Matches" in result["detail"]


def test_a_missing_unit_is_noted_only_in_detail() -> None:
    """"-30" against "-30 cm" counts as correct. The checker's "unit is missing" note stays in "detail"."""
    result: dict[str, Any] = grader.grade_answer("-30", "-30 cm", is_numeric=True)
    assert result["is_correct"] is True
    assert result["feedback"] == grader.CORRECT_FEEDBACK
    assert "The unit is missing: write it (cm)" in result["detail"]
