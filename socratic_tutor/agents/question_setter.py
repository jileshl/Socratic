"""Question Setter Agent: Selects or drafts practice questions at appropriate difficulty."""

from socratic_tutor import llm, config
from socratic_tutor.prompts import QUESTION_SETTER_PROMPT


def select_question(concept_id: str, difficulty: str = "medium") -> dict:
    prompt = f"Concept ID: {concept_id}\nDifficulty: {difficulty}\n"
    return llm.chat_json(prompt=prompt, system_prompt=QUESTION_SETTER_PROMPT)
