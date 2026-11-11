"""The systems under test, behind one interface so every experiment uses the same harness.

    c2      the team's LangGraph tutor (socratic_tutor.graph): supervisor + specialists
    c0      fixed workflow: retrieve passages, then one prompt (no agent decisions)
    c1      one ReAct agent with all the tools and the same budget
    direct  E4 condition: same retrieval and model as c0, but answers directly

Every system gets the same input guardrail, so E1 compares the agent designs and
not the guardrails. E2 switches the guardrails off for all of them together.

Each system returns a ``TurnResult``. The harness never reads gold answers into a
system: problems reach the tutor only as the student's own message.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field

from evalkit import datasets, llm_client, prompts
from socratic_tutor import config, policy
from socratic_tutor.graph import build_graph
from socratic_tutor.learner_store import LearnerStore
from socratic_tutor.tools import math_tools, textbook_kb

REFUSAL = "I cannot fulfill this request as entered. Let's focus on our NCERT study goals."


@dataclass
class TurnResult:
    text: str
    citations: list[str] = field(default_factory=list)
    diagnosed: str | None = None
    steps: list[str] = field(default_factory=list)
    blocked: bool = False
    teacher_alert: bool = False
    pending_approval: bool = False
    error: str | None = None


class TutorSystem:
    name = "base"

    def start(self, student_id: str, mode: str, current_question_id: str | None = None) -> None:
        self.session_id = f"eval-{uuid.uuid4().hex[:10]}"
        self.student_id = student_id
        self.mode = mode
        self.current_question_id = current_question_id
        self.history: list[tuple[str, str]] = []

    def turn(self, message: str, callbacks: list | None = None) -> TurnResult:
        raise NotImplementedError

    # shared input guardrail for the baselines (c2 runs its own inside the graph)
    def _guard(self, message: str) -> tuple[str | None, TurnResult | None]:
        guard = policy.check_input_guardrails(message)  # looked up at call time so E2 can switch it off
        if not guard["passed"]:
            return None, TurnResult(text=REFUSAL, blocked=True, teacher_alert=bool(guard["is_distress"]), steps=["input_guardrail"])
        return guard["sanitized_query"], None


# --------------------------------------------------------------------- C2


class GraphSystem(TutorSystem):
    """The team's graph. Reads what the graph puts in state; changes nothing in it."""

    name = "c2"

    def __init__(self) -> None:
        self.app = build_graph(checkpointer=InMemorySaver())

    def turn(self, message: str, callbacks: list | None = None) -> TurnResult:
        thread = {"configurable": {"thread_id": self.session_id}, "callbacks": callbacks or [], "recursion_limit": config.GRAPH_RECURSION_LIMIT}
        before = self.app.get_state(thread).values.get("steps", []) if self.history else []
        state_in = {
            "session_id": self.session_id,
            "student_id": self.student_id,
            "mode": self.mode,
            "current_question_id": getattr(self, "current_question_id", None),
            "query": message,
            "messages": [HumanMessage(content=message)],
            "steps": [],
            "response": "",
            "citations": [],
            "identified_misconception": None,
            "injection_detected": False,
            "teacher_alert_triggered": False,
            "hint_step": len(self.history) + 1,
        }
        if not self.history:
            state_in["mastery_map"] = {}
        out = self.app.invoke(state_in, config=thread)
        steps = list(out.get("steps", []))[len(before):]
        diagnosed = out.get("identified_misconception") or None
        if isinstance(diagnosed, dict):
            diagnosed = diagnosed.get("id")
        text = str(out.get("response") or "")
        self.history.append((message, text))
        return TurnResult(
            text=text,
            citations=[str(c) for c in out.get("citations") or []],
            diagnosed=diagnosed,
            steps=steps,
            blocked=bool(out.get("injection_detected")) or text == REFUSAL,
            teacher_alert=bool(out.get("teacher_alert_triggered")),
            pending_approval="__interrupt__" in out,
        )


# --------------------------------------------------------------------- C0 / direct


def _misconception_list() -> str:
    return "\n".join(f"{m['id']}: {m['name']}" for m in datasets.misconceptions().values())


def _history_text(history: list[tuple[str, str]]) -> str:
    if not history:
        return "(start of conversation)"
    return "\n".join(f"Student: {s}\nTutor: {t}" for s, t in history[-6:])


def _prompt(name: str) -> str:
    return {"baseline_c0": prompts.BASELINE_C0, "baseline_c1": prompts.BASELINE_C1, "baseline_direct": prompts.BASELINE_DIRECT}[name]


class RetrievalPromptSystem(TutorSystem):
    """C0, and the E4 'direct' condition: retrieval followed by one prompt."""

    def __init__(self, prompt_name: str, name: str) -> None:
        self.prompt_name = prompt_name
        self.name = name
        self.kb = textbook_kb

    def turn(self, message: str, callbacks: list | None = None) -> TurnResult:
        clean, blocked = self._guard(message)
        if blocked:
            self.history.append((message, blocked.text))
            return blocked
        hits = self.kb.search_textbook(clean or "", top_k=4)
        passages = "\n\n".join(f"[{h['section_id']}] {h['section_title']}: {h['content'][:900]}" for h in hits) or "(no passages found)"
        system = _prompt(self.prompt_name).format(passages=passages, misconceptions=_misconception_list(), history=_history_text(self.history))
        raw = llm_client.chat(config.SPECIALIST_MODEL, system, clean or "", config.AGENT_TEMPERATURE, role="tutor", callbacks=callbacks)
        try:
            parsed = llm_client.parse_json(raw)
            text = str(parsed.get("reply", ""))
            diagnosed = parsed.get("diagnosed_misconception_id") or None
            cited = [str(s) for s in parsed.get("cited_section_ids") or []]
        except (ValueError, json.JSONDecodeError):
            text, diagnosed, cited = raw, None, []
        self.history.append((message, text))
        return TurnResult(text=text, citations=cited, diagnosed=diagnosed, steps=["input_guardrail", "retrieve", "prompt"])


