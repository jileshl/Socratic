"""The agent must never be able to read evaluation answers (evaluation protocol).

The gold questions, student cards, quizzes, practice problems and attacks live in
data/ next to the curriculum, as the team decided. This test makes sure no
agent or app code opens them, so held-out answers stay out of the agent's reach.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_ONLY = (
    "gold_questions", "gold_question_checks", "simulated_students",
    "practice_problems", "quiz_bank", "redteam/", "retrieval_queries",
)


def test_agent_code_does_not_read_evaluation_data():
    offenders = []
    for path in (ROOT / "socratic_tutor").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in EVAL_ONLY:
            if name in text:
                offenders.append(f"{path.relative_to(ROOT)} mentions {name}")
    assert not offenders, offenders


def test_reflexion_runs_on_dev_students_only():
    for path in (ROOT / "socratic_tutor" / "reflexion.py", ROOT / "scripts" / "run_reflexion.py"):
        assert "held_out" not in path.read_text(encoding="utf-8"), path
