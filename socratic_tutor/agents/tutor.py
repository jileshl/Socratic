"""Tutor Agent: Emits cited Socratic hints grounded in NCERT textbook."""

from socratic_tutor import llm, config

TUTOR_PROMPT = """You are a Socratic NCERT Tutor for Class 10.
RULE 1: NEVER provide the final answer, formula substitution, or full derivation in practice mode.
RULE 2: Cite the exact NCERT section or page for every hint.
RULE 3: Use the provided textbook passage to formulate one incremental hint or analogy.
"""


def generate_hint(student_query: str, ncert_passages: list[dict], hint_level: int = 1) -> str:
    """Generate progressive Socratic hint grounded in NCERT."""
    prompt = f"Student asked: {student_query}\nHint Level: {hint_level}\nNCERT Context: {ncert_passages}\n"
    client = llm.get_llm(model=config.SPECIALIST_MODEL)
    resp = client.invoke([
        {"role": "system", "content": TUTOR_PROMPT},
        {"role": "user", "content": prompt}
    ])
    return resp.content
