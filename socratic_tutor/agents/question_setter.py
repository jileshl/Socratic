"""Question Setter Agent: Selects or drafts practice questions at appropriate difficulty."""

from socratic_tutor import llm, config

QUESTION_SETTER_PROMPT = """You are an NCERT Curriculum Question Setter.
Select or create a question matching the target concept and difficulty.
Do NOT reveal the answer in the question text.
Return JSON with {concept_id, difficulty, question_text, gold_answer}.
"""


def select_question(concept_id: str, difficulty: str = "medium") -> dict:
    prompt = f"Concept ID: {concept_id}\nDifficulty: {difficulty}\n"
    return llm.chat_json(prompt=prompt, system_prompt=QUESTION_SETTER_PROMPT)
