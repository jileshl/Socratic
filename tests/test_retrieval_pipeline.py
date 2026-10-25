"""Focused tests for NCERT section chunking and lexical retrieval."""

from socratic_tutor.kb import chunk_ncert_text
from socratic_tutor.retrieval import HybridRetriever


class _MemoryIndex:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks


def test_section_chunk_ids_are_stable() -> None:
    text = """
9.1 REFLECTION OF LIGHT
The angle of incidence equals the angle of reflection.
9.2 SPHERICAL MIRRORS
The centre of curvature and principal focus lie on the principal axis.
9.2.1 Image Formation by Spherical Mirrors
A concave mirror can form real or virtual images.
"""
    chunks = chunk_ncert_text(text, "9", "Light - Reflection and Refraction")

    assert [chunk.chunk_id for chunk in chunks] == [
        "ncert_c10_science_ch09_sec_9_1",
        "ncert_c10_science_ch09_sec_9_2",
        "ncert_c10_science_ch09_sec_9_2_1",
    ]
    assert chunks[0].section_id == "9.1"
    assert "angle of incidence" in chunks[0].content


def test_bm25_ranks_relevant_section_first() -> None:
    chunks = [
        {
            "chunk_id": "series",
            "chapter_title": "Electricity",
            "section_title": "Resistors in Series",
            "content": "The same current flows through each resistor in one series path.",
        },
        {
            "chunk_id": "parallel",
            "chapter_title": "Electricity",
            "section_title": "Resistors in Parallel",
            "content": "Parallel branches have the same voltage and branch current depends on resistance.",
        },
    ]
    retriever = HybridRetriever(index=_MemoryIndex(chunks))

    hits = retriever.search_hybrid("Does current split equally in parallel branches?", top_k=2)

    assert hits[0]["chunk_id"] == "parallel"
    assert hits[0]["rrf_score"] > 0
