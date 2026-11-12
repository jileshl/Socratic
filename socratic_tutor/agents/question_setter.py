"""Question Setter Agent: Selects or drafts practice questions at appropriate difficulty."""

from __future__ import annotations

from typing import Any
from socratic_tutor import llm, config, solver_key
from socratic_tutor.prompts import QUESTION_SETTER_PROMPT

CONCEPT_FALLBACK_QUESTIONS: dict[str, dict[str, Any]] = {
    "concept_reflection_laws": {
        "question_text": "State the laws of reflection of light.",
        "gold_answer": "1. The angle of incidence is equal to the angle of reflection. 2. The incident ray, normal to the mirror at the point of incidence, and reflected ray all lie in the same plane.",
        "difficulty": "easy",
    },
    "concept_concave_mirror": {
        "question_text": "An object is placed 20 cm in front of a concave mirror of focal length 15 cm. Find the distance of the image from the mirror.",
        "gold_answer": "-60 cm",
        "difficulty": "medium",
        "calculation": {"formula": "mirror_formula", "u": -20, "f": -15, "length_unit": "cm", "find": "v"},
    },
    "concept_mirror_formula": {
        "question_text": "An object is placed 30 cm in front of a concave mirror of focal length 20 cm. Find the image distance using the mirror formula.",
        "gold_answer": "-60 cm",
        "difficulty": "medium",
        "calculation": {"formula": "mirror_formula", "u": -30, "f": -20, "length_unit": "cm", "find": "v"},
    },
    "concept_refraction_laws": {
        "question_text": "State Snell's law of refraction.",
        "gold_answer": "The ratio of sine of angle of incidence to the sine of angle of refraction is a constant (sin i / sin r = constant) for a given pair of media.",
        "difficulty": "easy",
    },
    "concept_lens_formula": {
        "question_text": "A convex lens of focal length 20 cm produces an image of an object placed 30 cm in front of it. Find the image distance.",
        "gold_answer": "60 cm",
        "difficulty": "medium",
        "calculation": {"formula": "lens_formula", "u": -30, "f": 20, "length_unit": "cm", "find": "v"},
    },
    "concept_ohms_law": [
        {
            "question_text": "A potential difference of 12 V is applied across a 4 ohm resistor. Find the current flowing through it.",
            "gold_answer": "3 A",
            "difficulty": "easy",
            "calculation": {"formula": "ohms_law", "v": 12, "r": 4, "find": "i"},
        },
        {
            "question_text": "A potential difference of 24 V is applied across a conductor carrying a current of 6 A. Find its resistance.",
            "gold_answer": "4 ohm",
            "difficulty": "medium",
            "calculation": {"formula": "ohms_law", "v": 24, "i": 6, "find": "r"},
        },
        {
            "question_text": "A current of 0.5 A flows through a 100 ohm resistor. Find the potential difference across it.",
            "gold_answer": "50 V",
            "difficulty": "hard",
            "calculation": {"formula": "ohms_law", "i": 0.5, "r": 100, "find": "v"},
        },
    ],
    "concept_resistors_parallel": [
        {
            "question_text": "Two resistors of 6 ohm and 3 ohm are connected in parallel across a 6 V battery. Calculate the effective resistance.",
            "gold_answer": "2 ohm",
            "difficulty": "easy",
            "calculation": {"formula": "parallel_resistance", "resistors": [6, 3]},
        },
        {
            "question_text": "Two resistors of 6 ohm and 3 ohm are connected in parallel across a 6 V battery. Calculate the current in the 3 ohm resistor.",
            "gold_answer": "2 A",
            "difficulty": "medium",
            "calculation": {"formula": "ohms_law", "v": 6, "r": 3, "find": "i"},
        },
    ],
    "concept_parallel_combination": [
        {
            "question_text": "Two resistors of 6 ohm and 3 ohm are connected in parallel across a 6 V battery. Calculate the effective resistance.",
            "gold_answer": "2 ohm",
            "difficulty": "easy",
            "calculation": {"formula": "parallel_resistance", "resistors": [6, 3]},
        },
        {
            "question_text": "Two resistors of 6 ohm and 3 ohm are connected in parallel across a 6 V battery. Calculate the current in the 3 ohm resistor.",
            "gold_answer": "2 A",
            "difficulty": "medium",
            "calculation": {"formula": "ohms_law", "v": 6, "r": 3, "find": "i"},
        },
    ],
    "concept_joule_heating": {
        "question_text": "A 20 ohm resistor carries a current of 5 A for 30 seconds. Calculate the heat produced in joules.",
        "gold_answer": "15000 J",
        "difficulty": "medium",
        "calculation": {"formula": "joule_heating", "r": 20, "i": 5, "t": 30, "find": "h"},
    },
    "concept_joules_heating": {
        "question_text": "A 20 ohm resistor carries a current of 5 A for 30 seconds. Calculate the heat produced in joules.",
        "gold_answer": "15000 J",
        "difficulty": "medium",
        "calculation": {"formula": "joule_heating", "r": 20, "i": 5, "t": 30, "find": "h"},
    },
    "concept_series_combination": {
        "question_text": "Two resistors of 4 ohm and 6 ohm are connected in series across a 12 V battery. Calculate the equivalent resistance.",
        "gold_answer": "10 ohm",
        "difficulty": "easy",
        "calculation": {"formula": "series_resistance", "resistors": [4, 6]},
    },
    "concept_lens_power": {
        "question_text": "A convex lens has a focal length of 0.5 m. Find its power.",
        "gold_answer": "2 D",
        "difficulty": "easy",
        "calculation": {"formula": "lens_power", "f": 0.5, "length_unit": "m", "find": "p"},
    },
}


