"""Grader Agent: Combines solver checking and qualitative rubric evaluation.

The student is shown only one of two fixed sentences, never the grader's own text. The checker's text is worked
out from the answer key ("Off by 33.3% (allowed: 2.0%).", "Wrong sign: the key is negative, ..."), so in a quiz
it gives the key away: after an answer of -20 cm, "Off by 33.3%" leaves only -30 cm or -15 cm. The LLM fallback
sees the key too, so its feedback is handled the same way. Both texts are kept under "detail", for the logs and
the teacher. The rule is the same in every mode: the grader doesn't know the mode, and the tutor gives the hints.

Flowchart (each [box] matches a comment in the code):

    grade_answer
      [G1] a numeric question?                               no  -> [G3]
      [G2] can code read the key? (check_numeric_answer)     yes -> [F] with the checker's result
                                                             no  -> [G3]
      [G3] the LLM grades against the rubric                 -> [F] with the LLM's result

    for_the_student  [F]
      [F1] not a dict?                    -> an empty result, marked as a grader error
      [F2] correct only if is_correct is exactly True       (anything else fails closed)
      [F3] the grader's own text          -> "detail"       (logs and teacher only)
      [F4] the student's "feedback"       -> CORRECT_FEEDBACK or WRONG_FEEDBACK
"""

from typing import Any

from socratic_tutor import llm, config
from socratic_tutor.tools import math_tools

GRADER_PROMPT = """You are a grading evaluator for NCERT questions.
Use the rubric to assess conceptual accuracy. For numerical calculations, respect the solver output.
Provide constructive feedback and a score between 0.0 and 1.0.
"""

# The only two sentences a student is ever shown by the grader. Neither depends on the answer key.
CORRECT_FEEDBACK: str = "Correct! Well done."
WRONG_FEEDBACK: str = "Not quite right. Let's review the concept."


def for_the_student(result: Any) -> dict[str, Any]:
    """[F1]-[F4] Make a grading result safe to show: a fixed "feedback", and the grader's own text in "detail".

    Args:
        result: what the checker or the LLM returned. Its "feedback" is the grader's own text, which may state
            the answer key.

    Returns:
        A copy of the result in which "is_correct" is True or False, "feedback" is CORRECT_FEEDBACK or
        WRONG_FEEDBACK, and "detail" is the grader's own text ("" if it had none). Other keys, such as "score"
        and "error", are kept as they were.
    """
    # [F1] chat_json can return any JSON value (a list, a string, a number), and only a dict is a grading result.
    if not isinstance(result, dict):
        # Mark it as an error, so callers handle it as "the grader failed", not as the student's wrong answer.
        safe: dict[str, Any] = {"error": "The grader did not return a JSON object.", "raw": result}
    else:
        # Work on a copy, so the caller's dict is never changed.
        safe = dict(result)
    # [F2] only the value True counts as correct: "yes", 1, None or a missing key all fail closed.
    correct: bool = safe.get("is_correct") is True
    # Store the plain True or False, so everything downstream agrees with the sentence the student sees.
    safe["is_correct"] = correct
    # [F3] the grader's own text moves to "detail", for the logs and the teacher.
    own_text: Any = safe.get("feedback")
    if own_text is None:
        # No text at all, for example after a JSON error.
        safe["detail"] = ""
    else:
        # str() also covers an LLM that returned its feedback as a list or a number.
        safe["detail"] = str(own_text)
    # [F4] the student sees a fixed sentence that says only "right" or "not right".
    if correct:
        safe["feedback"] = CORRECT_FEEDBACK
    else:
        safe["feedback"] = WRONG_FEEDBACK
    return safe


def grade_answer(student_text: str, gold_answer: str, is_numeric: bool = False) -> dict[str, Any]:
    """Grade one answer against the key. The result's "feedback" is always safe to show the student."""
    # [G1] only a numeric question can be checked by code.
    if is_numeric:
        # [G2] Numbers with units ("-30 cm", "-0.3 m") are checked by code, not by the LLM
        # (capstone guide p.2, rule 1).
        check = math_tools.check_numeric_answer(student_text, gold_answer)
        if check["ok"]:
            correct = check["value"]
            return for_the_student(
                {"is_correct": correct, "score": 1.0 if correct else 0.0, "feedback": check["detail"]}
            )
        # Only if the answer key itself cannot be read does grading fall back to the rubric below.

    # [G3] the LLM grades against the rubric. It sees the key, so its feedback goes to "detail" like the checker's.
    prompt = f"Student Answer: {student_text}\nGold Answer / Rubric: {gold_answer}\n"
    return for_the_student(llm.chat_json(prompt=prompt, system_prompt=GRADER_PROMPT))
