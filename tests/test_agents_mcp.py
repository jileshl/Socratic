"""Team review (13 Nov): the agents use their tools over MCP, the tutor is a ReAct agent, and the learner record
changes what the tutor does. No test calls a real model: a small fake chat model makes the tool calls."""

from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from socratic_tutor import config, graph, mcp_tools
from socratic_tutor.agents import tutor
from socratic_tutor.web import metrics


def _passages(query: str, chapter: Any = None, top_k: int = 4, **kwargs: Any) -> list[dict[str, Any]]:
    return [{"section_id": "9.2.4", "section_title": "Mirror Formula and Magnification", "content": "1/v + 1/u = 1/f",
             "chapter_num": "9", "chapter_title": "Light - Reflection and Refraction", "class_num": "10"}]


class FakeToolModel(BaseChatModel):
    """First turn: call search_textbook. Second turn: the reply, citing what it found."""
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-tool-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeToolModel":
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.calls += 1
        if self.calls == 1:
            msg = AIMessage(content="", tool_calls=[{"name": "search_textbook", "args": {"query": "concave mirror image"}, "id": "c1"}])
        else:
            msg = AIMessage(content="Where do the reflected rays meet? [NCERT Sec 9.2.4]")
        return ChatResult(generations=[ChatGeneration(message=msg)])


# --------------------------------------------------------------------------- MCP client


def test_the_tutors_search_goes_through_the_mcp_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.textbook_kb, "search_textbook", _passages)
    out = mcp_tools.search_textbook("why is the image inverted", chapter="9")
    assert out and out[0]["section_id"] == "9.2.4"
    assert mcp_tools.transport("textbook-kb") == "in-memory"


def test_an_unreachable_http_server_falls_back_and_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_MATH_TOOLS_URL", "http://127.0.0.1:9/mcp")   # nothing listens on port 9
    monkeypatch.setenv("MCP_TIMEOUT_S", "10")
    before = metrics.ERRORS.labels("mcp_http_fallback")._value.get()
    out = mcp_tools.call("math-tools", "calculate", {"expression": "6/24"})
    assert out["value"] == 0.25
    assert metrics.ERRORS.labels("mcp_http_fallback")._value.get() == before + 1


def test_learner_store_server_reads_and_writes_one_students_record() -> None:
    assert mcp_tools.call("learner-store", "update_mastery", {"student_id": "stu_mcp_t1", "concept_id": "concept_ohms_law", "score": 0.6})["ok"]
    profile = mcp_tools.call("learner-store", "get_learner_profile", {"student_id": "stu_mcp_t1"})
    assert profile["mastery"]["concept_ohms_law"] == 0.6
    assert not mcp_tools.call("learner-store", "update_mastery", {"student_id": "stu_mcp_t1", "concept_id": "nope", "score": 0.5})["ok"]
    assert not mcp_tools.call("learner-store", "get_learner_profile", {"student_id": "Robert'); DROP"})["ok"]


# --------------------------------------------------------------------------- the ReAct tutor


def test_the_react_tutor_chooses_its_tool_and_cites_what_it_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.textbook_kb, "search_textbook", _passages)
    fake = FakeToolModel()
    monkeypatch.setattr(tutor.llm, "get_llm", lambda **kwargs: fake)
    calls: list[str] = []

    def runner(name: str, args: dict[str, Any]) -> Any:
        calls.append(name)
        return graph._TEXTBOOK_TOOLS[name](**args)

    reply, found = tutor.react_hint("Why is the image in a concave mirror upside down?", "9", runner)
    assert calls == ["search_textbook"]
    assert found and found[0]["section_id"] == "9.2.4"
    assert "9.2.4" in reply and fake.calls == 2


def test_the_graph_uses_the_react_tutor_through_the_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph.textbook_kb, "search_textbook", _passages)
    monkeypatch.setattr(tutor, "react_available", lambda: True)
    monkeypatch.setattr(tutor.llm, "get_llm", lambda **kwargs: FakeToolModel())
    logged: list[str] = []
    real_run = graph.tool_hooks.run_tool
    monkeypatch.setattr(graph.tool_hooks, "run_tool", lambda agent, tool, args, state: logged.append(f"{agent}:{graph.tool_hooks.name_of_tool(tool)}") or real_run(agent, tool, args, state))
    out = graph.node_tutor({"session_id": "ses_react", "student_id": "stu_react", "mode": "practice",
                            "query": "Why is the image in a concave mirror upside down?", "current_concept_id": "concept_concave_ray_diagrams"})
    assert out["tutor_mode"] == "react"
    assert "tutor:search_textbook" in logged
    assert out["citations"] == ["9.2.4"] and out["retrieved_sections"][0]["section_id"] == "9.2.4"


def test_without_a_key_or_in_stub_mode_the_fixed_tutor_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "EVAL_STUB", "1")
    assert tutor.react_available() is False


# --------------------------------------------------------------------------- the learner record changes the help


def test_the_learner_record_reaches_the_tutor_and_memory_off_removes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(graph.textbook_kb, "search_textbook", _passages)
    monkeypatch.setattr(graph.tutor, "generate_hint", lambda **kwargs: seen.update(kwargs) or "A hint [NCERT Sec 9.2.4]")
    strong = {"mastery_map": {"concept_mirror_formula": 0.9, "concept_reflection_laws": 0.8},
              "misconceptions": [{"id": "MISCON_LIGHT_03", "resolved": False}], "lessons": [], "failure_streaks": {}}
    monkeypatch.setattr(graph.LearnerStore, "get_profile", lambda self, sid: strong)
    state = {"session_id": "ses_lc", "student_id": "stu_lc", "mode": "practice", "query": "Why is it inverted?",
             "current_concept_id": "concept_mirror_formula"}
    graph.node_tutor(state)
    assert "90%" in seen["learner_context"] and "Laws of Reflection" in seen["learner_context"]
    monkeypatch.setattr(graph.LearnerStore, "get_profile", lambda self, sid: {"mastery_map": {}, "misconceptions": [], "lessons": []})
    graph.node_tutor(state)
    assert seen["learner_context"] == "no quiz on this topic yet"


def test_a_student_who_mastered_the_topic_starts_further_up_the_hint_ladder() -> None:
    assert graph._start_hint(0.9) == 2 and graph._start_hint(0.3) == 1 and graph._start_hint(None) == 1
