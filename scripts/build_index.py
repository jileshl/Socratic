"""Build a stable NCERT section index from locally supplied PDFs."""

from __future__ import annotations

import argparse
from pathlib import Path

from socratic_tutor import config
from socratic_tutor.index import NCERTIndex
from socratic_tutor.kb import chunk_ncert_pdf, extract_exemplar_problems


CHAPTERS = (
    ("9", "Light - Reflection and Refraction", "ch9-Light–Reflection-and-Refraction.pdf"),
    (
        "10",
        "Human Eye and the Colourful World",
        "ch10-The-Human-Eye-and-the-Colourful-World .pdf",
    ),
    ("11", "Electricity", "ch11-Electricity.pdf"),
)

EXEMPLARS = (
    ("9", ["exemplar_ch9.pdf"]),
    ("10", [ "exemplar_ch10.pdf" ]),
    ("11", ["exemplar_ch11"]),
)


def _read_source(source_dir: Path, filename: str) -> bytes:
    path = source_dir / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Set DOCUMENT_PATH or pass --source-dir with the "
            "directory containing the NCERT PDFs."
        )
    return path.read_bytes()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the NCERT section index")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=config.DOCUMENT_PATH,
        help="Directory containing the NCERT PDFs (default: DOCUMENT_PATH)",
    )
    parser.add_argument("--force", action="store_true", help="Replace any existing index")
    args = parser.parse_args()

    index = NCERTIndex()
    if index.chunks and not args.force:
        raise SystemExit("Index already exists; pass --force to replace it")

    chunks: list[dict] = []
    for chapter_num, chapter_title, filename in CHAPTERS:
        pdf_bytes = _read_source(args.source_dir, filename)
        chapter_chunks = chunk_ncert_pdf(pdf_bytes, chapter_num, chapter_title)
        if not chapter_chunks:
            raise RuntimeError(f"No sections extracted from {filename}")
        chunks.extend(chunk.to_dict() for chunk in chapter_chunks)
        print(f"Chapter {chapter_num}: extracted {len(chapter_chunks)} section chunks")

    chunk_ids = [chunk["chunk_id"] for chunk in chunks]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise RuntimeError("Generated duplicate chunk IDs")

    index.save(chunks)
    print(f"Indexed {len(chunks)} NCERT section chunks in {config.INDEX_DIR}.")

    # Ingest NCERT Exemplar problems if present in source_dir
    exemplars: list[dict] = []
    for chapter_num, candidate_filenames in EXEMPLARS:
        found_path = None
        for fn in candidate_filenames:
            p = args.source_dir / fn
            if p.exists():
                found_path = p
                break
        if found_path:
            pdf_bytes = found_path.read_bytes()
            extracted = extract_exemplar_problems(pdf_bytes, chapter_num)
            exemplars.extend(extracted)
            print(f"Chapter {chapter_num} Exemplar: extracted {len(extracted)} problems from {found_path.name}")
        else:
            print(f"Chapter {chapter_num} Exemplar: no exemplar PDF found (checked {candidate_filenames})")

    if exemplars:
        index.save_exemplars(exemplars)
        print(f"Saved {len(exemplars)} NCERT Exemplar problems in {index.exemplars_path}.")


if __name__ == "__main__":
    main()
