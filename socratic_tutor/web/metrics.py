"""Prometheus metrics exposed at /metrics and drawn in Grafana.

Names follow REPORT.md section 7. The alert rule AnswerLeakSpike
(alert_rules in docker/docker-compose.yml) watches socratic_answer_leaks_total.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry()

REQUESTS = Counter("socratic_requests_total", "Student turns handled", ["mode", "outcome"], registry=REGISTRY)
LATENCY = Histogram(
    "socratic_request_latency_seconds", "Time to answer one student turn", ["mode"], registry=REGISTRY,
    buckets=(0.25, 0.5, 1, 2, 4, 8, 15, 30, 60),
)
SESSIONS = Counter("socratic_sessions_started_total", "Tutoring sessions started", ["mode"], registry=REGISTRY)
ANSWER_LEAKS = Counter("socratic_answer_leaks_total", "Practice-mode replies flagged as giving away the answer", ["source"], registry=REGISTRY)
GUARDRAIL_BLOCKS = Counter("socratic_guardrail_blocks_total", "Turns stopped or replaced by a safety check (input guardrail, distress hand-off, reply check)", ["reason"], registry=REGISTRY)
DISTRESS_ALERTS = Counter("socratic_distress_alerts_total", "Distress hand-offs to a teacher", registry=REGISTRY)
STUCK_STUDENTS = Gauge("socratic_stuck_students_count", "Students with an open 'stuck' alert", registry=REGISTRY)
PENDING_APPROVALS = Gauge("socratic_pending_approvals", "Question items waiting for teacher approval", registry=REGISTRY)
APPROVAL_LATENCY = Histogram(
    "socratic_teacher_approval_latency_seconds", "Time from proposal to teacher decision", registry=REGISTRY,
    buckets=(60, 300, 900, 3600, 4 * 3600, 24 * 3600, 3 * 24 * 3600),
)
STALE_APPROVALS = Counter("socratic_stale_approvals_total", "Approvals rejected because the payload changed after it was viewed", registry=REGISTRY)
LLM_COST = Counter("socratic_llm_cost_dollars_total", "LLM cost reported by OpenRouter", registry=REGISTRY)
LLM_CALLS = Counter("socratic_llm_calls_total", "LLM calls made while answering students", registry=REGISTRY)
TURN_COST = Histogram(
    "socratic_turn_cost_dollars", "LLM cost of one student turn", registry=REGISTRY,
    buckets=(0.0001, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05),
)
MASTERY_DELTA = Histogram(
    "socratic_mastery_delta", "Change in a concept's mastery after a turn", registry=REGISTRY,
    buckets=(-0.5, -0.2, -0.1, -0.01, 0.01, 0.1, 0.2, 0.5),
)
CLASS_MISCONCEPTIONS = Gauge("socratic_class_misconception_students", "Students in whom a misconception has been seen", ["misconception_id"], registry=REGISTRY)
ERRORS = Counter("socratic_errors_total", "Unhandled errors while answering", ["where"], registry=REGISTRY)
