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
import re
from socratic_tutor import llm, config, tool_hooks
from socratic_tutor.prompts import GRADER_PROMPT
from socratic_tutor.tools import math_tools

# The only two sentences a student is ever shown by the grader. Neither depends on the answer key.
CORRECT_FEEDBACK: str = "Correct! Well done."
WRONG_FEEDBACK: str = "Not quite right. Let's review the concept."
# When R4's tool hooks block the grader's check (budget used up, tools paused, session facts missing), the answer
# was not checked at all, so the student is told that, never "right" or "wrong".
CANNOT_CHECK_FEEDBACK: str = "I can't check this answer right now. Please try again in a moment."


def extract_numeric_quantities(text: str) -> list[str]:
    """Extract numeric quantity candidates from labelled or multi-part text."""
    if not text:
        return []

    tidy = math_tools.tidy_answer_text(text)
    if math_tools.read_quantity(tidy)["ok"]:
        return [tidy]

    results = []
    # Split by clause separators
    clauses = re.split(r"[;,()\n]", text)
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        tidy_c = math_tools.tidy_answer_text(clause)
        if math_tools.read_quantity(tidy_c)["ok"]:
            results.append(tidy_c)
            continue

        # Strip variable labels: e.g. "v =", "P =", "I =", "h' =", "Equivalent resistance ="
        stripped = re.sub(r"^[a-zA-Z\s_\'\"’]+\s*=\s*", "", clause).strip()
        if stripped:
            tidy_s = math_tools.tidy_answer_text(stripped)
            if math_tools.read_quantity(tidy_s)["ok"]:
                results.append(tidy_s)
                continue

        # Handle chained equations e.g. "I = Q/t = 300/120 = 2.5 A"
        if "=" in clause:
            last_part = clause.split("=")[-1].strip()
            tidy_last = math_tools.tidy_answer_text(last_part)
            if math_tools.read_quantity(tidy_last)["ok"]:
                results.append(tidy_last)
                continue

    return results


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


def check_numeric_answer(student_text: str, gold_text: str) -> dict[str, Any]:
    """The grader's numeric check, under the name R4's permission map knows ("check_numeric_answer").

    It calls math_tools.check_numeric_answer at call time, so a test that swaps that function still works.
    """
    return math_tools.check_numeric_answer(student_text, gold_text)


def run_check(student_text: str, gold_text: str, state: dict[str, Any] | None) -> dict[str, Any]:
    """[H] One numeric check for the grader: through R4's tool hooks when the graph's state is given.

    Returns the check's own result, or {"ok": False, "blocked": True, "error": "BLOCKED: <reason>"} when the
    hook blocked it. Without a state (the eval harness and older callers), the check runs directly, as before.
    """
    # Flowchart (each [box] matches a comment below):
    #
    #   [H1] no graph state? -> run the check directly (as before)
    #   [H2] through the hook, as the agent "grader" (permission, quiz rule, budget, kill switch, log)
    #   [H3] blocked? -> a "blocked" result; the grader then fails closed (never the LLM)

    # The check's two inputs, by name, as the hook logs them.
    arguments: dict[str, Any] = {"student_text": student_text, "gold_text": gold_text}
    # [H1] No graph state: the direct call.
    if state is None:
        return check_numeric_answer(student_text, gold_text)
    # [H2] Through the hook.
    result: Any = tool_hooks.run_tool("grader", check_numeric_answer, arguments, state)
    # [H3] A blocked call returns "BLOCKED: <reason>" instead of a dict.
    if tool_hooks.is_blocked(result):
        return {"ok": False, "blocked": True, "error": str(result)}
    return result


def blocked_grade(check: dict[str, Any]) -> dict[str, Any]:
    """The grade when the hook blocked a check: not right, score 0, and an "error" so it isn't recorded."""
    return for_the_student({"is_correct": False, "score": 0.0, "feedback": "", "error": "tool_blocked: " + str(check["error"])})


def grade_answer(student_text: str, gold_answer: str, is_numeric: bool = False,
                 state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Grade one answer against the key. The result's "feedback" is always safe to show the student."""
    # [G1] only a numeric question can be checked by code.
    if is_numeric:
        # [G2] Numbers with units ("-30 cm", "-0.3 m") are checked by code, not by the LLM
        # (capstone guide p.2, rule 1).
        check = run_check(student_text, gold_answer, state)
        # The hook blocked the check: fail closed (no grade, and never the LLM rubric instead).
        if check.get("blocked"):
            return blocked_grade(check)
        if check["ok"]:
            correct = check["value"]
            return for_the_student(
                {"is_correct": correct, "score": 1.0 if correct else 0.0, "feedback": check["detail"]}
            )

        # If direct check could not read the answer key or student attempt due to variable labels
        # (e.g. "v = -37.5 cm", "P = +1.5 D", "I = 2.5 A"):
        gold_candidates = extract_numeric_quantities(gold_answer)
        student_candidates = extract_numeric_quantities(student_text)
        if gold_candidates and student_candidates:
            best_check = None
            for s_cand in student_candidates:
                for g_cand in gold_candidates:
                    c = run_check(s_cand, g_cand, state)
                    # The hook blocked a check: fail closed, as above.
                    if c.get("blocked"):
                        return blocked_grade(c)
                    if c["ok"]:
                        best_check = c
                        if c["value"]:
                            return for_the_student({"is_correct": True, "score": 1.0, "feedback": c["detail"]})
            if best_check:
                return for_the_student({"is_correct": False, "score": 0.0, "feedback": best_check["detail"]})
        # Only if the answer key itself cannot be read does grading fall back to the rubric below.

    # [G3] the LLM grades against the rubric. It sees the key, so its feedback goes to "detail" like the checker's.
    prompt = f"Student Answer: {student_text}\nGold Answer / Rubric: {gold_answer}\n"
    return for_the_student(llm.chat_json(prompt=prompt, system_prompt=GRADER_PROMPT))
