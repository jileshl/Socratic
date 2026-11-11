"""Reflexion improvement loop for distilling teaching lessons from student sessions."""

import json
import uuid
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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.lessons, f, indent=2)

    def get_lessons_for_misconception(self, misconception_id: str) -> list[str]:
        return [
            item["lesson"]
            for item in self.lessons
            if item.get("misconception_id") == misconception_id and item.get("approved_by_human", False)
        ]

    def add_candidate_lesson(
        self,
        misconception_id: str,
        lesson_text: str,
        rationale: str,
        approved_by_human: bool = False,
        lesson_id: str | None = None,
        rejection_reason: str | None = None,
    ) -> str:
        lid = lesson_id or f"LESSON_{misconception_id}_{uuid.uuid4().hex[:6]}"
        for item in self.lessons:
            if item.get("lesson_id") == lid or (item.get("misconception_id") == misconception_id and item.get("lesson") == lesson_text):
                item["lesson"] = lesson_text
                item["rationale"] = rationale
                item["approved_by_human"] = approved_by_human
                if rejection_reason:
                    item["rejection_reason"] = rejection_reason
                self.save()
                return str(item.get("lesson_id", lid))

        self.lessons.append({
            "lesson_id": lid,
            "misconception_id": misconception_id,
            "lesson": lesson_text,
            "rationale": rationale,
            "approved_by_human": approved_by_human,
            "rejection_reason": rejection_reason,
        })
        self.save()
        return lid

    def approve_lesson(self, lesson_id: str) -> bool:
        for item in self.lessons:
            if item.get("lesson_id") == lesson_id:
                item["approved_by_human"] = True
                item["rejection_reason"] = None
                self.save()
                return True
        return False

    def reject_lesson(self, lesson_id: str, reason: str) -> bool:
        for item in self.lessons:
            if item.get("lesson_id") == lesson_id:
                item["approved_by_human"] = False
                item["rejection_reason"] = reason
                self.save()
                return True
        return False

    def get_approved_lessons(self) -> list[dict]:
        return [item for item in self.lessons if item.get("approved_by_human")]

    def get_rejected_lessons(self) -> list[dict]:
        return [item for item in self.lessons if not item.get("approved_by_human") and item.get("rejection_reason")]

