"""Study plans: the teacher's assigned plan plus a suggestion worked out by code.

The suggestion is deterministic (no model call). It reads the student's learner record and
the concept graph (data/concept_graph.json) and is recomputed on every request, so it changes
after every quiz:

1. Mix-ups still open: the topic of each unresolved misconception comes first.
2. Weak topics: anything practised but below the passing mastery. If a topic it builds on
   is also below passing, that earlier topic is listed first ("fix the foundation first",
   the same rule the supervisor uses after three failed quizzes).
3. Next new topic: the first topic not started whose prerequisites are all mastered, in a
   chapter the student is already working on (otherwise ConceptGraph.next_recommended).

The teacher can accept the suggestion, change the order, add or remove topics, add a note
and a due date. The assigned plan is stored in the ops store (study_plans) and deleted with
"Delete my data".
"""

from __future__ import annotations

from typing import Any

from socratic_tutor import config
from socratic_tutor.concept_graph import ConceptGraph

MAX_SUGGESTIONS = 5
_graph: ConceptGraph | None = None


def concept_graph() -> ConceptGraph:
    global _graph
    if _graph is None:
        _graph = ConceptGraph()
    return _graph


def status_of(mastery: dict[str, float], concept_id: str) -> str:
    if concept_id not in mastery:
        return "not_started"
    return "mastered" if mastery[concept_id] >= config.PASSING_MASTERY_THRESHOLD else "in_progress"


def suggest(mastery: dict[str, float], open_misconceptions: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Up to five topics, each with the reason it was chosen. Code only, no model."""
    graph = concept_graph()
    passing = config.PASSING_MASTERY_THRESHOLD
    out: list[dict[str, str]] = []

    def add(concept_id: str | None, reason: str) -> None:
        if concept_id and concept_id in graph.concepts and all(o["concept_id"] != concept_id for o in out):
            out.append({"concept_id": concept_id, "reason": reason})

    def weak_prerequisites(concept_id: str) -> list[str]:
        return [p for p in graph.get_prerequisites(concept_id) if mastery.get(p, 0.0) < passing and p in mastery]

    for item in open_misconceptions:
        concept_id = item.get("concept_id")
        if concept_id and mastery.get(concept_id, 0.0) < passing:
            for prereq in weak_prerequisites(concept_id):
                add(prereq, f"Comes before {graph.concepts[concept_id].get('title', concept_id)}, which is still shaky")
            add(concept_id, f"Mix-up to sort out: {item.get('name', 'a common mix-up')}")

    for concept_id, score in sorted(mastery.items(), key=lambda kv: kv[1]):
        if score < passing:
            for prereq in weak_prerequisites(concept_id):
                add(prereq, f"Comes before {graph.concepts.get(concept_id, {}).get('title', concept_id)}, which is still shaky")
            add(concept_id, f"Practised, {round(score * 100)}% so far; passing is {round(passing * 100)}%")

    add(_next_new_topic(graph, mastery), "Next new topic: everything it builds on is mastered")
    return out[:MAX_SUGGESTIONS]


def _next_new_topic(graph: ConceptGraph, mastery: dict[str, float]) -> str | None:
    """ConceptGraph.next_recommended, but staying in a chapter the student is already working on."""
    chapters = {graph.concepts[c].get("chapter") for c in mastery if c in graph.concepts}
    for cid, details in graph.concepts.items():
        if details.get("chapter") in chapters and cid not in mastery and graph.can_advance(cid, mastery):
            return cid
    return graph.next_recommended(mastery)


def describe(concept_id: str, mastery: dict[str, float], quiz_concepts: set[str], reason: str = "") -> dict[str, Any]:
    info = concept_graph().concepts.get(concept_id, {})
    return {
        "concept_id": concept_id,
        "title": info.get("title", concept_id),
        "chapter": info.get("chapter", ""),
        "mastery": round(float(mastery.get(concept_id, 0.0)), 2),
        "status": status_of(mastery, concept_id),
        "has_quiz": concept_id in quiz_concepts,
        "reason": reason,
    }


def view(
    mastery: dict[str, float],
    open_misconceptions: list[dict[str, Any]],
    assigned: dict[str, Any] | None,
    quiz_concepts: set[str],
) -> dict[str, Any]:
    """What the student (and the teacher) see: the assigned plan with live status, and the suggestion."""
    assigned_ids = list((assigned or {}).get("concepts") or [])
    suggestion = [s for s in suggest(mastery, open_misconceptions) if s["concept_id"] not in assigned_ids]
    assigned_items = [describe(c, mastery, quiz_concepts) for c in assigned_ids if c in concept_graph().concepts]
    suggested_items = [describe(s["concept_id"], mastery, quiz_concepts, s["reason"]) for s in suggestion]
    done = sum(1 for item in assigned_items if item["status"] == "mastered")
    next_up = next((i for i in assigned_items if i["status"] != "mastered"), None) or (suggested_items[0] if suggested_items else None)
    return {
        "assigned": (
            {"items": assigned_items, "note": assigned.get("note", ""), "due": assigned.get("due"), "updated_at": assigned.get("updated_at"), "done": done}
            if assigned and assigned_ids
            else None
        ),
        "suggested": suggested_items,
        "next_up": next_up,
        "passing": config.PASSING_MASTERY_THRESHOLD,
    }
