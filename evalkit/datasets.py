"""Loaders for every evaluation dataset. Development rows live in data/; held-out rows in evalkit/held_out/.

The guide (p.5) asks for the held-out cases "in a folder the agent cannot read": the app's image does not
contain evalkit/held_out/ (.dockerignore), and only the evaluation service mounts it (HELD_OUT_DIR).

One source per thing, no copies:
    data/gold_questions.jsonl         the team's gold set (split: dev / held_out)
    data/gold_question_checks.jsonl   per question: code answer keys + one labelled wrong answer
    data/simulated_students.jsonl     hidden student cards (split: dev / held_out)
    data/practice_problems.jsonl      the problem each simulated student brings (one per misconception and split)
    data/quiz_bank.jsonl              pre/post quiz items, two parallel forms per misconception
    data/retrieval_queries.jsonl      labelled retrieval queries (R2)
    data/redteam/                     attacks, clean look-alikes, fixtures
    data/misconceptions.json, data/concept_graph.json  (R1)

Anything that can be worked out from these files is derived here instead of
being written twice: section IDs come from a question's citations, and a
student's practice problem, quizzes and "change of mind" condition come from
their seeded misconception.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from socratic_tutor import config

SPLITS = ("dev", "held_out")
_SECTION = re.compile(r"Section (\d+\.\d+(?:\.\d+)?)")
_CHAPTERS = ("Light - Reflection and Refraction", "Human Eye and the Colourful World", "Electricity")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset file: {path}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _data(name: str) -> Path:
    return config.DATA_DIR / name


HELD_OUT_DIR = Path(__import__("os").getenv("HELD_OUT_DIR", str(Path(__file__).resolve().parent / "held_out")))


def split_rows(name: str) -> list[dict[str, Any]]:
    """The rows of a split dataset: data/<name> (dev) plus evalkit/held_out/<name> (held-out), if mounted."""
    rows = _read_jsonl(_data(name))
    held = HELD_OUT_DIR / name
    if held.exists():
        rows += _read_jsonl(held)
    return rows


def _check_split(split: str) -> str:
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, not {split!r}")
    return split


# ------------------------------------------------------------------ curriculum (R1)


@lru_cache(maxsize=None)
def misconceptions() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in json.loads(_data("misconceptions.json").read_text(encoding="utf-8"))}


@lru_cache(maxsize=None)
def concepts() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in json.loads(_data("concept_graph.json").read_text(encoding="utf-8"))["concepts"]}


def chapter_of_misconception(misconception_id: str) -> str:
    return misconceptions()[misconception_id]["chapter"]


# ------------------------------------------------------------------ gold questions


@lru_cache(maxsize=None)
def _gold_checks() -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in _read_jsonl(_data("gold_question_checks.jsonl"))}


def gold_questions(split: str) -> list[dict[str, Any]]:
    """Gold questions of one split, with derived fields added (the file is not changed)."""
    out = []
    for q in split_rows("gold_questions.jsonl"):
        if q.get("split") != _check_split(split):
            continue
        q = dict(q)
        citations = " ".join(q.get("gold_citations", []))
        q["gold_section_ids"] = list(dict.fromkeys(_SECTION.findall(citations)))
        q["chapter"] = next((c for c in _CHAPTERS if c in citations), None)
        check = _gold_checks().get(q["id"], {})
        q["answer_specs"] = check.get("answer_specs", [])
        q["sample_answers"] = [{"text": q["gold_answer"], "is_correct": True}]
        if check.get("wrong_answer"):
            q["sample_answers"].append({"text": check["wrong_answer"], "is_correct": False})
        out.append(q)
    return out


# ------------------------------------------------------------------ simulated students


@lru_cache(maxsize=None)
def quiz_bank() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in _read_jsonl(_data("quiz_bank.jsonl"))}


@lru_cache(maxsize=None)
def _practice_problems() -> list[dict[str, Any]]:
    return _read_jsonl(_data("practice_problems.jsonl"))


def practice_problem_for(misconception_id: str, split: str) -> dict[str, Any]:
    for problem in _practice_problems():
        if problem["misconception_id"] == misconception_id and problem["split"] == split:
            return problem
    raise KeyError(f"No {split} practice problem for {misconception_id} in data/practice_problems.jsonl")


def _quiz_items(misconception_ids: list[str], form: str) -> list[str]:
    bank = quiz_bank()
    return [item_id for m in misconception_ids if (item_id := f"QZ_{m.split('_', 1)[1]}_{form}") in bank]


def simulated_students(split: str) -> list[dict[str, Any]]:
    """Student cards of one split, completed with fields derived from the misconception catalogue."""
    cards = []
    for card in split_rows("simulated_students.jsonl"):
        if card.get("split") != _check_split(split):
            continue
        card = dict(card)
        seeded = card["seeded_misconceptions"]
        catalogue = misconceptions()
        card.setdefault("archetype", "unspecified")
        card.setdefault("voice", f"Writes like a typical {card.get('persona_type', 'Class 10')} student.")
        card.setdefault(
            "convinced_when",
            {m: f"the tutor helps you work through this yourself: {catalogue[m]['scaffolding_hint']}" for m in seeded},
        )
        card.setdefault("opening_message", f"Can you help me with this? I think {catalogue[seeded[0]]['name'].lower()}.")
        card["practice_problem"] = practice_problem_for(seeded[0], split)
        card["pre_quiz"] = _quiz_items(seeded, "A")
        card["post_quiz"] = _quiz_items(seeded, "B")
        cards.append(card)
    return cards


# ------------------------------------------------------------------ retrieval and red team


def retrieval_queries(split: str) -> list[dict[str, Any]]:
    return [row for row in split_rows("retrieval_queries.jsonl") if row.get("split") == _check_split(split)]


def redteam_attacks() -> list[dict[str, Any]]:
    return _read_jsonl(_data("redteam/attacks.jsonl"))


def clean_cases() -> list[dict[str, Any]]:
    return _read_jsonl(_data("redteam/clean_cases.jsonl"))


@lru_cache(maxsize=None)
def redteam_fixtures() -> dict[str, Any]:
    return json.loads(_data("redteam/fixtures.json").read_text(encoding="utf-8"))
