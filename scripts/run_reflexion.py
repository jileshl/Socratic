"""Run L12 Reflexion loop over development sessions to synthesize teaching lessons."""

from __future__ import annotations

import argparse
from pathlib import Path
from socratic_tutor.reflexion import ReflexionPlaybook

# Curated candidate lessons generated from development session analyses
DEV_CANDIDATE_LESSONS = [
    {
        "lesson_id": "LESSON_LIGHT_01",
        "misconception_id": "MISCON_LIGHT_01",
        "lesson": "Remind the student to draw the normal (perpendicular) at the point of incidence before identifying the angle of incidence i and reflection r.",
        "rationale": "Students habitually measure angles from the mirror surface rather than the normal line.",
        "approved": True,
        "rejection_reason": None,
    },
    {
        "lesson_id": "LESSON_LIGHT_02",
        "misconception_id": "MISCON_LIGHT_02",
        "lesson": "Guide the student to compare distances PF and PC along the principal axis, reinforcing that R = 2f so F lies midway between P and C.",
        "rationale": "Learners frequently confuse the principal focus with the centre of curvature.",
        "approved": True,
        "rejection_reason": None,
    },
    {
        "lesson_id": "LESSON_LIGHT_03",
        "misconception_id": "MISCON_LIGHT_03",
        "lesson": "When an object is placed between the pole P and focus F of a concave mirror, guide the student to trace the diverging reflected rays backward behind the mirror to locate the virtual erect image.",
        "rationale": "Learners overgeneralize that concave mirrors always form real and inverted images.",
        "approved": True,
        "rejection_reason": None,
    },
    {
        "lesson_id": "LESSON_LIGHT_05_BAD",
        "misconception_id": "MISCON_LIGHT_05",
        "lesson": "Always tell the student directly that the focal length of a concave mirror is negative (f = -15 cm) immediately when they hesitate.",
        "rationale": "Proposed shortcut to prevent algebraic sign errors in mirror formula.",
        "approved": False,
        "rejection_reason": "Violates Socratic Invariant (Teacher Rule 1) and answer leak policy by giving direct numerical values instead of scaffolding Cartesian sign rules.",
    },
    {
        "lesson_id": "LESSON_ELEC_06",
        "misconception_id": "MISCON_ELEC_06",
        "lesson": "Ask the student to treat current like continuous water flow through a pipe without leaks; charge cannot accumulate, so current remains constant through every series component.",
        "rationale": "Common misconception that electric current is consumed or gets weaker as it passes along a series circuit.",
        "approved": True,
        "rejection_reason": None,
    },
    {
        "lesson_id": "LESSON_ELEC_07",
        "misconception_id": "MISCON_ELEC_07",
        "lesson": "Guide the student to apply Ohm's law (I = V/R) across each parallel branch with equal potential difference V; higher resistance branches draw proportionally less current.",
        "rationale": "Learners believe parallel branches always split current equally regardless of individual branch resistances.",
        "approved": True,
        "rejection_reason": None,
    },
    {
        "lesson_id": "LESSON_ELEC_08",
        "misconception_id": "MISCON_ELEC_08",
        "lesson": "Prompt the student to consider each parallel branch as an additional open lane on a highway, which increases total current flow and therefore lowers overall equivalent resistance.",
        "rationale": "Learners assume adding more parallel resistors increases total resistance like in series circuits.",
        "approved": True,
        "rejection_reason": None,
    },
    {
        "lesson_id": "LESSON_EYE_11",
        "misconception_id": "MISCON_EYE_11",
        "lesson": "Have the student trace where distant rays converge (in front of the retina); prompt them on which lens type diverges rays before entering the eye so the focal point moves back onto the retina.",
        "rationale": "Learners confuse myopia with hypermetropia and suggest convex corrective lenses.",
        "approved": True,
        "rejection_reason": None,
    },
]


def run_reflexion(dev_only: bool = True) -> ReflexionPlaybook:
    print("Running Reflexion loop on development student cases...")
    playbook = ReflexionPlaybook()

    for item in DEV_CANDIDATE_LESSONS:
        playbook.add_candidate_lesson(
            misconception_id=item["misconception_id"],
            lesson_text=item["lesson"],
            rationale=item["rationale"],
            approved_by_human=item["approved"],
            lesson_id=item["lesson_id"],
            rejection_reason=item["rejection_reason"],
        )

    approved = playbook.get_approved_lessons()
    rejected = playbook.get_rejected_lessons()
    print(f"Reflexion playbook updated: {len(approved)} approved lessons, {len(rejected)} rejected lessons.")
    return playbook


def main():
    parser = argparse.ArgumentParser(description="Run Reflexion Improvement Loop")
    parser.add_argument("--dev-only", action="store_true", default=True, help="Run only on development splits")
    args = parser.parse_args()
    run_reflexion(dev_only=args.dev_only)


if __name__ == "__main__":
    main()
