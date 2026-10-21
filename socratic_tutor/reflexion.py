"""Reflexion improvement loop for distilling teaching lessons from student sessions."""

import json
from pathlib import Path
from socratic_tutor import config


class ReflexionPlaybook:
    def __init__(self, path: Path | None = None):
        self.path = path or (config.DATA_DIR / "reflexion_playbook.json")
        self.lessons: list[dict] = []
        self.load()

    def load(self) -> None:
        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                self.lessons = json.load(f)

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.lessons, f, indent=2)

    def get_lessons_for_misconception(self, misconception_id: str) -> list[str]:
        return [
            item["lesson"] for item in self.lessons 
            if item.get("misconception_id") == misconception_id and item.get("approved_by_human", False)
        ]

    def add_candidate_lesson(self, misconception_id: str, lesson_text: str, rationale: str) -> None:
        self.lessons.append({
            "misconception_id": misconception_id,
            "lesson": lesson_text,
            "rationale": rationale,
            "approved_by_human": False
        })
        self.save()
