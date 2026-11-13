"""The held-out cases sit in a folder the agent cannot read (capstone guide p.5)."""

from pathlib import Path

from evalkit import datasets

ROOT = Path(__file__).resolve().parent.parent


def test_the_app_never_refers_to_the_held_out_folder():
    for path in (ROOT / "socratic_tutor").rglob("*.py"):
        assert "held_out" not in path.read_text(encoding="utf-8"), f"{path} mentions the held-out folder"


def test_the_app_image_leaves_the_held_out_folder_out():
    assert "evalkit/held_out" in (ROOT / ".dockerignore").read_text(encoding="utf-8")


def test_data_has_only_development_rows_and_the_harness_still_sees_both_splits():
    import json
    for name in ("gold_questions.jsonl", "simulated_students.jsonl", "retrieval_queries.jsonl"):
        rows = [json.loads(l) for l in (ROOT / "data" / name).read_text(encoding="utf-8").splitlines() if l.strip()]
        assert rows and all(r.get("split") == "dev" for r in rows), name
    assert len(datasets.gold_questions("held_out")) == 40 and len(datasets.gold_questions("dev")) == 24
    assert len(datasets.simulated_students("held_out")) == 20
    assert len(datasets.retrieval_queries("held_out")) == 12
