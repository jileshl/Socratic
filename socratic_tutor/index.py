"""Index persistence and management for hybrid BM25 + dense search."""

import json
from pathlib import Path
from socratic_tutor import config


class NCERTIndex:
    def __init__(self, index_dir: Path | None = None):
        self.index_dir = index_dir or config.INDEX_DIR
        self.chunks_path = self.index_dir / "chunks.json"
        self.exemplars_path = self.index_dir / "exemplars.json"
        self.chunks: list[dict] = []
        self.exemplars: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if self.chunks_path.exists():
            with open(self.chunks_path, "r", encoding="utf-8") as f:
                self.chunks = json.load(f)
        if self.exemplars_path.exists():
            with open(self.exemplars_path, "r", encoding="utf-8") as f:
                raw_ex = json.load(f)
                if isinstance(raw_ex, list):
                    self.exemplars = {item["exemplar_id"]: item for item in raw_ex if "exemplar_id" in item}
                elif isinstance(raw_ex, dict):
                    self.exemplars = raw_ex

    def save(self, chunks: list[dict]) -> None:
        self.chunks = chunks
        self.index_dir.mkdir(parents=True, exist_ok=True)
        with open(self.chunks_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2)

    def save_exemplars(self, exemplars: list[dict]) -> None:
        self.exemplars = {item["exemplar_id"]: item for item in exemplars if "exemplar_id" in item}
        self.index_dir.mkdir(parents=True, exist_ok=True)
        with open(self.exemplars_path, "w", encoding="utf-8") as f:
            json.dump(exemplars, f, indent=2)
