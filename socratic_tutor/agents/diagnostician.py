"""Diagnostician Agent: Formulates probing questions and identifies misconceptions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from socratic_tutor import config, llm
from socratic_tutor.prompts import DIAGNOSTICIAN_PROMPT


def _load_catalog() -> list[dict[str, Any]]:
    path = config.DATA_DIR / "misconceptions.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


GENERIC_TOPIC_WORDS = {
    "mirror", "mirrors", "lens", "lenses", "light", "image", "images", "ray", "rays", "object", "objects", "current",
    "circuit", "eye", "eyes", "know", "about", "question", "answer", "student", "students", "physics", "science",
}


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
    best_common: set[str] = set()

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
            best_common = common

    # A topic word on its own ("does he know about mirrors") is not a mix-up: at least two words must be shared,
    # and one of them must be more than a general topic word. (Before, the mix-up's name counted double, so the
    # single word "mirrors" flagged "Concave mirrors always invert images" on any message about mirrors, and the
    # repeated mix-up then pushed the hint up every turn. Team testing, 12 Nov.)
    specific = best_common - GENERIC_TOPIC_WORDS
    if best_score >= 2 and best_match and len(best_common) >= 2 and specific:
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
    catalog_by_id = {m["id"]: m for m in catalog if isinstance(m, dict) and "id" in m}
    summarized = [
        {"id": m["id"], "name": m["name"], "concept": m.get("concept_id", "")}
        for m in catalog
    ]
    prompt = f"Student input: {query}\nKnown catalogued misconceptions:\n{json.dumps(summarized, indent=1)}\n"
    res = llm.chat_json(prompt=prompt, system_prompt=DIAGNOSTICIAN_PROMPT)
    if isinstance(res, dict):
        raw_id = res.get("identified_misconception_id") or res.get("id")
        if isinstance(raw_id, str):
            clean_id = raw_id.strip()
            if clean_id.lower() not in ("null", "none", "nil", "n/a", "undefined", "") and clean_id in catalog_by_id:
                cat = catalog_by_id[clean_id]
                return {
                    "identified_misconception_id": clean_id,
                    "identified_misconception_name": cat.get("name") or clean_id,
                    "chapter": cat.get("chapter") or res.get("chapter"),
                    "confidence": float(res.get("confidence") or 0.7),
                    "probing_question": res.get("probing_question") or cat.get("diagnostic_probe", "Can you explain your reasoning step by step?"),
                }
    keyword_match = match_misconception_by_keywords(query, catalog)
    if keyword_match:
        return keyword_match
    return {"identified_misconception_id": None, "identified_misconception_name": None}
