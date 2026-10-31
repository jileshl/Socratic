"""Focused tests for NCERT section chunking and lexical retrieval."""

from socratic_tutor.kb import chunk_ncert_text
from socratic_tutor.retrieval import HybridRetriever


class _MemoryIndex:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks


class _MemoryCollection:
    def __init__(self, ranked_ids: list[str], distances: list[float]):
        self.documents: dict[str, str] = {}
        self.ranked_ids = ranked_ids
        self.distances = distances

    def get(self, include: list[str]) -> dict:
        ids = list(self.documents)
        return {"ids": ids, "documents": [self.documents[chunk_id] for chunk_id in ids]}

    def upsert(self, ids: list[str], documents: list[str]) -> None:
        self.documents.update(zip(ids, documents))

    def delete(self, ids: list[str]) -> None:
        for chunk_id in ids:
            self.documents.pop(chunk_id, None)

    def query(self, query_texts: list[str], n_results: int, include: list[str]) -> dict:
        return {
            "ids": [self.ranked_ids[:n_results]],
            "distances": [self.distances[:n_results]],
        }


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


def test_dense_search_syncs_chunk_text_and_returns_cosine_score() -> None:
    chunks = [
        {
            "chunk_id": "refraction",
            "chapter_title": "Light",
            "section_title": "Refraction",
            "content": "Light bends when it enters glass.",
            "equations": ["n = c/v"],
        },
        {
            "chunk_id": "reflection",
            "chapter_title": "Light",
            "section_title": "Reflection",
            "content": "The angle of incidence equals the angle of reflection.",
        },
    ]
    collection = _MemoryCollection(["refraction", "reflection"], [0.12, 0.4])
    retriever = HybridRetriever(index=_MemoryIndex(chunks), dense_collection=collection)

    hits = retriever.search_dense("Why does light bend in glass?", top_k=2)

    assert [hit["chunk_id"] for hit in hits] == ["refraction", "reflection"]
    assert hits[0]["dense_score"] == 0.88
    assert "n = c/v" in collection.documents["refraction"]


def test_dense_search_handles_empty_queries_without_indexing() -> None:
    collection = _MemoryCollection([], [])
    retriever = HybridRetriever(index=_MemoryIndex([]), dense_collection=collection)

    assert retriever.search_dense("  ") == []
    assert collection.documents == {}


def test_hybrid_search_fuses_overlapping_and_unique_results() -> None:
    shared = {"chunk_id": "shared", "content": "Found by both retrievers."}
    lexical_only = {"chunk_id": "lexical", "content": "Found by BM25."}
    dense_only = {"chunk_id": "semantic", "content": "Found by dense search."}
    retriever = HybridRetriever(index=_MemoryIndex([]))
    retriever.search_bm25 = lambda query, top_k: [
        dict(lexical_only, bm25_score=2.5),
        dict(shared, bm25_score=1.5),
    ]
    retriever.search_dense = lambda query, top_k: [
        dict(dense_only, dense_score=0.9),
        dict(shared, dense_score=0.8),
    ]

    hits = retriever.search_hybrid("student question", top_k=3, k=60)
    by_id = {hit["chunk_id"]: hit for hit in hits}

    assert set(by_id) == {"shared", "lexical", "semantic"}
    assert hits[0]["chunk_id"] == "shared"
    assert abs(by_id["shared"]["rrf_score"] - 2 / 62) < 1e-12
    assert by_id["shared"]["bm25_score"] == 1.5
    assert by_id["shared"]["dense_score"] == 0.8
    assert by_id["shared"]["bm25_rank"] == 2
    assert by_id["shared"]["dense_rank"] == 2
    assert by_id["lexical"]["bm25_rank"] == 1
    assert by_id["semantic"]["dense_rank"] == 1


def test_hybrid_search_validates_top_k_and_rrf_constant() -> None:
    retriever = HybridRetriever(index=_MemoryIndex([]))

    assert retriever.search_hybrid("query", top_k=0) == []
    try:
        retriever.search_hybrid("query", k=0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("Expected non-positive RRF constant to be rejected")
