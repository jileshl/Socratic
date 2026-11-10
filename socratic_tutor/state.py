"""LangGraph state representation for Socratic Tutor.

Stores conversation history, learner profile snapshot, diagnostic traces,
active hints, and verification flags across turns.
"""

import operator
from typing import Annotated, Any, TypedDict
from langchain_core.messages import AnyMessage


class SocraticState(TypedDict, total=False):
    # --- Session & Identity ---------------------------------------------------
    session_id: str
    student_id: str                          # Pseudonymous UUID
    mode: str                                # "practice" | "quiz"
    current_concept_id: str | None
    current_question_id: str | None
    
    # --- Dialogue & History ---------------------------------------------------
    query: str
    messages: Annotated[list[AnyMessage], operator.add]
    steps: Annotated[list[str], operator.add] # Node execution trajectory
    turn_steps: list[str]                    # Current turn node execution (reset each turn)
    plan: list[str]                          # Current turn execution plan (e.g. ["diagnose", "hint"])
    
    # --- Learner Model Snapshot -----------------------------------------------
    mastery_map: dict[str, float]            # {concept_id: mastery_score}
    identified_misconception: dict | None    # {id, name, confidence}
    effective_lesson_applied: str | None     # Reflexion playbook lesson applied
    hint_step: int                           # 1..MAX_HINT_STEPS
    hint_tries: int                          # Re-try counter for hint generation on leak
    last_concept_id: str | None              # Track previous concept for hint ladder reset
    last_misconception_id: str | None        # Track previous misconception for hint ladder progression
    
    # --- Retrieval & Evidence -------------------------------------------------
    retrieved_sections: list[dict]           # NCERT section passages
    citations: list[str]                     # Passage/Section IDs cited
    
    # --- Solver & Math Grounding ----------------------------------------------
    student_attempt: str | None
    grade_result: dict | None                # {is_correct, feedback, score}
    
    # --- Safety & Teacher Gate ------------------------------------------------
    injection_detected: bool
    distress_detected: bool                  # Distress detected on current turn
    answer_leak_flag: bool                   # Triggered if practice response gave direct answer
    teacher_approval_required: bool
    teacher_approval_payload: dict | None    # Question proposal payload for interrupt()
    teacher_alert_triggered: bool            # Student stuck or in distress
    
    # --- Final Output ---------------------------------------------------------
    response: str
    next_recommended_concept: str | None
