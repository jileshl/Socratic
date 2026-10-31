"""Deterministic BM25 retrieval with Reciprocal Rank Fusion hooks."""

from __future__ import annotations

import re
from collections import defaultdict

from rank_bm25 import BM25Okapi

from socratic_tutor import config
from socratic_tutor.index import NCERTIndex


_TOKEN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


_QUERY_REWRITES = (
    (
        re.compile(r"\b(pencil|straw)\b.{0,50}\b(bent|broken|shifted|displaced)\b|\b(bent|broken)\b.{0,40}\b(glass|water)\b", re.I),
        "refraction light air water interface apparent displacement",
    ),
    (
        re.compile(r"\b(near[- ]sighted|myopia|distant.{0,20}blur)\b", re.I),
        "myopia concave lens distant vision far point",
    ),
    (
        re.compile(
            r"\b(current|charge)\b.{0,80}\b(split|divide|branches)\b|"
            r"\bparallel\b.{0,100}\b(current|voltage)\b|"
            r"\b(current|voltage)\b.{0,100}\bparallel\b",
            re.I,
        ),
        "resistors in parallel branch current potential difference",
    ),
    (
        re.compile(r"\b(2f1|2f)\b.{0,50}\b(convex lens|lens|image)\b", re.I),
        "convex lens image formation ray diagram object position size",
    ),
)


class HybridRetriever:
    def __init__(self, index: NCERTIndex | None = None, dense_collection=None):
        self.index = index or NCERTIndex()
        self._dense_collection = dense_collection
        self._dense_index_signature: tuple[tuple[str, str], ...] | None = None
        self._bm25_signature: tuple[tuple[str, str], ...] | None = None
        self._bm25_index: BM25Okapi | None = None
        self._reranker = None

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

    @staticmethod
    def rewrite_query(query: str) -> str:
        """Append textbook vocabulary for a small set of common colloquial queries."""
        additions = [terms for pattern, terms in _QUERY_REWRITES if pattern.search(query)]
        if not additions:
            return query
        return f"{query} {' '.join(additions)}"

    def _get_bm25_index(self, chunks: list[dict]) -> BM25Okapi | None:
        signature = tuple(
            (chunk["chunk_id"], self._chunk_text(chunk))
            for chunk in chunks
        )
        if signature != self._bm25_signature:
            tokenized_documents = [_tokenize(text) for _, text in signature]
            self._bm25_index = BM25Okapi(tokenized_documents) if any(tokenized_documents) else None
            self._bm25_signature = signature
        return self._bm25_index

    def search_bm25(self, query: str, top_k: int = 5) -> list[dict]:
        """Rank indexed NCERT chunks with BM25."""
        chunks = self.index.chunks
        if not chunks or top_k <= 0:
            return []
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        bm25_index = self._get_bm25_index(chunks)
        if bm25_index is None:
            return []
        scores = bm25_index.get_scores(query_tokens)
        ranked = sorted(range(len(chunks)), key=lambda index: (-scores[index], chunks[index]["chunk_id"]))
        return [dict(chunks[index], bm25_score=float(scores[index])) for index in ranked[:top_k]]

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

    def search_hybrid(
        self,
        query: str,
        top_k: int = 5,
        k: int = config.RRF_K,
        rewrite: bool = True,
        rerank: bool = False,
    ) -> list[dict]:
        """Fuse available ranked lists using standard Reciprocal Rank Fusion."""
        if top_k <= 0:
            return []
        if k <= 0:
            raise ValueError("RRF constant k must be positive")

        retrieval_query = self.rewrite_query(query) if rewrite else query

        ranked_lists = [
            ("bm25", self.search_bm25(retrieval_query, top_k=max(top_k * 3, 10))),
            ("dense", self.search_dense(retrieval_query, top_k=max(top_k * 3, 10))),
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
        candidate_limit = max(top_k * 3, 10)
        for chunk_id in ordered[:candidate_limit]:
            result = dict(documents[chunk_id], rrf_score=scores[chunk_id])
            for source, rank in ranks[chunk_id].items():
                result[f"{source}_rank"] = rank
            results.append(result)
        if rerank:
            return self.rerank(query, results, top_k=top_k)
        return results[:top_k]

    def rerank(self, query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
        """Rerank candidates with an optional CPU cross-encoder model."""
        if top_k <= 0 or not candidates:
            return []
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError(
                    "Cross-encoder reranking requires sentence-transformers; "
                    "install requirements-reranker.txt"
                ) from exc
            model_name = config.RERANKER_MODEL
            self._reranker = CrossEncoder(model_name, device="cpu")

        pairs = [[query, self._chunk_text(candidate)] for candidate in candidates]
        scores = self._reranker.predict(pairs, show_progress_bar=False)
        ranked = sorted(
            zip(scores, candidates),
            key=lambda item: (-float(item[0]), item[1]["chunk_id"]),
        )
        return [dict(candidate, reranker_score=float(score)) for score, candidate in ranked[:top_k]]
