"""Tracing: one scrubbed JSONL record per LLM call, tool call and turn.

Every trace goes to .cache/traces/<date>.jsonl after personal data is removed
(phone numbers, e-mail addresses, and anything that looks like a name after
"my name is"). The app and the eval harness both write here, so the red-team
check "personal data appears in a trace" tests the real code path.

Optional: set LANGSMITH_TRACING=true and LANGSMITH_API_KEY to also send runs to
LangSmith. LangChain picks those variables up by itself; text reaching the
models has already passed the input guardrail's masking.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?\d{10}(?!\d)")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b")
_NAME = re.compile(r"(?i)\b(my name is|i am called|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")
_LOCK = threading.Lock()


def scrub(value: Any) -> Any:
    """Remove personal data from strings, recursively through dicts and lists."""
    if isinstance(value, str):
        text = _PHONE.sub("[PHONE]", value)
        text = _EMAIL.sub("[EMAIL]", text)
        return _NAME.sub(lambda m: f"{m.group(1)} [NAME]", text)
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(item) for item in value]
    return value


def traces_dir() -> Path:
    from socratic_tutor import config

    path = config.TRACES_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def record(kind: str, **fields: Any) -> dict[str, Any]:
    """Append one scrubbed trace record and return it."""
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "kind": kind}
    entry.update(scrub(fields))
    line = json.dumps(entry, ensure_ascii=False, default=str)
    path = traces_dir() / f"{entry['ts'][:10]}.jsonl"
    with _LOCK, open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return entry


class SocraticTracer:
    """Collects timed spans for one request; ``flush`` writes them as a trace record."""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id
        self.spans: list[dict[str, Any]] = []

    def start_span(self, name: str, metadata: dict[str, Any] | None = None) -> dict:
        span = {"name": name, "start_time": time.time(), "metadata": metadata or {}}
        self.spans.append(span)
        return span

    def end_span(self, span: dict) -> None:
        span["end_time"] = time.time()
        span["duration_ms"] = round((span["end_time"] - span["start_time"]) * 1000, 2)

    def flush(self, **fields: Any) -> dict[str, Any]:
        return record("request", session_id=self.session_id, spans=self.spans, **fields)


class TraceCallback:
    """LangChain callback that writes a scrubbed record for every LLM and tool call."""

    def __new__(cls, session_id: str | None = None):  # built lazily so importing this module stays cheap
        from langchain_core.callbacks import BaseCallbackHandler

        class _Handler(BaseCallbackHandler):
            def __init__(self, sid: str | None):
                self.sid = sid
                self._starts: dict[Any, float] = {}

            def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):  # noqa: ANN001
                self._starts[run_id] = time.perf_counter()

            def on_llm_end(self, response, *, run_id, **kwargs):  # noqa: ANN001
                started = self._starts.pop(run_id, None)
                usage: dict[str, Any] = {}
                model = ""
                text = ""
                for generations in response.generations or []:
                    for generation in generations:
                        message = getattr(generation, "message", None)
                        metadata = getattr(message, "response_metadata", {}) or {}
                        usage = metadata.get("token_usage") or usage
                        model = metadata.get("model_name") or model
                        text = str(getattr(message, "content", "") or "")[:500]
                record(
                    "llm_call",
                    session_id=self.sid,
                    model=model,
                    latency_ms=round((time.perf_counter() - started) * 1000, 1) if started else None,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    cost_usd=usage.get("cost"),
                    output_preview=text,
                )

            def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):  # noqa: ANN001
                self._starts[run_id] = time.perf_counter()
                record("tool_start", session_id=self.sid, tool=(serialized or {}).get("name"), input=str(input_str)[:500])

            def on_tool_end(self, output, *, run_id, **kwargs):  # noqa: ANN001
                started = self._starts.pop(run_id, None)
                record(
                    "tool_end",
                    session_id=self.sid,
                    latency_ms=round((time.perf_counter() - started) * 1000, 1) if started else None,
                    output=str(output)[:500],
                )

        return _Handler(session_id)


class CostMeter:
    """Counts LLM calls, tokens and the cost OpenRouter reports for them.

    Pass one per request (app) or per case (eval) as a LangChain callback.
    A call whose provider reports no cost makes the total unknown (None):
    costs are never estimated.
    """

    def __new__(cls):
        from langchain_core.callbacks import BaseCallbackHandler

        class _Meter(_MeterBase, BaseCallbackHandler):
            pass

        return _Meter()


class _MeterBase:
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
