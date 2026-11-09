"""Cross-family LLM judge for teaching quality (what code cannot decide).

Scores the three dimensions our consulting teacher uses (questionnaire 4.1),
each 1-5: conceptual accuracy, identified misconception, Socratic guidance.
The judge model comes from a different family from the tutor's agents
(socratic_tutor/config.py). evalkit/calibrate.py compares its scores with 20+
human labels (weighted Cohen's kappa) before they are relied on.
"""

from __future__ import annotations

from typing import Any

from evalkit import llm_client, prompts
from socratic_tutor import config

PASS_SCORE = 4  # a session "passes" the judge when every dimension scores 4 or 5


def evaluate_transcript(transcript: str, problem: str = "", misconception: str = "", callbacks: list | None = None) -> dict[str, Any]:
    """Return {"scores": {dimension: 1-5}, "reasons": {...}, "passed": bool}. Unparseable output is an error, not a score."""
    system = prompts.JUDGE.format(problem=problem or "(none)", misconception=misconception or "(unknown)", transcript=transcript)
    raw = llm_client.chat(config.JUDGE_MODEL, system, "Return the JSON scores now.", config.JUDGE_TEMPERATURE, role="judge", callbacks=callbacks)
    try:
        parsed = llm_client.parse_json(raw)
    except ValueError as exc:
        return {"error": str(exc), "raw": raw[:500]}
    scores: dict[str, int] = {}
    reasons: dict[str, str] = {}
    for dimension in prompts.JUDGE_DIMENSIONS:
        entry = parsed.get(dimension, {})
        value = entry.get("score") if isinstance(entry, dict) else entry
        try:
            scores[dimension] = min(5, max(1, int(round(float(value)))))
        except (TypeError, ValueError):
            return {"error": f"no score for {dimension}", "raw": raw[:500]}
        reasons[dimension] = entry.get("reason", "") if isinstance(entry, dict) else ""
    return {
        "scores": scores,
        "reasons": reasons,
        "passed": all(v >= PASS_SCORE for v in scores.values()),
        "judge_model": config.JUDGE_MODEL,
        "prompt_version": prompts.PROMPT_VERSION,
    }
