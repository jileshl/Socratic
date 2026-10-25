"""Build a stable NCERT section index from local PDFs or a temporary Git source."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from socratic_tutor import config
from socratic_tutor.index import NCERTIndex
from socratic_tutor.kb import chunk_ncert_pdf


CHAPTERS = (
    ("9", "Light - Reflection and Refraction", "ch9-Light–Reflection-and-Refraction.pdf"),
    (
        "10",
        "Human Eye and the Colourful World",
        "ch10-The-Human-Eye-and-the-Colourful-World .pdf",
    ),
    ("11", "Electricity", "ch11-Electricity.pdf"),
)


def _read_source(source_dir: Path, filename: str, git_revision: str | None) -> bytes:
    if git_revision:
        repo_root = Path(__file__).resolve().parent.parent
        tree = subprocess.run(
            ["git", "ls-tree", "-r", "-z", git_revision, "--", "data"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
        target = f"data/{filename}"
        blob_id: str | None = None
        for entry in tree.stdout.split(b"\0"):
            if not entry:
                continue
            metadata, encoded_path = entry.split(b"\t", maxsplit=1)
            if encoded_path.decode("utf-8") == target:
                blob_id = metadata.split()[2].decode("ascii")
                break
        if blob_id is None:
            raise FileNotFoundError(f"{target} not found at Git revision {git_revision}")
        blob = subprocess.run(
            ["git", "cat-file", "blob", blob_id],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
        return blob.stdout

    path = source_dir / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Keep source PDFs outside Git and pass --source-dir, "
            "or use --git-revision only while the old PDF commit remains available."
        )
    return path.read_bytes()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the NCERT section index")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=config.DATA_DIR / "source_pdfs",
        help="Untracked directory containing the three NCERT chapter PDFs",
    )
    parser.add_argument(
        "--git-revision",
        help="Read PDFs from data/ at this Git revision without checking them out",
    )
    parser.add_argument("--force", action="store_true", help="Replace any existing index")
    args = parser.parse_args()

    index = NCERTIndex()
    if index.chunks and not args.force:
        raise SystemExit("Index already exists; pass --force to replace it")

    chunks: list[dict] = []
    for chapter_num, chapter_title, filename in CHAPTERS:
        pdf_bytes = _read_source(args.source_dir, filename, args.git_revision)
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


if __name__ == "__main__":
    main()
