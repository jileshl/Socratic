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
    chapter: str | None
    concept_pinned: bool                     # True when the student picked this topic for this turn (Practise it)
    
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
    hint_raised_this_turn: bool              # Track whether hint was already escalated this turn
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
    distress_level: str                      # "none", "academic" or "severe" (from policy.check_input_guardrails)
    input_blocked_by: str | None             # Which input check stopped this turn, e.g. "word_rule:teacher_claim"
    output_blocked_by: str | None            # Which reply check replaced the reply (policy.check_reply), or None
    answer_leak_flag: bool                   # Triggered if practice response gave direct answer
    teacher_approval_required: bool
    question_set_size: int                   # How many questions the teacher asked the question setter for (PR-2)
    proposed_set: dict | None                # The set sent to the teacher: ok, set id, question ids, refusals; never a key
    teacher_alert_triggered: bool            # Student stuck or in distress
    
    # --- Final Output ---------------------------------------------------------
    response: str
    next_recommended_concept: str | None
