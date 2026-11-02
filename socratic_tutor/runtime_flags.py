"""Experiment switches shared by the app and the evaluation harness.

The evaluation harness runs the same code with different switches instead of
keeping a code branch per experiment (E2 defences, E3 playbook, E4 memory).
Every component reads its switch from here, so one config file controls a run.

    SOCRATIC_DEFENCES=on|off   input/output guardrails (E2)
    SOCRATIC_MEMORY=on|off     learner memory read/write (E4)
    SOCRATIC_PLAYBOOK=on|off   reviewed Reflexion lessons in the tutor (E3)

Contract for agent and tool code (R3/R4): call ``defences_on()``,
``memory_on()`` or ``playbook_on()`` at the point where the feature applies.
Defaults are "on", which is how the deployed app runs.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

_FLAGS = ("SOCRATIC_DEFENCES", "SOCRATIC_MEMORY", "SOCRATIC_PLAYBOOK")


def _is_on(name: str) -> bool:
    return os.getenv(name, "on").strip().lower() not in {"off", "0", "false", "no"}


def defences_on() -> bool:
    return _is_on("SOCRATIC_DEFENCES")


def memory_on() -> bool:
    return _is_on("SOCRATIC_MEMORY")


def playbook_on() -> bool:
    return _is_on("SOCRATIC_PLAYBOOK")


def snapshot() -> dict[str, str]:
    """Current switch values, recorded with every eval run."""
    return {name: ("on" if _is_on(name) else "off") for name in _FLAGS}


@contextmanager
def applied(defences: bool = True, memory: bool = True, playbook: bool = True) -> Iterator[None]:
    """Temporarily set the switches (used by the eval runner)."""
    wanted = {
        "SOCRATIC_DEFENCES": defences,
        "SOCRATIC_MEMORY": memory,
        "SOCRATIC_PLAYBOOK": playbook,
    }
    previous = {name: os.environ.get(name) for name in wanted}
    try:
        for name, value in wanted.items():
            os.environ[name] = "on" if value else "off"
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
