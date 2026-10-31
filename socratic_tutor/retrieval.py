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
    def __init__(self, index: NCERTIndex | None = None, dense_collection=None):
        self.index = index or NCERTIndex()
        self._dense_collection = dense_collection
        self._dense_index_signature: tuple[tuple[str, str], ...] | None = None

    @staticmethod
    def _chunk_text(chunk: dict) -> str:
        return "\n".join(
            value
            for value in (
                chunk.get("chapter_title", ""),
                chunk.get("section_title", ""),
                chunk.get("content", ""),
                " ".join(chunk.get("equations", [])),
            )
            if value
        )

    def _get_dense_collection(self):
        if self._dense_collection is None:
            try:
                import chromadb
            except ImportError as exc:  # pragma: no cover - environment-specific
                raise RuntimeError("Dense search requires chromadb; install requirements.txt") from exc

            client = chromadb.PersistentClient(path=str(config.INDEX_DIR / "chroma"))
            self._dense_collection = client.get_or_create_collection(
                name="ncert_sections",
                metadata={"hnsw:space": "cosine"},
            )
        return self._dense_collection

    def _sync_dense_collection(self, collection) -> dict[str, dict]:
        chunks_by_id = {chunk["chunk_id"]: chunk for chunk in self.index.chunks}
        signature = tuple(
            (chunk_id, self._chunk_text(chunk))
            for chunk_id, chunk in sorted(chunks_by_id.items())
        )
        if signature == self._dense_index_signature:
            return chunks_by_id

        existing = collection.get(include=["documents"])
        existing_documents = dict(zip(existing["ids"], existing.get("documents") or []))
        stale_ids = set(existing_documents) - set(chunks_by_id)
        if stale_ids:
            collection.delete(ids=sorted(stale_ids))

        changed_ids = [
            chunk_id
            for chunk_id, text in signature
            if existing_documents.get(chunk_id) != text
        ]
        if changed_ids:
            collection.upsert(
                ids=changed_ids,
                documents=[self._chunk_text(chunks_by_id[chunk_id]) for chunk_id in changed_ids],
            )
        self._dense_index_signature = signature
        return chunks_by_id

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
        """Rank indexed chunks by cosine distance between local embeddings."""
        if not query.strip() or top_k <= 0 or not self.index.chunks:
            return []

        collection = self._get_dense_collection()
        chunks_by_id = self._sync_dense_collection(collection)
        result = collection.query(
            query_texts=[query],
            n_results=min(top_k, len(chunks_by_id)),
            include=["distances"],
        )
        hit_ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        hits = []
        for chunk_id, distance in zip(hit_ids, distances):
            chunk = chunks_by_id.get(chunk_id)
            if chunk is not None:
                hits.append(dict(chunk, dense_score=1.0 - distance))
        return hits

    def search_hybrid(self, query: str, top_k: int = 5, k: int = config.RRF_K) -> list[dict]:
        """Fuse available ranked lists using standard Reciprocal Rank Fusion."""
        if top_k <= 0:
            return []
        if k <= 0:
            raise ValueError("RRF constant k must be positive")

        ranked_lists = [
            ("bm25", self.search_bm25(query, top_k=max(top_k * 3, 10))),
            ("dense", self.search_dense(query, top_k=max(top_k * 3, 10))),
        ]
        scores: defaultdict[str, float] = defaultdict(float)
        documents: dict[str, dict] = {}
        ranks: dict[str, dict[str, int]] = defaultdict(dict)
        for source, ranked_list in ranked_lists:
            for rank, hit in enumerate(ranked_list, start=1):
                chunk_id = hit["chunk_id"]
                documents[chunk_id] = {**documents.get(chunk_id, {}), **hit}
                ranks[chunk_id][source] = rank
                scores[chunk_id] += 1.0 / (k + rank)

        ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
        results = []
        for chunk_id in ordered[:top_k]:
            result = dict(documents[chunk_id], rrf_score=scores[chunk_id])
            for source, rank in ranks[chunk_id].items():
                result[f"{source}_rank"] = rank
            results.append(result)
        return results

    def rerank(self, query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
        """Keep fused order until a separately evaluated reranker is configured."""
        return candidates[:top_k]
