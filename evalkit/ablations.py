"""Experiment switches applied from the evaluation side, without editing agent code.

E2 turns the guardrails off, E3 turns the reviewed Reflexion lessons on or off,
and E4 turns learner memory off. Each switch temporarily replaces one function
the agents already call, for the duration of a run only. The deployed app is
never affected.

Patch points (tell R5 if you rename any of these):
    socratic_tutor.policy.check_input_guardrails / check_answer_leak      (R4)
    socratic_tutor.policy.check_reply (the reply check: links, citations, content guard) (R4)
    socratic_tutor.learner_store.LearnerStore read and write methods      (R2)
    socratic_tutor.reflexion.ReflexionPlaybook.get_lessons_for_misconception (R3)
"""

from __future__ import annotations

import sys
from contextlib import ExitStack, contextmanager
from typing import Any, Iterator

from socratic_tutor import policy
from socratic_tutor.learner_store import LearnerStore
from socratic_tutor.reflexion import ReflexionPlaybook


def _swap(stack: ExitStack, target: Any, name: str, replacement: Any) -> None:
    if not hasattr(target, name):
        return
    original = getattr(target, name)
    setattr(target, name, replacement)
    stack.callback(setattr, target, name, original)


def _pass_input(text: str) -> dict[str, Any]:
    return {"sanitized_query": text, "is_injection": False, "is_distress": False, "passed": True}


def _no_leak(*args: Any, **kwargs: Any) -> bool:
    return False


def _pass_reply(reply: str, citations: list[str], retrieved_ids: list[str], student_text: str = "") -> dict[str, Any]:
    """Defences off: the reply check lets the reply through unchanged (no link removal, no content guard)."""
    return {"reply": reply, "citations": citations, "links_removed": 0, "blocked_by": None}


def _empty_profile(self: Any, student_id: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"student_id": student_id, "mastery_map": {}, "misconceptions": [], "effective_lessons": [], "stuck_counter": 0}


def _ignore_write(self: Any, *args: Any, **kwargs: Any) -> None:
    return None


@contextmanager
def applied(defences: bool = True, memory: bool = True, playbook: bool = False) -> Iterator[None]:
    with ExitStack() as stack:
        if not defences:
            _swap(stack, policy, "check_input_guardrails", _pass_input)
            _swap(stack, policy, "check_answer_leak", _no_leak)
            # The reply check also counts as a defence (R4 plumbing PR-1 wired it into the graph's output node).
            _swap(stack, policy, "check_reply", _pass_reply)
            for module in list(sys.modules.values()):  # modules that did `from policy import ...`
                if module is not None and getattr(module, "__name__", "").startswith("socratic_tutor.") and module is not policy:
                    if getattr(module, "check_input_guardrails", None) is not None:
                        _swap(stack, module, "check_input_guardrails", _pass_input)
                    if getattr(module, "check_answer_leak", None) is not None:
                        _swap(stack, module, "check_answer_leak", _no_leak)
                    # graph.py does `from policy import check_reply`, so its own copy is switched off too.
                    if getattr(module, "check_reply", None) is not None:
                        _swap(stack, module, "check_reply", _pass_reply)
        if not memory:
            _swap(stack, LearnerStore, "get_profile", _empty_profile)
            for name in dir(LearnerStore):
                if name.startswith(("update_", "record_", "add_", "set_")):
                    _swap(stack, LearnerStore, name, _ignore_write)
        if not playbook:
            _swap(stack, ReflexionPlaybook, "get_lessons_for_misconception", lambda self, misconception_id: [])
        yield


def describe(defences: bool, memory: bool, playbook: bool) -> dict[str, str]:
    return {k: ("on" if v else "off") for k, v in {"defences": defences, "memory": memory, "playbook": playbook}.items()}