def get_existing_questions(concept_id: str, limit: int = 15) -> list[str]:
    """Retrieve existing question prompts from the bank for this concept to avoid generating duplicates."""
    try:
        import sqlite3
        from socratic_tutor.tools import question_bank
        conn = sqlite3.connect(question_bank.DB_PATH)
        rows = conn.execute(
            "SELECT prompt FROM questions WHERE concept_id = ? ORDER BY id DESC LIMIT ?",
            (concept_id, limit),
        ).fetchall()
        conn.close()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def select_question(
    concept_id: str,
    difficulty: str = "medium",
    existing_questions: list[str] | None = None,
) -> dict[str, Any]:
    prompt = f"Concept ID: {concept_id}\nDifficulty: {difficulty}\n"

    existing: list[str] = list(existing_questions or [])
    for bq in get_existing_questions(concept_id):
        if bq not in existing:
            existing.append(bq)

    if existing:
        prompt += (
            "\nThe following questions ALREADY exist in the bank. You MUST create a different question "
            "with DIFFERENT numerical values, scenario, or asking for a different quantity (do NOT duplicate or rephrase these):\n"
        )
        for ex in existing[:10]:
            prompt += f"- {ex}\n"

    # PR-2 (R4): the solver's formula list, so the model names a formula and its inputs exactly as code expects.
    prompt = prompt + "\nFormulas you may use:\n" + solver_key.formula_list_for_the_model()
    res = llm.chat_json(prompt=prompt, system_prompt=QUESTION_SETTER_PROMPT, temperature=0.7)
    # PR-2 (R4): a usable reply has a question and a calculation. The model no longer writes the answer key
    # (the solver computes it from the calculation), so a reply is not dropped for having no gold_answer.
    if isinstance(res, dict) and res.get("question_text") and res.get("calculation") and "error" not in res:
        res.setdefault("concept_id", concept_id)
        res.setdefault("difficulty", difficulty)
        return res

    fallback_entry = CONCEPT_FALLBACK_QUESTIONS.get(concept_id)
    if not fallback_entry:
        return {"error": f"No question generated or fallback available for concept '{concept_id}'"}

    if isinstance(fallback_entry, list):
        matching = [q for q in fallback_entry if q.get("difficulty") == difficulty]
        fallback = matching[0] if matching else fallback_entry[0]
    else:
        fallback = fallback_entry

    result = {
        "concept_id": concept_id,
        "difficulty": fallback.get("difficulty", difficulty),
        "question_text": fallback["question_text"],
        "gold_answer": fallback["gold_answer"],
        # PR-2 (R4): marks a fixed fallback question, so the teacher view can say the model gave none.
        "source": "fallback",
    }
    if "calculation" in fallback:
        result["calculation"] = fallback["calculation"]
    return result

