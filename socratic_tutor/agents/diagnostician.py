"""Diagnostician Agent: Formulates probing questions and identifies misconceptions."""

from socratic_tutor import llm, config

DIAGNOSTICIAN_PROMPT = """You are an expert pedagogical diagnostician in NCERT Class 10 Science/Maths.
Your role is to diagnose the underlying misconception in the student's reasoning.
Do NOT give the answer.
Ask exactly ONE focused, probing question to uncover their mental model, or map their statement
to the chapter's catalogued misconceptions.
"""


def diagnose_response(query: str, chapter_misconceptions: list[dict]) -> dict:
    """Analyze student input against catalogued misconceptions."""
    prompt = f"Student input: {query}\nKnown chapter misconceptions: {chapter_misconceptions}\n"
    return llm.chat_json(prompt=prompt, system_prompt=DIAGNOSTICIAN_PROMPT)
