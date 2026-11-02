"""Evaluate Socratic Tutor development cases and retrieval benchmarks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evalkit.metrics import compute_recall_at_k
from socratic_tutor import config
from socratic_tutor.retrieval import HybridRetriever


def evaluate_retrieval(queries_path: Path, split: str, top_k: int, show: int) -> float:
    records = [
        json.loads(line)
        for line in queries_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records = [record for record in records if split == "all" or record["split"] == split]
    if not records:
        raise RuntimeError(f"No retrieval queries found for split={split!r}")

    retriever = HybridRetriever()
    if not retriever.index.chunks:
        raise RuntimeError("NCERT index is empty; run scripts/build_index.py first")

    scores: list[float] = []
    misses: list[tuple[str, float, list[str], list[str]]] = []
    for record in records:
        gold_ids = record.get("gold_chunk_ids")
        if not gold_ids:
            raise RuntimeError(
                f"{record['id']} has no gold_chunk_ids; run scripts/map_retrieval_chunks.py"
            )
        hits = retriever.search_hybrid(record["query"], top_k=top_k)
        retrieved_ids = [hit["chunk_id"] for hit in hits]
        recall = compute_recall_at_k(retrieved_ids, gold_ids, k=top_k)
        scores.append(recall)
        if recall < 1.0:
            misses.append((record["id"], recall, gold_ids, retrieved_ids))

    mean_recall = sum(scores) / len(scores)
    print("Retrieval backend: BM25 with RRF plumbing (dense index not yet implemented)")
    print(f"Queries: {len(records)} ({split})")
    print(f"Recall@{top_k}: {mean_recall:.4f}")
    print(f"Perfect-recall queries: {sum(score == 1.0 for score in scores)}/{len(scores)}")
    for query_id, recall, gold_ids, retrieved_ids in misses[:show]:
        print(f"MISS {query_id}: recall={recall:.2f}")
        print(f"  gold={gold_ids}")
        print(f"  got ={retrieved_ids}")
    return mean_recall


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate development datasets")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--show", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--split", choices=("dev", "held_out", "all"), default="dev")
    parser.add_argument(
        "--queries",
        type=Path,
        default=config.DATA_DIR / "retrieval_queries.jsonl",
    )
    args = parser.parse_args()

    if args.retrieval_only:
        evaluate_retrieval(args.queries, args.split, args.top_k, args.show)
        return

    raise SystemExit(
        "End-to-end evaluation now lives in the evaluation harness:\n"
        "  python -m evalkit.runner --config eval/configs/e1_c2.yaml --split dev\n"
        "See docs/EVALUATION_GUIDE.md."
    )


if __name__ == "__main__":
    main()
