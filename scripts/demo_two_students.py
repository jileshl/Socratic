"""Demonstration of Signature Challenge A: Two students asking the exact same question.

"Show how the tutor responds differently to two students asking the same question."
(README.md Signature Challenge A)

Both students ask: "Why is the image in a concave mirror upside down?"
- Student 1 (Novice): Has low mastery on reflection laws and an active misconception (MISCON_LIGHT_01).
- Student 2 (Advanced): Has mastered reflection laws and spherical mirrors.

The tutor's learner model and LangGraph supervisor route to divergent pedagogical strategies:
remedial prerequisite probing for Student 1 vs advanced geometric ray tracing for Student 2.
"""

from __future__ import annotations

import os
import uuid

# When running locally without API key, disable external Llama Guard model to allow local deterministic rules
if not os.getenv("OPENROUTER_API_KEY") and "GUARD_MODELS" not in os.environ:
    os.environ["GUARD_MODELS"] = "off"

from socratic_tutor import config
config.GUARD_MODELS = os.getenv("GUARD_MODELS", "off")

from socratic_tutor.concept_graph import ConceptGraph
from socratic_tutor.learner_store import LearnerStore
from socratic_tutor.graph import build_graph
from langgraph.checkpoint.memory import MemorySaver


def run_comparison(interactive: bool = True) -> dict[str, dict]:
    store = LearnerStore()
    checkpointer = MemorySaver()
    graph = build_graph(checkpointer=checkpointer)

    id_novice = f"demo_novice_{uuid.uuid4().hex[:6]}"
    id_advanced = f"demo_advanced_{uuid.uuid4().hex[:6]}"

    # Seed Novice profile: struggling on reflection laws, seeded misconception
    store.update_mastery(id_novice, "concept_reflection_laws", 0.20)
    store.update_mastery(id_novice, "concept_spherical_mirrors", 0.15)
    store.record_misconception(id_novice, "MISCON_LIGHT_01", resolved=False)
    store.record_quiz_result(id_novice, "concept_reflection_laws", 0.25)
    store.record_quiz_result(id_novice, "concept_reflection_laws", 0.30)

    # Seed Advanced profile: high mastery on prerequisites
    store.update_mastery(id_advanced, "concept_reflection_laws", 0.95)
    store.update_mastery(id_advanced, "concept_spherical_mirrors", 0.90)
    store.update_mastery(id_advanced, "concept_mirror_formula", 0.85)

    same_query = "Why is the image in a concave mirror upside down?"

    # Run Student 1 (Novice)
    sess_novice = f"sess_{id_novice}"
    state_novice = {
        "student_id": id_novice,
        "session_id": sess_novice,
        "query": same_query,
        "mode": "practice",
        "current_concept_id": "concept_spherical_mirrors",
    }
    out_novice = graph.invoke(state_novice, config={"configurable": {"thread_id": sess_novice}})

    # Run Student 2 (Advanced)
    sess_advanced = f"sess_{id_advanced}"
    state_advanced = {
        "student_id": id_advanced,
        "session_id": sess_advanced,
        "query": same_query,
        "mode": "practice",
        "current_concept_id": "concept_spherical_mirrors",
    }
    out_advanced = graph.invoke(state_advanced, config={"configurable": {"thread_id": sess_advanced}})

    results = {
        "novice": {
            "student_id": id_novice,
            "response": out_novice.get("response", ""),
            "citations": out_novice.get("citations", []),
            "misconception": out_novice.get("identified_misconception"),
            "next_concept": out_novice.get("next_recommended_concept"),
            "steps": out_novice.get("steps", []),
        },
        "advanced": {
            "student_id": id_advanced,
            "response": out_advanced.get("response", ""),
            "citations": out_advanced.get("citations", []),
            "misconception": out_advanced.get("identified_misconception"),
            "next_concept": out_advanced.get("next_recommended_concept"),
            "steps": out_advanced.get("steps", []),
        },
    }

    if interactive:
        print("=" * 80)
        print("SIGNATURE CHALLENGE A: TWO STUDENTS ASKING THE SAME QUESTION")
        print("=" * 80)
        print(f"QUERY: \"{same_query}\"\n")

        print("--------------------------------------------------------------------------------")
        print("STUDENT 1: NOVICE (Low mastery on reflection laws, active MISCON_LIGHT_01)")
        print("--------------------------------------------------------------------------------")
        print(f"Identified Misconception: {results['novice']['misconception']}")
        print(f"Citations: {results['novice']['citations']}")
        print(f"Next Concept: {results['novice']['next_concept']}")
        print(f"Tutor Response:\n{results['novice']['response']}\n")

        print("--------------------------------------------------------------------------------")
        print("STUDENT 2: ADVANCED (Mastered reflection laws 0.95, spherical mirrors 0.90)")
        print("--------------------------------------------------------------------------------")
        print(f"Identified Misconception: {results['advanced']['misconception']}")
        print(f"Citations: {results['advanced']['citations']}")
        print(f"Next Concept: {results['advanced']['next_concept']}")
        print(f"Tutor Response:\n{results['advanced']['response']}\n")
        print("=" * 80)

    # Clean up test profiles
    try:
        store.forget_student(id_novice, checkpointer=checkpointer)
        store.forget_student(id_advanced, checkpointer=checkpointer)
    except Exception:
        pass

    return results


if __name__ == "__main__":
    run_comparison(interactive=True)
