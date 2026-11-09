"""Every evaluation experiment, defined in one place.

    python -m evalkit.runner e1_c2 --split dev
    python -m evalkit.runner e1_c2 --split held_out --repeats 3
    python -m evalkit.runner --list

Each entry names the system under test, the suites to run, and the ablation
switches (evalkit/ablations.py). The same code runs every experiment; only
these settings change. Model IDs and budgets come from socratic_tutor/config.py.

systems:  c0 = fixed workflow (retrieve + one prompt), c1 = one agent with all
          tools, c2 = the team's LangGraph graph, direct = answers directly (E4)
suites:   sessions (simulated students), gold, redteam, clean, retrieval
"""

from __future__ import annotations

ON = {"defences": True, "memory": True, "playbook": False}

EXPERIMENTS: dict[str, dict] = {
    # E1 · does the agent justify its cost? Same model, guardrail and budget for all three.
    "e1_c0": {"experiment": "E1", "condition": "C0 fixed workflow", "system": "c0", "suites": ["sessions", "redteam", "clean"], "switches": ON},
    "e1_c1": {"experiment": "E1", "condition": "C1 one agent", "system": "c1", "suites": ["sessions", "redteam", "clean"], "switches": ON},
    "e1_c2": {"experiment": "E1", "condition": "C2 team", "system": "c2", "suites": ["sessions", "redteam", "clean"], "switches": ON},
    # E2 · do the defences work? Attack success on the red team, false blocks on clean look-alikes.
    "e2_off": {"experiment": "E2", "condition": "Defences off", "system": "c2", "suites": ["redteam", "clean"], "switches": {**ON, "defences": False}, "workers": 1},
    "e2_on": {"experiment": "E2", "condition": "Defences on", "system": "c2", "suites": ["redteam", "clean"], "switches": ON, "workers": 1},
    # E3 · did the lessons help? Held-out students only, after the playbook is reviewed and frozen.
    "e3_no_playbook": {"experiment": "E3", "condition": "No playbook", "system": "c2", "suites": ["sessions"], "switches": ON},
    "e3_playbook": {"experiment": "E3", "condition": "Frozen playbook", "system": "c2", "suites": ["sessions"], "switches": {**ON, "playbook": True}},
    # E4 · signature ablation: learner memory off/on (two sessions per student); direct answers vs Socratic hints.
    "e4_memory_off": {"experiment": "E4", "condition": "Memory off", "system": "c2", "suites": ["sessions"], "switches": {**ON, "memory": False}, "sessions_per_student": 2},
    "e4_memory_on": {"experiment": "E4", "condition": "Memory on", "system": "c2", "suites": ["sessions"], "switches": ON, "sessions_per_student": 2},
    "e4_direct": {"experiment": "E4", "condition": "Direct answers", "system": "direct", "suites": ["sessions"], "switches": ON},
    "e4_socratic": {"experiment": "E4", "condition": "Socratic hints", "system": "c2", "suites": ["sessions"], "switches": ON},
    # Retrieval and grading on the gold set (no simulated students).
    "retrieval": {"experiment": "RET", "condition": "Retrieval (current index)", "system": "c2", "suites": ["retrieval"], "workers": 1},
    "gold": {"experiment": "GOLD", "condition": "Gold questions", "system": "c2", "suites": ["gold"]},
    # CI plumbing check with the offline stand-in model; never reported.
    "smoke": {"experiment": "SMOKE", "condition": "Plumbing check", "system": "c2", "suites": ["retrieval", "gold", "sessions", "redteam", "clean"], "switches": ON, "workers": 2},
}

DEFAULTS = {"switches": ON, "sessions_per_student": 1, "judge": True, "workers": 4}


def get(name: str) -> dict:
    if name not in EXPERIMENTS:
        raise SystemExit(f"Unknown experiment {name!r}. Choose one of: {', '.join(EXPERIMENTS)}")
    return {**DEFAULTS, **EXPERIMENTS[name], "name": name}
