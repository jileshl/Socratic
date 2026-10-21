"""Concept Dependency Graph navigation and prerequisite management."""

import json
from pathlib import Path
from socratic_tutor import config


class ConceptGraph:
    def __init__(self, path: Path | None = None):
        self.path = path or (config.DATA_DIR / "concept_graph.json")
        self.concepts: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.concepts = {item["id"]: item for item in data.get("concepts", [])}

    def get_prerequisites(self, concept_id: str) -> list[str]:
        concept = self.concepts.get(concept_id)
        return concept.get("prerequisites", []) if concept else []

    def can_advance(self, concept_id: str, mastery_map: dict[str, float]) -> bool:
        """Check if all prerequisites meet the passing mastery threshold."""
        prereqs = self.get_prerequisites(concept_id)
        return all(mastery_map.get(p, 0.0) >= config.PASSING_MASTERY_THRESHOLD for p in prereqs)

    def next_recommended(self, mastery_map: dict[str, float]) -> str | None:
        """Find the earliest concept whose prerequisites are met but not yet mastered."""
        for cid, details in self.concepts.items():
            if mastery_map.get(cid, 0.0) < config.PASSING_MASTERY_THRESHOLD:
                if self.can_advance(cid, mastery_map):
                    return cid
        return None
