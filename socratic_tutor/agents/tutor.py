"""Tutor Agent: Emits cited Socratic hints grounded in NCERT textbook."""

from __future__ import annotations

import re
from typing import Any
from socratic_tutor import config, llm
from socratic_tutor.prompts import TUTOR_PROMPT


def _instructions(
    hint_level: int,
    approved_lesson: str | None,
    remediation: str | None,
    misconception: dict[str, Any] | None,
    conversation_history: list[Any] | None,
    learner_context: str | None,
) -> tuple[str, list[str]]:
    """The hint level's strategy and the extra instructions, shared by both ways of writing a hint."""
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
    if learner_context:
        # Signature challenge A: the learner record changes what the tutor does (team review, 13 Nov: it didn't).
        extra_instructions.append(
            "What the learner record says about this student (pseudonymous; use it, don't mention it): " + learner_context
            + "\nBuild on what they have mastered, don't re-teach it from zero, and if they showed this mix-up before, "
            "address it head-on with a different explanation from last time."
        )
    if conversation_history:
        recent = [
            f"{'Student' if getattr(m, 'type', '') == 'human' else 'Tutor'}: {getattr(m, 'content', str(m))}"
            for m in conversation_history[-4:]
            if getattr(m, 'content', None)
        ]
        if recent:
            extra_instructions.append("Recent Dialogue Context:\n" + "\n".join(recent))
    return strategy_desc, extra_instructions


def generate_hint(
    student_query: str,
    ncert_passages: list[dict[str, Any]],
    hint_level: int = 1,
    approved_lesson: str | None = None,
    remediation: str | None = None,
    misconception: dict[str, Any] | None = None,
    conversation_history: list[Any] | None = None,
    learner_context: str | None = None,
) -> str:
    """Generate progressive Socratic hint grounded in NCERT."""
    passages_text = "\n\n".join(
        f"[Section {p.get('section_id', 'Unknown')}] {p.get('section_title', '')}: {p.get('content', '')[:600]}"
        for p in ncert_passages
    ) if ncert_passages else "(No textbook passages retrieved)"

    top_sec = ncert_passages[0].get("section_id", "9.2.4") if ncert_passages else "9.2.4"
    strategy_desc, extra_instructions = _instructions(hint_level, approved_lesson, remediation, misconception,
                                                      conversation_history, learner_context)

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


# ---------------------------------------------------------------------------
# The tutor as a ReAct agent over its own MCP tools (capstone guide L10/L11: "use ReAct within the specialists";
# "each with its own tools"). Team review, 13 Nov: until now the graph searched the book for the tutor and the
# model only wrote the reply. Now the model decides what to look up (search, then perhaps read a whole section
# or an exemplar), each call goes through R4's tool hooks and the textbook-kb MCP server, and it stops when it
# has what it needs. The answer-leak check and the reply check still read the final reply afterwards.
# ---------------------------------------------------------------------------

REACT_INSTRUCTIONS = (
    "\n\nYou have three read-only tools over the NCERT textbook: search_textbook, get_section and get_exemplar. "
    "Before you reply, look up what you need: usually one search; read a whole section only if the excerpt is not "
    "enough. At most three tool calls. Then write the reply, citing a section you actually retrieved, in the form "
    "[NCERT Sec 9.2.4]. Never solve the problem or state the final answer."
)
MAX_REACT_STEPS = 8  # model and tool steps together: about three tool calls, then the reply


def react_available() -> bool:
    """A real model is configured (not the offline stub the tests and stub runs use) and the switch is on."""
    return bool(config.TUTOR_REACT and (config.OPENROUTER_API_KEY or config.OPENAI_API_KEY) and not config.EVAL_STUB)


def react_hint(
    student_query: str,
    chapter: str | None,
    tool_runner: Any,
    hint_level: int = 1,
    approved_lesson: str | None = None,
    remediation: str | None = None,
    misconception: dict[str, Any] | None = None,
    conversation_history: list[Any] | None = None,
    learner_context: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Write the hint as a ReAct agent. tool_runner(name, arguments) runs one textbook tool (through the hooks and
    MCP) and returns its result, or a "BLOCKED: ..." string. Returns (reply, the passages the agent retrieved)."""
    from langchain_core.tools import StructuredTool
    from langgraph.prebuilt import create_react_agent

    found: list[dict[str, Any]] = []

    def _keep(passages: list[dict[str, Any]]) -> None:
        for p in passages:
            if p.get("section_id") and all(f.get("section_id") != p["section_id"] for f in found):
                found.append(p)

    def search_textbook(query: str, chapter_num: str | None = None) -> Any:
        """Search the NCERT Class 10 Science textbook. Returns the best-matching sections with short excerpts and
        their section ids. chapter_num: "9" (Light), "10" (Human eye) or "11" (Electricity), or leave it out."""
        result = tool_runner("search_textbook", {"query": query, "chapter": chapter_num or chapter, "top_k": 4})
        if isinstance(result, list):
            _keep(result)
            return [{"section_id": p.get("section_id"), "title": p.get("section_title"), "excerpt": str(p.get("content", ""))[:700]} for p in result]
        return str(result)

    def get_section(section_id: str) -> Any:
        """Read the whole text of one NCERT section by its id, for example "9.2.4"."""
        result = tool_runner("get_section", {"section_id": section_id})
        if isinstance(result, dict) and result.get("ok"):
            _keep([{"section_id": result.get("section_id"), "section_title": result.get("section_title", ""),
                    "content": result.get("content", "")}])
            return {"section_id": result.get("section_id"), "title": result.get("section_title"), "text": str(result.get("content", ""))[:3000]}
        return result if isinstance(result, (dict, str)) else str(result)

    def get_exemplar(exemplar_id: str) -> Any:
        """Read one NCERT Exemplar problem by its id (never its solution)."""
        return tool_runner("get_exemplar", {"exemplar_id": exemplar_id})

    tools = [StructuredTool.from_function(f) for f in (search_textbook, get_section, get_exemplar)]
    strategy_desc, extra = _instructions(hint_level, approved_lesson, remediation, misconception,
                                         conversation_history, learner_context)
    task = (
        f"Student Query: {student_query}\nHint Level: {hint_level} - {strategy_desc}\n"
        + ("\n".join(extra) + "\n" if extra else "")
        + "\nLook up what you need, then draft exactly ONE concise, encouraging Socratic reply that cites the NCERT "
        "section ID. If the student has already explained it correctly, confirm it warmly with the citation and "
        "invite them to take the quiz or try the next topic."
    )
    model = llm.get_llm(model=config.SPECIALIST_MODEL, temperature=0.3)
    agent = create_react_agent(model, tools, prompt=TUTOR_PROMPT + REACT_INSTRUCTIONS)
    out = agent.invoke({"messages": [{"role": "user", "content": task}]}, config={"recursion_limit": MAX_REACT_STEPS})
    reply = str(out["messages"][-1].content or "").strip()
    if not reply:
        raise RuntimeError("the ReAct tutor returned no reply")
    if found and not re.search(r"\b(9|10|11)\.\d+", reply):
        reply += f" (Refer to NCERT Section {found[0]['section_id']})"
    return reply, found
