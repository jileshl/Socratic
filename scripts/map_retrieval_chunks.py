"""Map human-labelled NCERT section IDs to stable generated chunk IDs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from socratic_tutor import config


def main() -> None:
    parser = argparse.ArgumentParser(description="Add gold_chunk_ids to retrieval-query JSONL")
    parser.add_argument(
        "--queries",
        type=Path,
        default=config.DATA_DIR / "retrieval_queries.jsonl",
    )
    parser.add_argument("--index", type=Path, default=config.INDEX_DIR / "chunks.json")
    parser.add_argument("--output", type=Path, help="Output JSONL; defaults to replacing --queries")
    args = parser.parse_args()

    chunks = json.loads(args.index.read_text(encoding="utf-8"))
    lookup = {
        (chunk["chapter_title"], chunk["section_id"]): chunk["chunk_id"]
        for chunk in chunks
    }
    if len(lookup) != len(chunks):
        raise RuntimeError("Index contains duplicate chapter/section entries")

    records: list[dict] = []
    missing: list[str] = []
    for line_number, line in enumerate(args.queries.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        chunk_ids: list[str] = []
        for section_id in record["gold_section_ids"]:
            key = (record["chapter"], section_id)
            chunk_id = lookup.get(key)
            if chunk_id is None:
                missing.append(f"line {line_number}: {key}")
            else:
                chunk_ids.append(chunk_id)
        record["gold_chunk_ids"] = chunk_ids
        records.append(record)

    if missing:
        raise RuntimeError("Missing section chunks:\n" + "\n".join(missing))

    output = args.output or args.queries
    rendered = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    output.write_text(rendered, encoding="utf-8")
    print(f"Mapped {len(records)} queries to stable chunk IDs in {output}.")


if __name__ == "__main__":
    main()
