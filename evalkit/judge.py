"""Cross-family LLM judge for teaching quality (what code cannot decide).

The judge model comes from a different family from the tutor's agents
(config/models.yaml). Before its verdicts are relied on, evalkit/calibrate.py
compares them with 20+ human labels and reports Cohen's kappa per criterion.
"""

from __future__ import annotations

import re
from typing import Any

from evalkit import llm_client
from evalkit.llm_client import JUDGE_CRITERIA
from socratic_tutor import config


def _template() -> str:
    return re.sub(r"<!--.*?-->\n?", "", config.load_prompt("judge"), flags=re.S)


def evaluate_transcript(transcript: str, problem: str = "", misconception: str = "", callbacks: list | None = None) -> dict[str, Any]:
    """Return {criterion: "yes"|"no"} plus reasons. Unparseable output is recorded as an error."""
    system = _template().format(problem=problem or "(none)", misconception=misconception or "(unknown)", transcript=transcript)
    raw = llm_client.chat(config.JUDGE_MODEL, system, "Return the JSON verdict now.", config.JUDGE_TEMPERATURE, role="judge", callbacks=callbacks)
    try:
        parsed = llm_client.parse_json(raw)
    except ValueError as exc:
        return {"error": str(exc), "raw": raw[:500]}
    verdicts: dict[str, Any] = {}
    reasons: dict[str, str] = {}
    for criterion in JUDGE_CRITERIA:
        entry = parsed.get(criterion, {})
        verdict = entry.get("verdict") if isinstance(entry, dict) else entry
        verdicts[criterion] = "yes" if str(verdict).strip().lower() == "yes" else "no"
        reasons[criterion] = entry.get("reason", "") if isinstance(entry, dict) else ""
    return {"verdicts": verdicts, "reasons": reasons, "judge_model": config.JUDGE_MODEL}
