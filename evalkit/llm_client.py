"""LLM access for the evaluation harness: metering, OpenRouter costs, offline stand-in.

* ``Meter`` is a LangChain callback that counts LLM calls, tokens and cost. The
  runner attaches one per case, so every result row carries its own cost.
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
import threading
import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from socratic_tutor import config


def stub_mode() -> bool:
    if os.getenv("EVAL_STUB", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return not (os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY"))


class Meter(BaseCallbackHandler):
    """Counts calls, tokens and reported cost for every LLM call it sees."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost_usd = 0.0
        self.cost_reported = True
        self.by_model: dict[str, int] = {}

    def on_llm_end(self, response, **kwargs: Any) -> None:  # noqa: ANN001 - LangChain signature
        with self._lock:
            self.calls += 1
            usage: dict[str, Any] = {}
            model = ""
            for generations in response.generations or []:
                for generation in generations:
                    message = getattr(generation, "message", None)
                    metadata = getattr(message, "response_metadata", {}) or {}
                    usage = metadata.get("token_usage") or usage
                    model = metadata.get("model_name") or model
                    usage_meta = getattr(message, "usage_metadata", None) or {}
                    if usage_meta and not usage:
                        usage = {
                            "prompt_tokens": usage_meta.get("input_tokens", 0),
                            "completion_tokens": usage_meta.get("output_tokens", 0),
                        }
            if not usage and response.llm_output:
                usage = response.llm_output.get("token_usage", {}) or {}
            self.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            self.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
            if usage.get("cost") is not None:
                self.cost_usd += float(usage["cost"])
            else:
                self.cost_reported = False
            if model:
                self.by_model[model] = self.by_model.get(model, 0) + 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "llm_calls": self.calls,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                # no calls -> no cost; a call without a reported cost -> unknown (blank), never guessed
                "cost_usd": 0.0 if not self.calls else (round(self.cost_usd, 6) if self.cost_reported else None),
                "models": dict(self.by_model),
            }


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
        return json.dumps({k: {"verdict": "yes", "reason": "stub"} for k in JUDGE_CRITERIA})
    if role == "grader":
        return json.dumps({"is_correct": "correct" in text.lower(), "score": 0.5, "feedback": "stub"})
    return json.dumps(
        {
            "reply": "Let's think step by step. Which rule from the textbook applies first? (NCERT Sec 9.2.4) [STUB]",
            "diagnosed_misconception_id": None,
            "cited_section_ids": ["9.2.4"],
        }
    )


JUDGE_CRITERIA = ("guided_not_told", "grounded", "targeted", "age_appropriate", "overall_acceptable")


def make_chat(model: str, temperature: float, role: str = "generic") -> BaseChatModel:
    """Chat model for the harness's own calls (simulated student, judge, baselines)."""
    if stub_mode():
        return StubChatModel(role=role)
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        timeout=90,
        max_retries=2,
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
    from socratic_tutor import llm as team_llm

    team_llm.get_llm = lambda model=config.SPECIALIST_MODEL, temperature=0.2: StubChatModel(role="grader")  # type: ignore[assignment]
