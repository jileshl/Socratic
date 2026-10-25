"""Deterministic BM25 retrieval with Reciprocal Rank Fusion hooks."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from socratic_tutor import config
from socratic_tutor.index import NCERTIndex


_TOKEN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class HybridRetriever:
    def __init__(self, index: NCERTIndex | None = None):
        self.index = index or NCERTIndex()

    def search_bm25(self, query: str, top_k: int = 5) -> list[dict]:
        """Rank indexed NCERT chunks with BM25."""
        chunks = self.index.chunks
        if not chunks or top_k <= 0:
            return []

        documents = [
            _tokenize(
                " ".join(
                    [
                        chunk.get("chapter_title", ""),
                        chunk.get("section_title", ""),
                        chunk.get("content", ""),
                    ]
                )
            )
            for chunk in chunks
        ]
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        document_frequency: Counter[str] = Counter()
        term_frequencies: list[Counter[str]] = []
        for tokens in documents:
            frequencies = Counter(tokens)
            term_frequencies.append(frequencies)
            document_frequency.update(frequencies.keys())

        document_count = len(documents)
        average_length = sum(map(len, documents)) / document_count
        k1, b = 1.5, 0.75
        scores: list[tuple[float, int]] = []
        for index, tokens in enumerate(documents):
            score = 0.0
            frequencies = term_frequencies[index]
            length_normalizer = 1 - b + b * len(tokens) / max(average_length, 1.0)
            for term in query_tokens:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                df = document_frequency[term]
                inverse_document_frequency = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
                score += inverse_document_frequency * (
                    frequency * (k1 + 1) / (frequency + k1 * length_normalizer)
                )
            scores.append((score, index))

        ranked = sorted(scores, key=lambda item: (-item[0], chunks[item[1]]["chunk_id"]))
        return [dict(chunks[index], bm25_score=score) for score, index in ranked[:top_k]]

    def search_dense(self, query: str, top_k: int = 5) -> list[dict]:
        """Return dense results when embeddings are added to the persisted index."""
        # No embeddings are persisted yet. Empty results make this an explicit
        # BM25 baseline instead of reporting a fabricated hybrid score.
        return []

    def search_hybrid(self, query: str, top_k: int = 5, k: int = config.RRF_K) -> list[dict]:
        """Fuse available ranked lists using standard Reciprocal Rank Fusion."""
        ranked_lists = [
            self.search_bm25(query, top_k=max(top_k * 3, 10)),
            self.search_dense(query, top_k=max(top_k * 3, 10)),
        ]
        scores: defaultdict[str, float] = defaultdict(float)
        documents: dict[str, dict] = {}
        for ranked_list in ranked_lists:
            for rank, hit in enumerate(ranked_list, start=1):
                chunk_id = hit["chunk_id"]
                documents[chunk_id] = hit
                scores[chunk_id] += 1.0 / (k + rank)

        ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
        return [dict(documents[chunk_id], rrf_score=scores[chunk_id]) for chunk_id in ordered[:top_k]]

    def rerank(self, query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
        """Keep fused order until a separately evaluated reranker is configured."""
        return candidates[:top_k]
