"""Diagnostician Agent: Formulates probing questions and identifies misconceptions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from socratic_tutor import config, llm

DIAGNOSTICIAN_PROMPT = """You are an expert pedagogical diagnostician in NCERT Class 10 Science (Light, Eye, Electricity).
Your role is to diagnose the underlying misconception in the student's reasoning or question.
Do NOT give away the answer or write derivations.
Analyze the student's question against the provided list of catalogued misconceptions.

Output a valid JSON object matching:
{
  "identified_misconception_id": "<e.g. MISCON_LIGHT_03 or null>",
  "identified_misconception_name": "<name of misconception or null>",
  "confidence": <float between 0.0 and 1.0>,
  "probing_question": "<ONE focused Socratic question targeting their mental model>"
}
"""


def _load_catalog() -> list[dict[str, Any]]:
    path = config.DATA_DIR / "misconceptions.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def match_misconception_by_keywords(query: str, catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Deterministic matching based on token overlap with catalogued misconceptions."""
    if not query.strip() or not catalog:
        return None
    stop_words = {
        "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "is", "are",
        "was", "were", "what", "why", "how", "where", "does", "do", "can", "if",
        "my", "me", "i", "you", "and", "or", "from", "that", "this", "it"
    }
    query_tokens = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in stop_words and len(w) > 2}
    if not query_tokens:
        return None

    best_match = None
    best_score = 0

    for item in catalog:
        text = f"{item.get('name', '')} {item.get('description', '')} {item.get('diagnostic_probe', '')}"
        item_tokens = {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in stop_words and len(w) > 2}
        common = query_tokens & item_tokens
        score = len(common)
        name_tokens = {w for w in re.findall(r"[a-z0-9]+", item.get("name", "").lower())}
        score += 2 * len(query_tokens & name_tokens)
        if score > best_score:
            best_score = score
            best_match = item

    if best_score >= 2 and best_match:
        return {
            "identified_misconception_id": best_match["id"],
            "identified_misconception_name": best_match["name"],
            "chapter": best_match.get("chapter"),
            "confidence": min(1.0, 0.4 + 0.15 * best_score),
            "probing_question": best_match.get("diagnostic_probe", "Can you explain your reasoning step by step?"),
        }
    return None


def diagnose_response(query: str, chapter_misconceptions: list[dict] | None = None) -> dict[str, Any]:
    """Analyze student input against catalogued misconceptions."""
    catalog = chapter_misconceptions or _load_catalog()
    summarized = [
        {"id": m["id"], "name": m["name"], "concept": m.get("concept_id", "")}
        for m in catalog
    ]
    prompt = f"Student input: {query}\nKnown catalogued misconceptions:\n{json.dumps(summarized, indent=1)}\n"
    res = llm.chat_json(prompt=prompt, system_prompt=DIAGNOSTICIAN_PROMPT)
    if isinstance(res, dict) and res.get("identified_misconception_id"):
        return res
    keyword_match = match_misconception_by_keywords(query, catalog)
    if keyword_match:
        return keyword_match
    return res if isinstance(res, dict) else {"identified_misconception_id": None, "identified_misconception_name": None}
