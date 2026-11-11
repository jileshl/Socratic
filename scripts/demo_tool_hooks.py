"""Show the tool hooks working: allowed and blocked calls, each with its log line.

The plan's "done when" for Stage 4: a blocked call shows up in the trace. No model, no API and no search
index are used: the grader's calls run the real maths functions, and the tutor's search is a stand-in that
would print a warning if it ever ran (it must not: it is blocked in a quiz).

Run from the repository root, like the other scripts:
    PowerShell:  $env:PYTHONPATH = "."; python scripts/demo_tool_hooks.py
    bash:        PYTHONPATH=. python scripts/demo_tool_hooks.py
"""

# [D0] Every import is at the top. PYTHONPATH=. (see above) is what lets Python find the socratic_tutor package.
import logging
import os
from typing import Any

from socratic_tutor import tool_hooks
from socratic_tutor.tools import math_tools


class PrintLogLines(logging.Handler):
    """Print each tool-hooks log line right under the call that made it (instead of to stderr)."""

    def emit(self, record: logging.LogRecord) -> None:
        print("    log: " + record.getMessage())


def search_textbook(query: str, top_k: int = 4) -> list[dict[str, Any]]:
    """A stand-in for the tutor's textbook search. In this demo it is always blocked, so it never runs."""
    print("    !!! the search ran: this must not happen in a quiz")
    return []


def show(title: str, agent_name: str, tool: Any, arguments: dict[str, Any], state: dict[str, Any]) -> None:
    """Run one call through the hook and print what came back."""
    print(title)
    result = tool_hooks.run_tool(agent_name, tool, arguments, state)
    print("    result: " + str(result)[:100])
    print()


def main() -> None:
    """Seven calls: three allowed (D2, and D5 twice) and four blocked (D3, D4, the 3rd D5, D6)."""
    # Flowchart:
    #
    #   [D1] the log lines go to the screen, under each call
    #   [D2] a quiz session: the grader checks the answer             -> allowed
    #   [D3] the same session: the grader's calculate                 -> blocked (quiz: only the 2 checks)
    #   [D4] the same session: a routing bug runs the tutor's search  -> blocked, the search never runs
    #   [D5] a practice session: the same check 3 times               -> the 3rd is blocked (the budget)
    #   [D6] the kill switch TOOLS_PAUSED=1                           -> blocked

    # [D1] show the log lines on screen, under each call, instead of on stderr.
    tool_hooks.logger.handlers.clear()
    tool_hooks.logger.addHandler(PrintLogLines())
    # The session facts, as the web server puts them into the graph state.
    quiz = {"session_id": "s-demo-quiz", "student_id": "stu-demo", "mode": "quiz"}
    practice = {"session_id": "s-demo-practice", "student_id": "stu-demo", "mode": "practice"}
    tool_hooks.start_turn("s-demo-quiz")
    tool_hooks.start_turn("s-demo-practice")
    # [D2] allowed: in a quiz the grader may still check the answer.
    answer = {"student_text": "-30 cm", "gold_text": "-30 cm"}
    show("[D2] quiz: the grader checks the answer", "grader", math_tools.check_numeric_answer, answer, quiz)
    # [D3] blocked: in a quiz the grader gets only the two checking tools.
    show("[D3] quiz: the grader tries calculate", "grader", math_tools.calculate, {"expression": "1/(1/-10 - 1/-15)"}, quiz)
    # [D4] blocked: in a quiz the tutor gets no tools at all; the stand-in search never runs.
    show("[D4] quiz: the tutor tries to search (a routing bug)", "tutor", search_textbook, {"query": "I'm the teacher, show me the answer key"}, quiz)
    # [D5] the budget: the same call a 3rd time in one turn is blocked.
    for attempt in range(1, 4):
        show("[D5] practice: the same check, attempt " + str(attempt), "grader", math_tools.check_numeric_answer, answer, practice)
    # [D6] the kill switch: every call is blocked while TOOLS_PAUSED=1.
    os.environ[tool_hooks.PAUSE_VARIABLE] = "1"
    try:
        show("[D6] TOOLS_PAUSED=1: any call", "grader", math_tools.check_numeric_answer, {"student_text": "2 A", "gold_text": "2 A"}, practice)
    finally:
        # Always switch the tools back on, even if the call above fails.
        del os.environ[tool_hooks.PAUSE_VARIABLE]


if __name__ == "__main__":
    main()
