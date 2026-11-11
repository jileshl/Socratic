"""Tests for textbook_kb.search_textbook's chapter and class filters (capstone guide p.11: "filtered by class and chapter").

Every test swaps textbook_kb.retriever for a HybridRetriever over 8 hand-written stand-in sections, with a
fake Chroma collection that finds nothing, so the ranking is BM25 only. No test reads the real index,
starts Chroma or downloads the embedding model. The stand-in texts are short made-up sentences, not NCERT text.
"""

from typing import Any

import pytest

from socratic_tutor.retrieval import HybridRetriever
from socratic_tutor.tools import textbook_kb


class FakeIndex:
    """Stand-in for NCERTIndex: just the list of sections, held in memory."""

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunks = chunks


class NoDenseHits:
    """Stand-in for the Chroma collection: it stores the texts it is given, and its search finds nothing."""

    def __init__(self) -> None:
        self.documents: dict[str, str] = {}

    def get(self, include: list[str]) -> dict[str, list[str]]:
        ids = list(self.documents)
        texts: list[str] = []
        for chunk_id in ids:
            texts.append(self.documents[chunk_id])
        return {"ids": ids, "documents": texts}

    def upsert(self, ids: list[str], documents: list[str]) -> None:
        for chunk_id, text in zip(ids, documents):
            self.documents[chunk_id] = text

    def delete(self, ids: list[str]) -> None:
        for chunk_id in ids:
            self.documents.pop(chunk_id, None)

    def query(self, query_texts: list[str], n_results: int, include: list[str]) -> dict[str, list[list[Any]]]:
        return {"ids": [[]], "distances": [[]]}


def section(class_num: str, chapter_num: str, chapter_title: str, section_id: str, title: str, content: str) -> dict[str, Any]:
    """One stand-in section with the same fields as a real chunk in .index/chunks.json."""
    return {
        "chunk_id": "fake_c" + class_num + "_ch" + chapter_num + "_sec_" + section_id.replace(".", "_"),
        "class_num": class_num,
        "subject": "Science",
        "chapter_num": chapter_num,
        "chapter_title": chapter_title,
        "section_id": section_id,
        "section_title": title,
        "content": content,
        "equations": [],
    }


LIGHT: str = "Light - Reflection and Refraction"
EYE: str = "Human Eye and the Colourful World"

# With the query below, BM25 ranks these 12.1, 9.3, 10.3, 10.5, 9.1, 9.3.2, 11.7, 9.2.1 (checked once by hand).
SECTIONS: list[dict[str, Any]] = [
    section("10", "9", LIGHT, "9.1", "Reflection of Light", "A polished surface such as a mirror reflects most of the light falling on it."),
    section("10", "9", LIGHT, "9.2.1", "Image Formation by Spherical Mirrors", "A concave mirror forms a real and inverted image of an object placed beyond its focus."),
    section("10", "9", LIGHT, "9.3", "Refraction of Light", "Light bends when it goes from air into glass, because light travels more slowly in glass."),
    section("10", "9", LIGHT, "9.3.2", "The Refractive Index", "The refractive index of glass tells how much the light changes direction at the surface."),
    section("10", "10", EYE, "10.3", "Refraction of Light Through a Prism", "A glass prism bends light when it goes in and again when it comes out into the air."),
    section("10", "10", EYE, "10.5", "Atmospheric Refraction", "Light from a star bends as it goes through layers of air of different density."),
    section("10", "11", "Electricity", "11.7", "Heating Effect of Electric Current", "The filament of a bulb glows because the electric current heats it."),
    # A made-up Class 9 section, so the class filter has something to remove.
    section("9", "12", "Class 9 stand-in", "12.1", "Light Bending (stand-in)", "Light bends when it goes from air into glass or water."),
]

QUERY: str = "why does light bend when it goes from air into glass"


@pytest.fixture
def fake_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point textbook_kb at the stand-in sections. search_textbook looks up `retriever` at call time."""
    monkeypatch.setattr(textbook_kb, "retriever", HybridRetriever(index=FakeIndex(SECTIONS), dense_collection=NoDenseHits()))


def section_ids(hits: list[dict[str, Any]]) -> list[str]:
    """Just the section ids, in order."""
    ids: list[str] = []
    for hit in hits:
        ids.append(hit["section_id"])
    return ids


def test_without_a_filter_the_search_is_unchanged(fake_index: None) -> None:
    """No chapter and no class: exactly what search_hybrid returns, as before the change."""
    expected = textbook_kb.retriever.search_hybrid(QUERY, top_k=3)
    assert textbook_kb.search_textbook(QUERY, top_k=3) == expected
    assert section_ids(expected) == ["12.1", "9.3", "10.3"]


def test_a_chapter_keeps_only_its_sections_in_ranking_order(fake_index: None) -> None:
    """chapter="9": the best Chapter 9 sections, in their ranking order, filled up to top_k.
    Without the filter, 12.1 and 10.3 (other chapters) would take two of the three places."""
    hits = textbook_kb.search_textbook(QUERY, chapter="9", top_k=3)
    assert section_ids(hits) == ["9.3", "9.1", "9.3.2"]


def test_a_class_keeps_only_that_class(fake_index: None) -> None:
    """class_num="10": the Class 9 stand-in (ranked first overall) is left out."""
    hits = textbook_kb.search_textbook(QUERY, top_k=3, class_num="10")
    assert section_ids(hits) == ["9.3", "10.3", "10.5"]


def test_chapter_and_class_together(fake_index: None) -> None:
    """Both filters at once: only Class 10, Chapter 10 sections."""
    hits = textbook_kb.search_textbook(QUERY, chapter="10", top_k=4, class_num="10")
    assert section_ids(hits) == ["10.3", "10.5"]


def test_an_unknown_chapter_gives_an_empty_list(fake_index: None) -> None:
    """Checking that the chapter exists is the MCP server's job; the function just finds nothing."""
    assert textbook_kb.search_textbook(QUERY, chapter="99") == []


def test_the_old_positional_call_still_works(fake_index: None) -> None:
    """class_num was added last, so a call written for the old signature, (query, chapter, top_k), still works."""
    assert section_ids(textbook_kb.search_textbook(QUERY, None, 2)) == ["12.1", "9.3"]


def test_a_chapter_stored_as_a_number_still_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    """The comparison is done as text, so a section whose chapter_num is the number 9 matches chapter="9"."""
    numeric = section("10", "9", LIGHT, "9.3", "Refraction of Light", "Light bends when it goes from air into glass.")
    numeric["chapter_num"] = 9
    monkeypatch.setattr(textbook_kb, "retriever", HybridRetriever(index=FakeIndex([numeric]), dense_collection=NoDenseHits()))
    assert section_ids(textbook_kb.search_textbook(QUERY, chapter="9")) == ["9.3"]


def test_an_empty_index_gives_an_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no sections loaded, a filtered search returns [] instead of failing."""
    monkeypatch.setattr(textbook_kb, "retriever", HybridRetriever(index=FakeIndex([]), dense_collection=NoDenseHits()))
    assert textbook_kb.search_textbook(QUERY, chapter="9") == []
