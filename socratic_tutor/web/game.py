"""Points, levels, badges and streaks for the student and teacher views.

Everything is worked out by code from records the tutor already keeps, so the student and
the teacher always see the same numbers and nothing is invented:

- the learner record (mastery by topic, mix-ups and whether they are sorted, quiz attempts)
- the ops store (how many messages the student sent, on which days)

Points (shown to students as "points"):
- 1 point per percentage point of mastery on every topic (a topic at 70% gives 70)
- 25 for every mix-up sorted
- 10 for every quiz answer that is fully correct
- 2 for every message to the tutor (practice counts, but less than results)

Flashcards are practised in the browser only, so they earn their own badge on the student's
device and are not part of the shared points.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from socratic_tutor import config

# (minimum points, level name). Names follow the chapters: from a spark to a rainbow.
LEVELS: list[tuple[int, str]] = [(0, "Spark"), (150, "Ray"), (400, "Beam"), (800, "Prism"), (1400, "Spectrum"), (2200, "Rainbow")]

BADGES: list[tuple[str, str, str]] = [
    ("first_question", "First question", "Ask the tutor anything"),
    ("quiz_starter", "Quiz starter", "Answer a quiz question"),
    ("bullseye", "Bullseye", "Get 3 quiz answers fully right"),
    ("myth_buster", "Myth buster", "Sort out a mix-up"),
    ("topic_master", "Topic master", "Master a topic (70% or more)"),
    ("explorer", "Chapter explorer", "Practise topics in all three chapters"),
    ("on_a_roll", "On a roll", "Learn on 3 days in a row"),
    ("plan_finisher", "Plan finisher", "Finish every topic on your teacher's plan"),
]


def _day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def streak(days: set[date], today: date | None = None) -> int:
    """Days in a row with any learning, ending today or yesterday (so it doesn't reset before you start today)."""
    today = today or datetime.now(timezone.utc).date()  # records are stored in UTC
    start = today if today in days else today - timedelta(days=1)
    count = 0
    while start - timedelta(days=count) in days:
        count += 1
    return count


def level_for(points: int) -> dict[str, Any]:
    index = max(i for i, (minimum, _) in enumerate(LEVELS) if points >= minimum)
    floor, name = LEVELS[index]
    nxt = LEVELS[index + 1] if index + 1 < len(LEVELS) else None
    return {
        "number": index + 1,
        "name": name,
        "floor": floor,
        "next_at": nxt[0] if nxt else None,
        "next_name": nxt[1] if nxt else None,
    }


def summary(profile: dict[str, Any], messages: int, message_days: list[str], chapters: dict[str, str], plan: dict[str, Any] | None) -> dict[str, Any]:
    passing = config.PASSING_MASTERY_THRESHOLD
    mastery: dict[str, float] = profile.get("mastery_map", {})
    quizzes = profile.get("quiz_history", [])
    misconceptions = [m for m in profile.get("misconceptions", []) if isinstance(m, dict)]

    mastered = sum(1 for v in mastery.values() if v >= passing)
    correct = sum(1 for q in quizzes if float(q.get("score") or 0) >= 1.0)
    sorted_mixups = sum(1 for m in misconceptions if m.get("resolved"))
    days = {d for d in (_day(t) for t in message_days) if d} | {d for d in (_day(q.get("created_at")) for q in quizzes) if d}
    in_a_row = streak(days)
    chapters_touched = {chapters.get(c) for c in mastery if chapters.get(c)}
    plan_items = (plan or {}).get("items") or []

    points = round(sum(v * 100 for v in mastery.values())) + 25 * sorted_mixups + 10 * correct + 2 * messages
    earned = {
        "first_question": messages >= 1,
        "quiz_starter": len(quizzes) >= 1,
        "bullseye": correct >= 3,
        "myth_buster": sorted_mixups >= 1,
        "topic_master": mastered >= 1,
        "explorer": len(chapters_touched) >= 3,
        "on_a_roll": in_a_row >= 3,
        "plan_finisher": bool(plan_items) and all(i.get("status") == "mastered" for i in plan_items),
    }
    return {
        "points": points,
        "level": level_for(points),
        "streak_days": in_a_row,
        "stats": {
            "messages": messages,
            "quiz_answers": len(quizzes),
            "quiz_correct": correct,
            "topics_mastered": mastered,
            "mixups_sorted": sorted_mixups,
            "active_days": len(days),
        },
        "badges": [{"id": key, "name": name, "how": how, "earned": earned[key]} for key, name, how in BADGES],
        "points_rule": "1 point per % of mastery on each topic, 25 per mix-up sorted, 10 per quiz answer fully right, 2 per message to the tutor.",
    }