# --------------------------------------------------------------------- C1


class SingleAgentSystem(TutorSystem):
    """C1: one ReAct agent with every tool the team uses, under the same budget."""

    name = "c1"

    def __init__(self) -> None:
        self._agent = None if llm_client.stub_mode() else self._build()
        self._fallback = RetrievalPromptSystem("baseline_c0", "c1-stub")

    def start(self, student_id: str, mode: str) -> None:
        super().start(student_id, mode)
        self._fallback.start(student_id, mode)

    def _build(self):  # noqa: ANN202
        @tool
        def search_textbook(query: str) -> list[dict]:
            """Search NCERT Class 10 Science (chapters 9-11). Returns sections with IDs."""
            return [{"section_id": h["section_id"], "title": h["section_title"], "content": h["content"][:900]} for h in textbook_kb.search_textbook(query, top_k=4)]

        @tool
        def get_section(section_id: str) -> dict:
            """Fetch one NCERT section by ID, e.g. '9.2.4'."""
            hit = textbook_kb.get_section(section_id)
            return {k: hit[k] for k in ("section_id", "section_title", "content")} if hit else {"error": "not found"}

        @tool
        def misconception_catalogue(chapter: str = "") -> list[dict]:
            """List catalogued misconceptions (optionally for one chapter) with a probe question."""
            return [
                {"id": m["id"], "name": m["name"], "probe": m["diagnostic_probe"]}
                for m in datasets.misconceptions().values()
                if not chapter or chapter.lower() in m["chapter"].lower()
            ]

        @tool
        def mirror_formula(u: float, f: float) -> dict:
            """Image distance v for a spherical mirror, 1/v + 1/u = 1/f (cm, New Cartesian signs)."""
            return math_tools.solve_mirror_formula("cm", u=u, f=f)

        @tool
        def lens_formula(u: float, f: float) -> dict:
            """Image distance v for a lens, 1/v - 1/u = 1/f (cm, New Cartesian signs)."""
            return math_tools.solve_lens_formula("cm", u=u, f=f)

        @tool
        def ohms_law(v: float | None = None, i: float | None = None, r: float | None = None) -> dict:
            """Solve V = IR given any two of V, I, R."""
            return math_tools.solve_ohms_law(v=v, i=i, r=r)

        @tool
        def equivalent_resistance(resistors: list[float], mode: str = "series") -> dict:
            """Equivalent resistance of resistors in 'series' or 'parallel'."""
            if mode == "parallel":
                return math_tools.solve_parallel_resistance(resistors)
            return math_tools.solve_series_resistance(resistors)

        @tool
        def numeric_check(student_value: float, correct_value: float) -> bool:
            """Is the student's number within 5% of the correct one?"""
            return math_tools.numeric_check(student_value, correct_value)

        store = LearnerStore()

        @tool
        def learner_record(student_id: str) -> dict:
            """Read the student's mastery and past misconceptions."""
            return store.get_profile(student_id)

        class TutorReply(BaseModel):
            reply: str = Field(description="message to the student")
            diagnosed_misconception_id: str | None = Field(default=None)
            cited_section_ids: list[str] = Field(default_factory=list)

        model = llm_client.make_chat(config.SPECIALIST_MODEL, config.AGENT_TEMPERATURE, role="tutor")
        return create_react_agent(
            model,
            [search_textbook, get_section, misconception_catalogue, mirror_formula, lens_formula, ohms_law, equivalent_resistance, numeric_check, learner_record],
            prompt=_prompt("baseline_c1"),
            response_format=TutorReply,
            checkpointer=InMemorySaver(),
        )

    def turn(self, message: str, callbacks: list | None = None) -> TurnResult:
        if self._agent is None:
            result = self._fallback.turn(message, callbacks)
            self.history.append((message, result.text))
            return result
        clean, blocked = self._guard(message)
        if blocked:
            self.history.append((message, blocked.text))
            return blocked
        cfg = {"configurable": {"thread_id": self.session_id}, "callbacks": callbacks or [], "recursion_limit": config.GRAPH_RECURSION_LIMIT}
        out = self._agent.invoke({"messages": [HumanMessage(content=f"(student id {self.student_id}, mode {self.mode})\n{clean}")]}, config=cfg)
        structured = out.get("structured_response")
        tools_used = [m.name for m in out.get("messages", []) if getattr(m, "type", "") == "tool"]
        if structured is None:
            text = str(out["messages"][-1].content)
            result = TurnResult(text=text, steps=["agent"] + tools_used)
        else:
            result = TurnResult(text=structured.reply, citations=list(structured.cited_section_ids), diagnosed=structured.diagnosed_misconception_id, steps=["agent"] + tools_used)
        self.history.append((message, result.text))
        return result


def make_system(name: str) -> TutorSystem:
    if name == "c2":
        return GraphSystem()
    if name == "c0":
        return RetrievalPromptSystem("baseline_c0", "c0")
    if name == "c1":
        return SingleAgentSystem()
    if name == "direct":
        return RetrievalPromptSystem("baseline_direct", "direct")
    raise ValueError(f"Unknown system {name!r} (use c0, c1, c2 or direct)")
