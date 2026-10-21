"""Index persistence and management for hybrid BM25 + dense search."""

import json
from pathlib import Path
from socratic_tutor import config


class NCERTIndex:
    def __init__(self, index_dir: Path | None = None):
        self.index_dir = index_dir or config.INDEX_DIR
        self.chunks_path = self.index_dir / "chunks.json"
        self.chunks: list[dict] = []
        self.load()

    def load(self) -> None:
        if self.chunks_path.exists():
            with open(self.chunks_path, "r", encoding="utf-8") as f:
                self.chunks = json.load(f)

    def save(self, chunks: list[dict]) -> None:
        self.chunks = chunks
        self.index_dir.mkdir(parents=True, exist_ok=True)
        with open(self.chunks_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2)
