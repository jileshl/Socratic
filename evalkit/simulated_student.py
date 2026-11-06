"""Simulated students played by an LLM from a hidden card (signature challenge B).

The card (data/simulated_students.jsonl) holds a knowledge
state, one or two seeded misconceptions from data/misconceptions.json, a persona,
patience, and the condition under which each misconception is dropped. The tutor
never sees the card.

Quiz answers are multiple choice and scored by code. Options are shuffled per
student and item with a fixed seed, so a position bias in the model (for
example always picking A) cannot inflate scores.

Limits (state these in the report): a simulated student is not a real student.
Its "learning" is the model's judgement that the card's condition was met.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from typing import Any

from evalkit import datasets, llm_client, prompts
from socratic_tutor import config


@dataclass
class StudentProfileCard:
    student_id: str
    persona_type: str
    knowledge_state: dict[str, float]
    seeded_misconceptions: list[str]
    archetype: str = "unspecified"
    voice: str = ""
    convinced_when: dict[str, str] = field(default_factory=dict)
    opening_message: str = ""
    practice_problem: dict[str, Any] = field(default_factory=dict)
    pre_quiz: list[str] = field(default_factory=list)
    post_quiz: list[str] = field(default_factory=list)
    patience_turns: int = 5
    split: str = "dev"

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "StudentProfileCard":
        known = {k: record[k] for k in cls.__dataclass_fields__ if k in record}
        return cls(**known)


def _shuffle(student_id: str, item_id: str, phase: str) -> list[str]:
    seed = int(hashlib.sha256(f"{student_id}|{item_id}|{phase}".encode()).hexdigest()[:8], 16)
    letters = ["A", "B", "C", "D"]
    random.Random(seed).shuffle(letters)
    return letters  # letters[i] is the original option shown in position i


class SimulatedStudentAgent:
    def __init__(self, card: StudentProfileCard, callbacks: list | None = None):
        self.card = card
        self.callbacks = callbacks or []
        self.turns_elapsed = 0
        self.done = False
        miscs = datasets.misconceptions()
        self._beliefs = "; ".join(f"{miscs[m]['name']} ({miscs[m]['description']})" for m in card.seeded_misconceptions)
        self._template = prompts.SIMULATED_STUDENT

    def _system(self, task: str, fmt: str) -> str:
        return self._template.format(
            persona_type=self.card.persona_type,
            voice=self.card.voice,
            archetype=prompts.ARCHETYPES.get(self.card.archetype, prompts.ARCHETYPES["unspecified"]),
            knowledge_state=json.dumps(self.card.knowledge_state),
            misconception_beliefs=self._beliefs,
            convinced_when="; ".join(self.card.convinced_when.values()),
            patience_turns=self.card.patience_turns,
            task=task,
            format=fmt,
        )

    def _ask(self, system: str, user: str) -> str:
        return llm_client.chat(
            config.SIMULATED_STUDENT_MODEL,
            system,
            user,
            config.SIMULATED_STUDENT_TEMPERATURE,
            role="simulated_student",
            callbacks=self.callbacks,
        )

    # ------------------------------------------------------------------ quiz

    def answer_quiz(self, item_id: str, phase: str, transcript: str = "") -> dict[str, Any]:
        """Answer one multiple-choice item. phase: 'pre' or 'post'. Scored in code."""
        item = datasets.quiz_bank()[item_id]
        order = _shuffle(self.card.student_id, item_id, phase)
        shown = {pos: item["options"][orig] for pos, orig in zip("ABCD", order)}
        to_shown = {orig: pos for pos, orig in zip("ABCD", order)}
        lines = "\n".join(f"{pos}) {text}" for pos, text in shown.items())
        if phase == "pre":
            task = "Answer this short quiz question before your tutoring session, honestly, using only what you currently believe and know."
        else:
            task = (
                "Your tutoring session has just ended. Answer this quiz question honestly, using what you believe now. "
                "If the session changed your mind (because the condition on your card really happened), answer with your new understanding; otherwise answer as before.\n\n"
                f"Your session:\n{transcript}"
            )
        user = f"QUIZ PHASE: {phase.upper()}\n{item['stem']}\n{lines}"
        if llm_client.stub_mode():  # the stand-in needs to know which shown letter maps to what
            user += f"\nMISCONCEPTION OPTION: {to_shown[item['misconception_option']]}\nCORRECT OPTION FOR STUB: {to_shown[item['correct']]}"
        raw = self._ask(self._system(task, "Reply with a single letter: A, B, C or D. Nothing else."), user)
        match = re.search(r"\b([ABCD])\b", raw.strip().upper())
        chosen_shown = match.group(1) if match else None
        chosen_original = order["ABCD".index(chosen_shown)] if chosen_shown else None
        return {
            "item_id": item_id,
            "phase": phase,
            "chosen": chosen_original,
            "correct": chosen_original == item["correct"],
            "picked_misconception_option": chosen_original == item["misconception_option"],
            "raw": raw[:40],
        }

    # ------------------------------------------------------------------ dialogue

    def opening(self, problem_text: str) -> str:
        return f"{self.card.opening_message}\n\nThe question I'm working on: {problem_text}"

    def respond_to_hint(self, tutor_hint: str, transcript: str = "") -> str:
        """Reply to the tutor in character. Sets ``done`` when the student finishes."""
        self.turns_elapsed += 1
        out_of_patience = self.turns_elapsed >= self.card.patience_turns
        task = (
            "Continue the tutoring conversation as the student. Reply to the tutor's latest message."
            + (" You are running out of patience: wrap up in this message and end it with [DONE]." if out_of_patience else "")
        )
        user = f"Conversation so far:\n{transcript}\n\nTutor's latest message: {tutor_hint}"
        reply = self._ask(self._system(task, "One short chat message from the student (1-3 sentences)."), user).strip()
        if "[DONE]" in reply or out_of_patience:
            self.done = True
        return reply.replace("[DONE]", "").strip() or "ok"
