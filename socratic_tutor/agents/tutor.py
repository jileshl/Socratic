"""Tutor Agent: Emits cited Socratic hints grounded in NCERT textbook."""

from __future__ import annotations

import re
from typing import Any
from socratic_tutor import config, llm
from socratic_tutor.prompts import TUTOR_PROMPT


def generate_hint(
    student_query: str,
    ncert_passages: list[dict[str, Any]],
    hint_level: int = 1,
    approved_lesson: str | None = None,
    remediation: str | None = None,
    misconception: dict[str, Any] | None = None,
    conversation_history: list[Any] | None = None,
) -> str:
    """Generate progressive Socratic hint grounded in NCERT."""
    passages_text = "\n\n".join(
        f"[Section {p.get('section_id', 'Unknown')}] {p.get('section_title', '')}: {p.get('content', '')[:600]}"
        for p in ncert_passages
    ) if ncert_passages else "(No textbook passages retrieved)"

    top_sec = ncert_passages[0].get("section_id", "9.2.4") if ncert_passages else "9.2.4"

    strategy_desc = {
        1: "Level 1 (Conceptual Orientation): Focus on visualizing the phenomenon and basic principles. Ask a clarifying question.",
        2: "Level 2 (Procedural / Ray-Diagram Guidance): Guide the student on what steps or rays to trace.",
    }.get(hint_level, "Level 3 (Formula Guidance): Direct the student to the textbook formula and its variables, without doing the arithmetic.")

    extra_instructions = []
    if misconception and isinstance(misconception, dict):
        miscon_name = misconception.get("name") or misconception.get("id")
        if miscon_name:
            extra_instructions.append(f"Targeted Misconception: {miscon_name}")
    if approved_lesson:
        extra_instructions.append(f"Approved Teaching Lesson for this misconception: {approved_lesson}")
    if remediation == "parallel_resistors":
        extra_instructions.append("Remediation Rule: Remediate Ohm's law (V = IR) first, then review current division, then retry parallel resistance.")
    if conversation_history:
        recent = [
            f"{'Student' if getattr(m, 'type', '') == 'human' else 'Tutor'}: {getattr(m, 'content', str(m))}"
            for m in conversation_history[-4:]
            if getattr(m, 'content', None)
        ]
        if recent:
            extra_instructions.append("Recent Dialogue Context:\n" + "\n".join(recent))

    user_prompt = (
        f"Student Query: {student_query}\n"
        f"Hint Level: {hint_level} - {strategy_desc}\n"
        + ("\n".join(extra_instructions) + "\n" if extra_instructions else "")
        + f"\nRetrieved NCERT Context:\n{passages_text}\n\n"
        "Draft exactly ONE concise, encouraging Socratic hint that cites the NCERT section ID. "
        "If the student has already correctly and sufficiently explained the concept or relationship, "
        "confirm it warmly, restate in one sentence what they said with the NCERT citation (adding no new facts or numbers), "
        "and invite them to take the quiz or try the next topic instead of asking another probing question."
    )

    try:
        client = llm.get_llm(model=config.SPECIALIST_MODEL, temperature=0.3)
        resp = client.invoke([
            {"role": "system", "content": TUTOR_PROMPT},
            {"role": "user", "content": user_prompt}
        ])
        content = str(resp.content)
    except Exception:
        # Graceful fallback when offline or in sandboxed tests
        if "10." in str(top_sec):
            content = (
                f"Think about the optical and scattering phenomena described in NCERT Section {top_sec}. "
                f"How do particles interact with different wavelengths of light?"
            )
        elif "11." in str(top_sec):
            content = (
                f"Think about the circuit relationships described in NCERT Section {top_sec}. "
                f"How do voltage, current, and resistance relate in this setup?"
            )
        else:
            content = (
                f"Think about the reflection rules described in NCERT Section {top_sec}. "
                f"Where do the rays meet after reflecting from the surface?"
            )

    # Ensure a section citation is present if passages exist
    if not re.search(r"\b(9|10|11)\.\d+", content):
        content += f" (Refer to NCERT Section {top_sec})"
    return content
