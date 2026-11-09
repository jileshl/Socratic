"""Grader Agent: Combines solver checking and qualitative rubric evaluation."""

from socratic_tutor import llm, config
from socratic_tutor.prompts import GRADER_PROMPT
from socratic_tutor.tools import math_tools


def grade_answer(student_text: str, gold_answer: str, is_numeric: bool = False) -> dict:
    if is_numeric:
        # Numbers with units ("-30 cm", "-0.3 m") are checked by code, not by the LLM (capstone guide p.2, rule 1).
        check = math_tools.check_numeric_answer(student_text, gold_answer)
        if check["ok"]:
            correct = check["value"]
            return {"is_correct": correct, "score": 1.0 if correct else 0.0, "feedback": check["detail"]}
        # Only if the answer key itself cannot be read does grading fall back to the rubric below.

    prompt = f"Student Answer: {student_text}\nGold Answer / Rubric: {gold_answer}\n"
    return llm.chat_json(prompt=prompt, system_prompt=GRADER_PROMPT)
