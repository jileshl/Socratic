"""The NCERT book next to the tutor: real excerpts, figures cropped from the chapters, formulas, and lessons."""

import json

import pytest
from fastapi.testclient import TestClient

from socratic_tutor import book, config
from socratic_tutor.web.server import app

needs_index = pytest.mark.skipif(not (config.INDEX_DIR / "chunks.json").exists(), reason="NCERT index not built")


def test_every_listed_figure_file_exists_and_topics_point_at_real_figures():
    rows = json.loads((config.DATA_DIR / "book" / "figures.json").read_text(encoding="utf-8"))
    assert len(rows) >= 30
    for r in rows:
        assert (config.DATA_DIR / "book" / "figures" / r["file"]).exists(), r
    listed = {r["figure"] for r in rows}
    for concept, figs in book.CONCEPT_FIGURES.items():
        assert set(figs) <= listed, concept
    assert set(book.CONCEPT_FIGURES) == set(book.CONCEPT_SECTIONS)


def test_split_words_from_the_pdf_are_joined_again(monkeypatch):
    monkeypatch.setattr(book, "_vocab", lambda: {"formation": 16, "for": 120, "mation": 2, "mirrors": 30, "mirr": 1, "ors": 1})
    assert book._join_split_words("the for mation of images by mirr ors , here") == "the formation of images by mirrors, here"


@needs_index
def test_book_card_for_a_concave_mirror_question_shows_the_ray_diagrams():
    card = book.book_card(["9.2.2", "9.2.1"], "Why is the image in a concave mirror upside down?", "concept_concave_ray_diagrams")
    assert card["section_id"] == "9.2.2"
    assert card["figure"]["figure"] == "9.7"
    assert card["excerpt"] and len(card["excerpt"]) <= 400
    # the excerpt is the book's own text, not something made up
    words = card["excerpt"].split()[:6]
    assert " ".join(words).lower().replace(" ", "") in book._join_split_words(book._chunks()["9.2.2"]["content"].replace("\n", " ")).lower().replace(" ", "")


@needs_index
def test_lesson_depends_on_the_students_mastery():
    new = book.lesson("concept_ohms_law", None, "Ohm's Law")
    assert new["level"] == "new" and new["steps"][0]["kind"] == "read" and "Ohm" in new["steps"][0]["text"]
    assert any(s["kind"] == "formula" and s["items"][0]["eq"] == "V = IR" for s in new["steps"])
    assert any(s["kind"] == "figure" for s in new["steps"])
    going = book.lesson("concept_mirror_formula", 0.5, "Mirror formula")
    assert going["level"] == "in_progress" and going["steps"][1]["kind"] == "formula"
    done = book.lesson("concept_ohms_law", 0.9, "Ohm's Law", "concept_series_combination", "Resistors in Series")
    assert done["level"] == "mastered" and done["next"]["concept_id"] == "concept_series_combination"


def test_figures_are_served_and_nothing_else_is():
    client = TestClient(app)
    assert client.get("/book/figures/fig_9_7.png").status_code == 200
    assert client.get("/book/figures/..%2F..%2Fconcept_graph.json").status_code == 404
    assert client.get("/book/figures/figures.json").status_code == 404


@needs_index
def test_lesson_endpoint():
    client = TestClient(app)
    assert client.get("/api/lesson/concept_nope").status_code == 404
    out = client.get("/api/lesson/concept_concave_ray_diagrams").json()
    assert out["level"] == "new" and out["chapter"].startswith("Light")
    assert any(s.get("figure") == "9.7" for s in out["steps"])
    assert "no model" in out["how"]


@needs_index
def test_the_figure_fits_the_question_or_there_is_none():
    pick = lambda q, c, s: (book.pick_figure(q, c, s) or {}).get("figure")
    assert pick("Why is the image in a concave mirror upside down?", "concept_concave_ray_diagrams", ["9.2.2"]) == "9.7"
    assert pick("Why does adding a resistor in parallel lower the total resistance?", "concept_parallel_combination", ["11.6.2"]) == "11.7"
    assert pick("How does a concave lens correct short-sightedness?", "concept_myopia", ["10.2"]) == "10.2"
    assert pick("Why is the sky blue?", "concept_scattering", ["10.6.2"]) is None  # the book has no figure for it
    assert pick("What is the far point and near point of the human eye with normal vision?", "concept_accommodation", ["10.1.1"]) == "10.1"
    assert pick("A student has difficulty reading the blackboard while sitting in the last row.", "concept_myopia", ["10.2"]) == "10.2"
    assert pick("Why do stars twinkle?", "concept_atmospheric_refraction", ["10.5"]) == "10.9"
    assert pick("Why do we prefer a convex mirror as a rear-view mirror in vehicles?", "concept_convex_ray_diagrams", ["9.2.2"]) == "9.8"
    assert pick("Draw a labelled diagram to explain the formation of a rainbow.", "concept_rainbow_formation", ["10.4"]) == "10.8"
    assert pick("Can I have another hint?", "concept_reflection_laws", ["9.1"]) is None


@needs_index
def test_cross_chapter_topic_change_never_shows_stale_figure_or_misconception():
    # Student asked about 1/v + 1/u = 1/f, then changed topic to electricity with 3.5 ohm and power:
    # A card for Section 11.8 (Electric Power) must never show Figure 9.9 even if concept_id was still concept_mirror_formula
    card = book.book_card(["11.8"], "and 3.5Ω to generate this much power how much V should I have", "concept_mirror_formula")
    assert card is not None
    assert card["section_id"] == "11.8"
    assert card["figure"] is None  # Section 11.8 has no figure; must not leak Chapter 9's Figure 9.9


def test_quiz_questions_and_flashcards_carry_a_figure_field():
    client = TestClient(app)
    for item in client.get("/api/quiz/questions").json()["items"]:
        assert "figure" in item and "answer" not in item
    cards = client.get("/api/flashcards").json()["items"]
    assert cards and all("figure" in c for c in cards)
