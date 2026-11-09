"""Tracing, Prometheus metrics, and execution logging."""

import time
from typing import Any


class SocraticTracer:
    def __init__(self):
        self.spans = []

    def start_span(self, name: str, metadata: dict[str, Any] | None = None) -> dict:
        span = {
            "name": name,
            "start_time": time.time(),
            "metadata": metadata or {}
        }
        self.spans.append(span)
        return span

    def end_span(self, span: dict) -> None:
        span["end_time"] = time.time()
        span["duration_ms"] = round((span["end_time"] - span["start_time"]) * 1000, 2)
