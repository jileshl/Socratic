"""Grader Agent: Combines solver checking and qualitative rubric evaluation."""

import re
from typing import Any
from socratic_tutor import llm, config
from socratic_tutor.prompts import GRADER_PROMPT
from socratic_tutor.tools import math_tools


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


def grade_answer(student_text: str, gold_answer: str, is_numeric: bool = False) -> dict:
    if is_numeric:
        # Numbers with units ("-30 cm", "-0.3 m") are checked by code, not by the LLM (capstone guide p.2, rule 1).
        check = math_tools.check_numeric_answer(student_text, gold_answer)
        if check["ok"]:
            correct = check["value"]
            return {"is_correct": correct, "score": 1.0 if correct else 0.0, "feedback": check["detail"]}

        # If direct check could not read the answer key or student attempt due to variable labels
        # (e.g. "v = -37.5 cm", "P = +1.5 D", "I = 2.5 A"):
        gold_candidates = extract_numeric_quantities(gold_answer)
        student_candidates = extract_numeric_quantities(student_text)
        if gold_candidates and student_candidates:
            best_check = None
            for s_cand in student_candidates:
                for g_cand in gold_candidates:
                    c = math_tools.check_numeric_answer(s_cand, g_cand)
                    if c["ok"]:
                        best_check = c
                        if c["value"]:
                            return {"is_correct": True, "score": 1.0, "feedback": c["detail"]}
            if best_check:
                return {"is_correct": False, "score": 0.0, "feedback": best_check["detail"]}
        # Only if the answer key itself cannot be read does grading fall back to the rubric below.

    prompt = f"Student Answer: {student_text}\nGold Answer / Rubric: {gold_answer}\n"
    return llm.chat_json(prompt=prompt, system_prompt=GRADER_PROMPT)

