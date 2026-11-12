"""LLM access for the evaluation harness: metering, OpenRouter costs, offline stand-in.

* ``Meter`` (socratic_tutor.trace.CostMeter) counts LLM calls, tokens and cost.
  The runner attaches one per case, so every result row carries its own cost.
* Costs are taken from OpenRouter's usage accounting (the ``cost`` field it
  returns when ``usage.include`` is requested). If a provider does not report a
  cost, the row records tokens and leaves cost blank: no prices are guessed.
* ``stub_mode()`` is true when there is no API key or EVAL_STUB=1. Every LLM call
  is then answered by a deterministic stand-in so the plumbing can be tested in
  CI. Results from stub runs are labelled STUB and excluded from the report.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

from socratic_tutor import config, llm as team_llm
from socratic_tutor.trace import CostMeter
from evalkit.prompts import JUDGE_DIMENSIONS as JUDGE_CRITERIA  # teacher's rubric


def stub_mode() -> bool:
    if os.getenv("EVAL_STUB", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return not (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY"))


Meter = CostMeter  # shared with the app: socratic_tutor/trace.py


class StubChatModel(BaseChatModel):
    """Deterministic offline stand-in. Its answers are placeholders, never results."""

    role: str = "generic"

    @property
    def _llm_type(self) -> str:
        return "eval-stub"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs: Any) -> ChatResult:  # noqa: ANN001
        text = "\n".join(str(m.content) for m in messages)
        content = _stub_reply(self.role, text)
        message = AIMessage(
            content=content,
            response_metadata={"token_usage": {"prompt_tokens": len(text) // 4, "completion_tokens": len(content) // 4, "cost": 0.0}, "model_name": f"stub/{self.role}"},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def _stub_reply(role: str, text: str) -> str:
    if role == "simulated_student":
        if "QUIZ PHASE: PRE" in text:
            match = re.search(r"MISCONCEPTION OPTION: ([A-D])", text)
            return match.group(1) if match else "B"
        if "QUIZ PHASE: POST" in text:
            match = re.search(r"CORRECT OPTION FOR STUB: ([A-D])", text)
            return match.group(1) if match else "A"
        return "Hmm, I'm not sure. Can you give me another hint? [STUB]"
    if role == "judge":
        return json.dumps({k: {"score": 3, "reason": "stub"} for k in JUDGE_CRITERIA})
    if role == "grader":
        return json.dumps({"is_correct": "correct" in text.lower(), "score": 0.5, "feedback": "stub"})
    return json.dumps(
        {
            "reply": "Let's think step by step. Which rule from the textbook applies first? (NCERT Sec 9.2.4) [STUB]",
            "diagnosed_misconception_id": None,
            "cited_section_ids": ["9.2.4"],
        }
    )




def make_chat(model: str, temperature: float, role: str = "generic") -> BaseChatModel:
    """Chat model for the harness's own calls (simulated student, judge, baselines)."""
    if stub_mode():
        return StubChatModel(role=role)

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=os.getenv("OPENROUTER_API_KEY", config.OPENROUTER_API_KEY) or os.getenv("OPENAI_API_KEY", config.OPENAI_API_KEY),
        base_url=os.getenv("OPENROUTER_BASE_URL", config.OPENROUTER_BASE_URL),
        timeout=90,
        max_retries=2,
        max_tokens=config.LLM_MAX_TOKENS,  # OpenRouter reserves credit for the maximum reply
        extra_body={"usage": {"include": True}},  # OpenRouter returns the call's cost
    )


def chat(model: str, system: str, user: str, temperature: float, role: str, callbacks: list | None = None) -> str:
    client = make_chat(model, temperature, role)
    response = client.invoke([SystemMessage(content=system), HumanMessage(content=user)], config={"callbacks": callbacks or []})
    return str(response.content)


def parse_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply."""
    cleaned = text.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        cleaned = next((p[4:] if p.startswith("json") else p for p in parts if "{" in p), cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in reply: {text[:200]!r}")
    return json.loads(cleaned[start : end + 1])


class Stopwatch:
    def __enter__(self) -> "Stopwatch":
        self.start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.seconds = time.perf_counter() - self.start


def patch_team_llm_for_stub() -> None:
    """In stub mode, route the tutor's own LLM helper to the stand-in too."""
    if not stub_mode():
        return

    team_llm.get_llm = lambda model=config.SPECIALIST_MODEL, temperature=0.2: StubChatModel(role="grader")  # type: ignore[assignment]
