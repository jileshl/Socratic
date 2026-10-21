"""Grader Agent: Combines solver checking and qualitative rubric evaluation."""

from socratic_tutor import llm, config
from socratic_tutor.tools import math_tools

GRADER_PROMPT = """You are a grading evaluator for NCERT questions.
Use the rubric to assess conceptual accuracy. For numerical calculations, respect the solver output.
Provide constructive feedback and a score between 0.0 and 1.0.
"""


def grade_answer(student_text: str, gold_answer: str, is_numeric: bool = False) -> dict:
    if is_numeric:
        try:
            val = float(student_text.strip())
            gold_val = float(gold_answer.strip())
            correct = math_tools.numeric_check(val, gold_val)
            return {"is_correct": correct, "score": 1.0 if correct else 0.0, "feedback": "Numerical check completed."}
        except ValueError:
            pass

    prompt = f"Student Answer: {student_text}\nGold Answer / Rubric: {gold_answer}\n"
    return llm.chat_json(prompt=prompt, system_prompt=GRADER_PROMPT)
