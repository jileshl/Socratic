"""Hybrid search (BM25 + Dense) with Reciprocal Rank Fusion (RRF) and reranking."""

from typing import Any
from socratic_tutor import config
from socratic_tutor.index import NCERTIndex


class HybridRetriever:
    def __init__(self, index: NCERTIndex | None = None):
        self.index = index or NCERTIndex()

    def search_bm25(self, query: str, top_k: int = 5) -> list[dict]:
        """Lexical search over NCERT chunk text."""
        # TODO (Milestone 2.1 / L5): Initialize rank_bm25.BM25Okapi over tokenized chunks
        # Return ranked hits with BM25 lexical scores
        return self.index.chunks[:top_k]

    def search_dense(self, query: str, top_k: int = 5) -> list[dict]:
        """Dense semantic search using vector similarity."""
        # TODO (Milestone 2.2 / L5): Compute query embedding using BGE-M3 or MiniLM
        # Execute cosine similarity against stored vector embeddings
        return self.index.chunks[:top_k]

    def search_hybrid(self, query: str, top_k: int = 5, k: int = config.RRF_K) -> list[dict]:
        """Combine BM25 and dense scores via Reciprocal Rank Fusion."""
        # TODO (Milestone 2.3 / L6): Implement standard RRF formula:
        # Score(d) = sum(1.0 / (k + rank_i(d))) across BM25 and Dense ranked lists
        bm25_hits = self.search_bm25(query, top_k=top_k * 2)
        dense_hits = self.search_dense(query, top_k=top_k * 2)
        
        # Combine & deduplicate
        combined = []
        seen = set()
        for hit in bm25_hits + dense_hits:
            cid = hit.get("chunk_id")
            if cid not in seen:
                seen.add(cid)
                combined.append(hit)
        return combined[:top_k]

    # TODO (Milestone 2.4 / L6): Add cross-encoder reranking over top-10 hybrid candidates
    def rerank(self, query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
        """Rerank candidates using a cross-encoder model (e.g. cross-encoder/ms-marco-MiniLM-L-6-v2)."""
        return candidates[:top_k]

