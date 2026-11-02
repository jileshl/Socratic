"""Loaders for every evaluation dataset, with the held-out boundary enforced.

Dev cases live in eval/dev/ (and data/). Held-out cases live in eval_heldout/,
which only the eval container mounts. ``load_split("heldout", ...)`` refuses to
run unless that folder is present, and nothing under socratic_tutor/ may read
it (tests/test_heldout_isolation.py checks this).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from socratic_tutor import config

SPLITS = ("dev", "heldout")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset file: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def split_dir(split: str) -> Path:
    if split == "dev":
        return config.EVAL_DIR / "dev"
    if split == "heldout":
        if not config.EVAL_HELDOUT_DIR.exists():
            raise SystemExit(
                f"Held-out folder {config.EVAL_HELDOUT_DIR} is not mounted. Held-out runs happen only in the "
                "eval container (docker compose --profile eval run --rm eval ...)."
            )
        return config.EVAL_HELDOUT_DIR
    raise ValueError(f"split must be one of {SPLITS}, not {split!r}")


def load_split(split: str, name: str) -> list[dict[str, Any]]:
    """name: gold_questions | simulated_students | practice_problems"""
    return _read_jsonl(split_dir(split) / f"{name}.jsonl")


@lru_cache(maxsize=None)
def quiz_bank() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in _read_jsonl(config.EVAL_DIR / "quiz_bank.jsonl")}


@lru_cache(maxsize=None)
def misconceptions() -> dict[str, dict[str, Any]]:
    data = json.loads((config.DATA_DIR / "misconceptions.json").read_text(encoding="utf-8"))
    return {item["id"]: item for item in data}


@lru_cache(maxsize=None)
def concepts() -> dict[str, dict[str, Any]]:
    data = json.loads((config.DATA_DIR / "concept_graph.json").read_text(encoding="utf-8"))
    return {item["id"]: item for item in data["concepts"]}


def practice_problems(split: str) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in load_split(split, "practice_problems")}


def redteam_attacks() -> list[dict[str, Any]]:
    return _read_jsonl(config.BASE_DIR / "redteam" / "attacks.jsonl")


def clean_cases() -> list[dict[str, Any]]:
    return _read_jsonl(config.BASE_DIR / "redteam" / "clean_cases.jsonl")


@lru_cache(maxsize=None)
def redteam_fixtures() -> dict[str, Any]:
    return json.loads((config.BASE_DIR / "redteam" / "fixtures" / "redteam_fixtures.json").read_text(encoding="utf-8"))


def retrieval_queries(split: str) -> list[dict[str, Any]]:
    rows = _read_jsonl(config.DATA_DIR / "retrieval_queries.jsonl")
    wanted = "held_out" if split == "heldout" else "dev"
    return [row for row in rows if row.get("split") == wanted]


def chapter_of_misconception(misconception_id: str) -> str:
    return misconceptions()[misconception_id]["chapter"]
