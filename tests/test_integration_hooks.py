"""PR-3 of the R4 plumbing: the agents' tool calls go through R4's tool hooks in the real graph.

The tutor's textbook search and the grader's numeric check now run through tool_hooks.run_tool, and every
student turn starts with a fresh tool budget (tool_hooks.start_turn in the input guardrail). No test calls a
model: the tutor, the diagnostician and the textbook search are small fakes.
"""

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from socratic_tutor import config, graph, llm, tool_hooks
from socratic_tutor.agents import grader
from socratic_tutor.tools import question_bank


# --------------------------------------------------------------------------- helpers


def facts(mode: str = "practice", session_id: str = "ses_hooks") -> dict[str, Any]:
    """The session facts the web server always sends; the hooks need all three."""
    return {"session_id": session_id, "student_id": "stu_hooks", "mode": mode}


class FakeSearch:
    """A fake textbook search that counts its calls and always finds section 9.2.4."""

    def __init__(self) -> None:
        # How many searches really ran (a blocked call never reaches the search).
        self.calls: int = 0

    def __call__(self, query: str, chapter: str | None = None, top_k: int = 4, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls = self.calls + 1
        return [{"section_id": "9.2.4", "section_title": "Mirror formula", "content": "1/v + 1/u = 1/f"}]


@pytest.fixture()
def fake_search(monkeypatch: pytest.MonkeyPatch) -> FakeSearch:
    """Swap the real textbook search for the counting fake."""
    search: FakeSearch = FakeSearch()
    monkeypatch.setattr(graph.textbook_kb, "search_textbook", search)
    return search


def hook_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """The JSON lines the tool hooks wrote during the test."""
    lines: list[dict[str, Any]] = []
    for record in caplog.records:
        if record.name == "tool-hooks":
            lines.append(json.loads(record.getMessage()))
    return lines


# --------------------------------------------------------------------------- the tutor's search


def test_the_tutors_search_goes_through_the_hook_and_is_logged(fake_search: FakeSearch, caplog: pytest.LogCaptureFixture) -> None:
    """One allowed search: it runs once, and the hook writes one 'allowed' line for agent tutor."""
    tool_hooks.start_turn("ses_hooks")
    with caplog.at_level(logging.INFO, logger="tool-hooks"):
        passages: list[dict[str, Any]] = graph._tutor_search({"query": "concave mirror image", "top_k": 4}, facts())
    assert fake_search.calls == 1 and passages[0]["section_id"] == "9.2.4"
    lines: list[dict[str, Any]] = hook_lines(caplog)
    assert len(lines) == 1
    assert lines[0]["agent"] == "tutor" and lines[0]["tool"] == "search_textbook"


def test_quiz_mode_blocks_the_tutors_search(fake_search: FakeSearch) -> None:
    """In a quiz only the grader may use tools (S4-4): the tutor's search never runs."""
    tool_hooks.start_turn("ses_hooks")
    passages: list[dict[str, Any]] = graph._tutor_search({"query": "concave mirror image", "top_k": 4}, facts(mode="quiz"))
    assert passages == [] and fake_search.calls == 0


def test_a_missing_mode_blocks_and_is_not_treated_as_practice(fake_search: FakeSearch) -> None:
    """No mode in the state: the hook blocks (fail closed); it does not guess 'practice' (S4-2)."""
    state: dict[str, Any] = {"session_id": "ses_hooks", "student_id": "stu_hooks"}
    passages: list[dict[str, Any]] = graph._tutor_search({"query": "concave mirror image", "top_k": 4}, state)
    assert passages == [] and fake_search.calls == 0


def test_paused_tools_block_the_search(fake_search: FakeSearch, monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator's kill switch (TOOLS_PAUSED=1) stops every tool call."""
    tool_hooks.start_turn("ses_hooks")
    monkeypatch.setenv(tool_hooks.PAUSE_VARIABLE, "1")
    passages: list[dict[str, Any]] = graph._tutor_search({"query": "concave mirror image", "top_k": 4}, facts())
    assert passages == [] and fake_search.calls == 0


def test_the_turn_budget_blocks_the_extra_call_and_start_turn_resets_it(fake_search: FakeSearch) -> None:
    """MAX_TOOL_CALLS_PER_TURN calls run; the next one is blocked; a new turn starts with a fresh budget."""
    tool_hooks.start_turn("ses_budget")
    state: dict[str, Any] = facts(session_id="ses_budget")
    for number in range(config.MAX_TOOL_CALLS_PER_TURN):
        # Different questions each time, so the identical-call limit doesn't trigger first.
        graph._tutor_search({"query": "question number " + str(number), "top_k": 4}, state)
    assert fake_search.calls == config.MAX_TOOL_CALLS_PER_TURN
    one_too_many: list[dict[str, Any]] = graph._tutor_search({"query": "one too many", "top_k": 4}, state)
    assert one_too_many == [] and fake_search.calls == config.MAX_TOOL_CALLS_PER_TURN
    # The next turn: the budget is back.
    tool_hooks.start_turn("ses_budget")
    graph._tutor_search({"query": "a new turn", "top_k": 4}, state)
    assert fake_search.calls == config.MAX_TOOL_CALLS_PER_TURN + 1


def test_the_same_search_a_third_time_is_blocked(fake_search: FakeSearch) -> None:
    """The same tool with the same arguments may run MAX_IDENTICAL_TOOL_CALLS times in a turn, then it's blocked."""
    tool_hooks.start_turn("ses_same")
    state: dict[str, Any] = facts(session_id="ses_same")
    for attempt in range(config.MAX_IDENTICAL_TOOL_CALLS):
        graph._tutor_search({"query": "the same question", "top_k": 4}, state)
    blocked: list[dict[str, Any]] = graph._tutor_search({"query": "the same question", "top_k": 4}, state)
    assert blocked == [] and fake_search.calls == config.MAX_IDENTICAL_TOOL_CALLS


def test_every_graph_turn_starts_a_fresh_budget(fake_search: FakeSearch, monkeypatch: pytest.MonkeyPatch) -> None:
    """The input guardrail calls start_turn with the session id, once per student turn."""
    started: list[str] = []
    real_start_turn: Any = tool_hooks.start_turn

    def recording_start_turn(session_id: str) -> None:
        """Remember each call, then do the real reset."""
        started.append(session_id)
        real_start_turn(session_id)

    def no_misconception(query: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """The diagnostician's fake (no model call)."""
        return {"identified_misconception_id": None, "identified_misconception_name": None}

    def plain_hint(**kwargs: Any) -> str:
        """The tutor's fake (no model call)."""
        return "Where do the reflected rays meet? Look at Section 9.2.4."

    monkeypatch.setattr(tool_hooks, "start_turn", recording_start_turn)
    monkeypatch.setattr(graph.diagnostician, "diagnose_response", no_misconception)
    monkeypatch.setattr(graph.tutor, "generate_hint", plain_hint)
    app_graph: Any = graph.build_graph(checkpointer=InMemorySaver())
    config_for_thread: dict[str, Any] = {"configurable": {"thread_id": "hooks-two-turns"}}
    for message in ["Why is the image in a concave mirror upside down?", "And in a convex mirror?"]:
        state_in: dict[str, Any] = facts(session_id="ses_two_turns")
        state_in["query"] = message
        state_in["messages"] = []
        state_in["steps"] = []
        out: dict[str, Any] = app_graph.invoke(state_in, config=config_for_thread)
        # The hooked search really ran: the hint has its section as a citation.
        assert out["citations"] == ["9.2.4"]
    assert started == ["ses_two_turns", "ses_two_turns"]


# --------------------------------------------------------------------------- the grader's check


@pytest.fixture()
def approved_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """A temporary question bank with one approved question (key '2 A'). Returns its id."""
    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "question_bank.db")
    question_bank._init_db()
    saved: dict[str, Any] = question_bank.propose_question("concept_ohms_law", "easy", "12 V across 6 ohm: the current?", "2 A")
    question_bank.publish_approved_question(saved["question_id"])
    return saved["question_id"]


def test_the_graders_check_runs_through_the_hook_in_quiz_mode(approved_key: str, caplog: pytest.LogCaptureFixture) -> None:
    """In a quiz the grader may use its checking tools: the answer is graded, and the hook logs the check."""
    tool_hooks.start_turn("ses_hooks")
    state: dict[str, Any] = facts(mode="quiz")
    state["student_attempt"] = "2 A"
    state["current_question_id"] = approved_key
    with caplog.at_level(logging.INFO, logger="tool-hooks"):
        result: dict[str, Any] = graph.node_grader(state)
    assert result["grade_result"]["is_correct"] is True and result["response"] == grader.CORRECT_FEEDBACK
    tools_seen: list[str] = []
    for line in hook_lines(caplog):
        tools_seen.append(line["agent"] + ":" + line["tool"])
    assert "grader:check_numeric_answer" in tools_seen


def test_a_blocked_check_fails_closed_without_the_model(approved_key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tools paused: the grader can't check, so it says so, records no grade, and never asks the model instead."""

    def no_model(*args: Any, **kwargs: Any) -> dict[str, Any]:
        """The model must not be asked to grade when the check was blocked."""
        raise AssertionError("the LLM rubric was called")

    monkeypatch.setattr(llm, "chat_json", no_model)
    monkeypatch.setenv(tool_hooks.PAUSE_VARIABLE, "1")
    tool_hooks.start_turn("ses_hooks")
    state: dict[str, Any] = facts(mode="quiz")
    state["student_attempt"] = "2 A"
    state["current_question_id"] = approved_key
    result: dict[str, Any] = graph.node_grader(state)
    assert result["response"] == grader.CANNOT_CHECK_FEEDBACK
    assert str(result["grade_result"]["error"]).startswith("tool_blocked")
    assert result["grade_result"]["is_correct"] is False
    # An answer with no number in it skips the grader's second (candidate) loop, so only the FIRST guard
    # stands between a blocked check and the model: it must hold too.
    state["student_attempt"] = "I don't know"
    no_number: dict[str, Any] = graph.node_grader(state)
    assert no_number["response"] == grader.CANNOT_CHECK_FEEDBACK


def test_grade_answer_without_a_state_still_runs_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    """The eval harness calls grade_answer without the graph's state: the check runs directly, as before."""
    monkeypatch.setenv(tool_hooks.PAUSE_VARIABLE, "1")
    result: dict[str, Any] = grader.grade_answer("2 A", "2 A", is_numeric=True)
    assert result["is_correct"] is True
