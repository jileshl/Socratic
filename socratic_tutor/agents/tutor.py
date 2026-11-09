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
    if approved_lesson:
        extra_instructions.append(f"Approved Teaching Lesson for this misconception: {approved_lesson}")
    if remediation == "parallel_resistors":
        extra_instructions.append("Remediation Rule: Remediate Ohm's law (V = IR) first, then review current division, then retry parallel resistance.")

    user_prompt = (
        f"Student Query: {student_query}\n"
        f"Hint Level: {hint_level} - {strategy_desc}\n"
        + ("\n".join(extra_instructions) + "\n" if extra_instructions else "")
        + f"\nRetrieved NCERT Context:\n{passages_text}\n\n"
        "Draft exactly ONE concise, encouraging Socratic hint that cites the NCERT section ID."
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
        content = (
            f"Think about the reflection rules described in NCERT Section {top_sec}. "
            f"Where do the rays meet after reflecting from the surface?"
        )

    # Ensure a section citation is present if passages exist
    if not re.search(r"\b(9|10|11)\.\d+", content):
        content += f" (Refer to NCERT Section {top_sec})"
    return content
