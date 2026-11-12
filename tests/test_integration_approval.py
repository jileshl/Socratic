"""R4 plumbing PR-2: the approval wiring and the solver key, end to end through the graph and the web app.

What these tests show:
- the teacher's "Propose a set" runs the graph's question setter, and the set waits on its OWN thread
  ("qbset:<set_id>"), so the run that proposed it never pauses (test X1);
- every answer key comes from the solver; none enters the graph's state;
- the teacher view lists and decides whole sets, signed on the server; the four bugs a full review of main
  found are gone (a web approval was always refused; an approval without a hash was accepted; nothing could
  reach the question setter; the teacher routes resumed the student's thread).

No test calls a model: llm.get_llm fails and llm.chat_json is a recorder that must stay empty, unless a test
gives the question setter a fake model (model_calls). Every test uses temporary files for the bank, the
checkpoints and the ops log. The question bank's concept list is stubbed; the graph's own ConceptGraph and
/api/quiz/next still load the concept graph file as the app does (the tests never print it).
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver

from socratic_tutor import approval_gate, config, graph, llm, policy, solver_key
from socratic_tutor.tools import question_bank, question_bank_server
from socratic_tutor.web import api
from socratic_tutor.web.ops_store import OpsStore
from socratic_tutor.web.server import app


TEST_KEY: str = "test-signing-key"
CONCEPT: str = "concept_mirror_formula"
KNOWN_CONCEPTS: list[str] = ["concept_mirror_formula", "concept_ohms_law", "concept_lens_formula"]

# The fake model's question for each difficulty, and the key the solver must compute for it.
FAKE_REPLIES: dict[str, dict[str, Any]] = {
    "easy": {
        "question_text": "An object is placed 30 cm in front of a concave mirror of focal length 20 cm. Find the image distance.",
        "calculation": {"formula": "mirror_formula", "values": {"u": -30, "f": -20}, "length_unit": "cm", "find": "v"},
        "gold_answer": "999 cm",  # the model's own key: it must never be used
    },
    "medium": {
        "question_text": "An object is placed 40 cm in front of a concave mirror of focal length 20 cm. Find the image distance.",
        "calculation": {"formula": "mirror_formula", "values": {"u": -40, "f": -20}, "length_unit": "cm", "find": "v"},
    },
    "hard": {
        "question_text": "An object is placed 10 cm in front of a concave mirror of focal length 20 cm. Find the image distance.",
        "calculation": {"formula": "mirror_formula", "values": {"u": -10, "f": -20}, "length_unit": "cm", "find": "v"},
    },
}
SOLVER_KEYS: dict[str, str] = {"easy": "-60 cm", "medium": "-40 cm", "hard": "20 cm"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_model_calls(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Any real model call in these tests is a bug. llm.chat_json swallows every exception, so a raising
    get_llm alone would stay silent: chat_json is a recorder too, which must be empty at the end (a test
    that fakes the model replaces it again)."""
    calls: list[str] = []

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a model call in a test")

    def record(prompt: str, system_prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        calls.append(prompt)
        return {"error": "a model call in a test"}

    monkeypatch.setattr(llm, "get_llm", refuse)
    monkeypatch.setattr(llm, "chat_json", record)
    yield
    assert calls == [], "a test reached llm.chat_json without a fake model"


@pytest.fixture
def model_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The question setter's model, faked: it reads the difficulty from the prompt and returns a canned reply.
    The list records the prompt of every call."""
    calls: list[str] = []

    def fake_chat_json(prompt: str, system_prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        calls.append(prompt)
        for difficulty in FAKE_REPLIES:
            if "Difficulty: " + difficulty in prompt:
                return json.loads(json.dumps(FAKE_REPLIES[difficulty]))
        return {"error": "no canned reply"}

    monkeypatch.setattr(llm, "chat_json", fake_chat_json)
    return calls


@pytest.fixture
def files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Temporary bank, checkpoints (the shared approval graph's file), ops log and concept list; the test key."""
    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "question_bank.db")
    question_bank._init_db()

    def known_concepts() -> list[str]:
        return list(KNOWN_CONCEPTS)

    monkeypatch.setattr(question_bank_server, "load_concept_ids", known_concepts)
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path)
    holder: dict[str, Any] = {"graph": None, "connection": None}
    monkeypatch.setattr(approval_gate, "APPROVAL_GRAPH_HOLDER", holder)
    monkeypatch.setattr(config, "APPROVAL_SIGNING_KEY", TEST_KEY)
    monkeypatch.setattr(api, "ops", OpsStore(tmp_path / "ops.db"))
    # The tutor graph on the SAME checkpoint file as the approval graph, as in the app (api.graph()).
    connection = sqlite3.connect(tmp_path / "checkpoints.sqlite", check_same_thread=False)
    tutor_graph = graph.build_graph(checkpointer=SqliteSaver(connection))
    monkeypatch.setattr(api, "_graph", tutor_graph)
    yield tutor_graph
    # Close both connections, so Windows can delete the temporary folder.
    connection.close()
    if holder["connection"] is not None:
        holder["connection"].close()


@pytest.fixture
def teacher(files: Any) -> TestClient:
    """A browser signed in as the teacher (conftest.py sets the PIN)."""
    client = TestClient(app)
    assert client.post("/api/teacher/login", json={"pin": "test-pin"}).status_code == 200
    return client


def teacher_request(concept: str, count: int) -> dict[str, Any]:
    """The graph input the web route sends for a teacher's request (no student, practice mode)."""
    return {
        "session_id": "qsetter:test",
        "student_id": "",
        "mode": "practice",
        "teacher_approval_required": True,
        "current_concept_id": concept,
        "question_set_size": count,
        "query": api.QUESTION_REQUEST_TEXT,
        "messages": [],
        "steps": [],
    }


def statuses(question_ids: list[str]) -> list[str]:
    """The bank status of each question."""
    found: list[str] = []
    for row in question_bank.get_questions(question_ids):
        found.append(row["status"])
    return found


def propose_through_the_web(teacher: TestClient, count: int = 3) -> dict[str, Any]:
    """The teacher clicks "Propose a set"; returns the one listed item for the new set."""
    proposed = teacher.post("/api/teacher/question_sets", json={"concept_id": CONCEPT, "count": count})
    assert proposed.status_code == 200, proposed.text
    body = proposed.json()
    assert body["ok"] is True, body
    item_id: str = "qbset:" + body["set_id"]
    for item in teacher.get("/api/teacher/approvals").json()["items"]:
        if item["item_id"] == item_id:
            return item
    raise AssertionError("the proposed set is not listed")


# ---------------------------------------------------------------------------
# The graph: the setter proposes a solver-keyed set and never pauses
# ---------------------------------------------------------------------------


def test_the_setter_inside_the_tutor_graph_never_pauses_it(files: Any, model_calls: list[str]) -> None:
    """X1: the set waits on the approval gate's own thread; the run that proposed it ends at once."""
    run_config: dict[str, Any] = {"configurable": {"thread_id": "qsetter:test"}, "recursion_limit": 25}
    out: dict[str, Any] = files.invoke(teacher_request(CONCEPT, 3), run_config)
    # Nothing paused in the tutor graph.
    assert "__interrupt__" not in out
    assert files.get_state(run_config).next == ()
    # One model call per difficulty, each shown the solver's formula list.
    assert len(model_calls) == 3
    for prompt in model_calls:
        assert "Formulas you may use:" in prompt
    # One set of three, waiting on the SHARED approval graph, with the solver's keys.
    summary: dict[str, Any] = out["proposed_set"]
    assert summary["ok"] is True
    assert len(summary["question_ids"]) == 3
    waiting = approval_gate.pending_set(approval_gate.get_approval_graph(), summary["set_id"])
    assert waiting is not None
    keys: list[str] = []
    for question in waiting["payload"]["questions"]:
        keys.append(question["gold_answer"])
    assert keys == [SOLVER_KEYS["easy"], SOLVER_KEYS["medium"], SOLVER_KEYS["hard"]]
    # Nothing is published until the teacher approves.
    assert statuses(summary["question_ids"]) == ["pending_approval", "pending_approval", "pending_approval"]


def test_no_answer_key_enters_the_graph_state(files: Any, model_calls: list[str]) -> None:
    """The graph's state holds ids and reasons only (THREAT_MODEL residual 4): never a key."""
    run_config: dict[str, Any] = {"configurable": {"thread_id": "qsetter:test"}, "recursion_limit": 25}
    files.invoke(teacher_request(CONCEPT, 3), run_config)
    values: dict[str, Any] = files.get_state(run_config).values
    dumped: str = json.dumps(values, default=str)
    assert SOLVER_KEYS["easy"] not in dumped
    assert SOLVER_KEYS["medium"] not in dumped
    assert "999 cm" not in dumped
    assert "teacher_approval_payload" not in values


def test_the_graph_has_no_gate_node_of_its_own() -> None:
    """The graph's old gate node (a web approval was always refused there) is gone: the setter ends the run."""
    drawn = graph.build_graph().get_graph()
    assert "teacher_approval_gate" not in drawn.nodes
    assert len(drawn.edges) == 14
    assert "question_setter --> __end__" in drawn.draw_mermaid()


def test_the_teacher_request_text_passes_the_input_check() -> None:
    """The fixed request text must not trip a word rule (it avoids the word "teacher")."""
    assert policy.check_input_guardrails(api.QUESTION_REQUEST_TEXT)["passed"] is True


def test_a_duplicate_draft_is_reported_with_its_difficulty(files: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same question three times: the bank keeps one, and the teacher learns which drafts were refused."""

    def same_reply(prompt: str, system_prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        return json.loads(json.dumps(FAKE_REPLIES["easy"]))

    monkeypatch.setattr(llm, "chat_json", same_reply)
    run_config: dict[str, Any] = {"configurable": {"thread_id": "qsetter:test"}, "recursion_limit": 25}
    summary: dict[str, Any] = files.invoke(teacher_request(CONCEPT, 3), run_config)["proposed_set"]
    assert summary["ok"] is True
    assert len(summary["question_ids"]) == 1
    refused_difficulties: list[str] = []
    for item in summary["refused"]:
        refused_difficulties.append(item["difficulty"])
    assert refused_difficulties == ["medium", "hard"]


def test_every_fallback_question_with_a_calculation_gets_the_solvers_key() -> None:
    """Jilesh's fallback questions (used when the model call fails): each numeric one is keyed by the solver, and
    the key agrees with the one written next to it. Text-only ones are refused (P2-4)."""
    from socratic_tutor.agents.question_setter import CONCEPT_FALLBACK_QUESTIONS

    for concept in CONCEPT_FALLBACK_QUESTIONS:
        entry: Any = CONCEPT_FALLBACK_QUESTIONS[concept]
        entries: list[dict[str, Any]] = []
        if isinstance(entry, list):
            entries = entry
        else:
            entries = [entry]
        for question in entries:
            made: dict[str, Any] = solver_key.draft_from_model_reply(concept, "easy", question)
            if "calculation" in question:
                assert made["ok"] is True, (concept, made)
                assert made["draft"]["gold_answer"] == question["gold_answer"]
            else:
                assert made["ok"] is False


# ---------------------------------------------------------------------------
# The web app: propose, list and decide whole sets, signed on the server
# ---------------------------------------------------------------------------


def test_the_teacher_trigger_reaches_the_question_setter(teacher: TestClient, model_calls: list[str]) -> None:
    """Bug 3 (nothing could reach the question setter): the button's route runs it, and the set is listed."""
    proposed = teacher.post("/api/teacher/question_sets", json={"concept_id": CONCEPT, "count": 2})
    assert proposed.status_code == 200
    body = proposed.json()
    assert body["ok"] is True
    assert body["question_count"] == 2
    assert len(model_calls) == 2
    listed = teacher.get("/api/teacher/approvals").json()
    assert len(listed["items"]) == 1
    assert listed["items"][0]["item_id"] == "qbset:" + body["set_id"]
    assert len(listed["items"][0]["payload"]["questions"]) == 2
    # The view also gets the concepts to choose from, and knows that approvals are on.
    assert listed["concept_ids"] == KNOWN_CONCEPTS
    assert listed["approvals_enabled"] is True


def test_an_unknown_concept_costs_no_model_call(teacher: TestClient, model_calls: list[str]) -> None:
    """An unknown concept is refused before the graph runs."""
    refused = teacher.post("/api/teacher/question_sets", json={"concept_id": "concept_made_up", "count": 3})
    assert refused.status_code == 400
    assert model_calls == []


def test_a_web_approval_publishes_the_set(teacher: TestClient, model_calls: list[str]) -> None:
    """Bug 1 (a web approval was always refused): approving the listed version publishes every question,
    and a student's quiz can then serve one of them (never its key)."""
    item = propose_through_the_web(teacher)
    question_ids: list[str] = []
    for question in item["payload"]["questions"]:
        question_ids.append(question["id"])
    approved = teacher.post("/api/teacher/approvals/" + item["item_id"],
                            json={"action": "approve", "payload_hash": item["payload_hash"]})
    assert approved.status_code == 200, approved.text
    assert approved.json()["published"] is True
    assert statuses(question_ids) == ["approved", "approved", "approved"]
    # Nothing waits any more, and the decision is in the log.
    assert teacher.get("/api/teacher/approvals").json()["items"] == []
    assert api.ops.approval_log()[0]["outcome"] == "ok"
    # A student's quiz serves one of the published questions, without its key.
    session = teacher.post("/api/session", json={"mode": "quiz"}).json()
    served = teacher.get("/api/quiz/next", params={"session_id": session["session_id"]}).json()
    assert served["question_id"] in question_ids
    assert "gold_answer" not in served


def test_a_decision_without_the_right_hash_publishes_nothing(teacher: TestClient, model_calls: list[str]) -> None:
    """Bug 2 (an approval without a hash was accepted): no hash, or a made-up one, is refused; nothing changes."""
    item = propose_through_the_web(teacher)
    question_ids: list[str] = []
    for question in item["payload"]["questions"]:
        question_ids.append(question["id"])
    no_hash = teacher.post("/api/teacher/approvals/" + item["item_id"], json={"action": "approve", "payload_hash": ""})
    assert no_hash.status_code == 409
    made_up = teacher.post("/api/teacher/approvals/" + item["item_id"],
                           json={"action": "approve", "payload_hash": "a" * 64})
    assert made_up.status_code == 409
    assert made_up.json()["current_hash"] == item["payload_hash"]
    assert statuses(question_ids) == ["pending_approval", "pending_approval", "pending_approval"]


def test_an_edit_through_the_web_needs_a_new_approval(teacher: TestClient, model_calls: list[str]) -> None:
    """The live demo (guide p.3): edit a key -> a new version; the old version can't be approved; the new one can."""
    item = propose_through_the_web(teacher)
    first_id: str = item["payload"]["questions"][0]["id"]
    item_url: str = "/api/teacher/approvals/" + item["item_id"]
    edited = teacher.post(item_url, json={"action": "edit", "payload_hash": item["payload_hash"],
                                          "changes": {first_id: {"gold_answer": "-0.6 m"}}})
    assert edited.status_code == 200, edited.text
    new_hash: str = edited.json()["payload_hash"]
    assert new_hash != item["payload_hash"]
    # The approval of the version the teacher first saw no longer applies.
    stale = teacher.post(item_url, json={"action": "approve", "payload_hash": item["payload_hash"]})
    assert stale.status_code == 409
    assert "older version" in stale.json()["detail"]
    # The new version can be approved, and the edited key is stored.
    approved = teacher.post(item_url, json={"action": "approve", "payload_hash": new_hash})
    assert approved.status_code == 200
    assert question_bank.get_approved_question(first_id)["gold_answer"] == "-0.6 m"


def test_an_edit_with_an_unreadable_key_is_refused(teacher: TestClient, model_calls: list[str]) -> None:
    """A teacher's edited key must still be readable by the grader (S3-8); otherwise nothing changes."""
    item = propose_through_the_web(teacher)
    first_id: str = item["payload"]["questions"][0]["id"]
    refused = teacher.post("/api/teacher/approvals/" + item["item_id"],
                           json={"action": "edit", "payload_hash": item["payload_hash"],
                                 "changes": {first_id: {"gold_answer": "v = -60 cm"}}})
    assert refused.status_code == 409
    assert teacher.get("/api/teacher/approvals").json()["items"][0]["payload_hash"] == item["payload_hash"]


def test_without_a_signing_key_nothing_can_be_decided(
    teacher: TestClient, model_calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """No APPROVAL_SIGNING_KEY: 503 with the reason; nothing changes; the view knows approvals are off."""
    item = propose_through_the_web(teacher)
    monkeypatch.setattr(config, "APPROVAL_SIGNING_KEY", "")
    refused = teacher.post("/api/teacher/approvals/" + item["item_id"],
                           json={"action": "approve", "payload_hash": item["payload_hash"]})
    assert refused.status_code == 503
    assert "APPROVAL_SIGNING_KEY" in refused.json()["detail"]
    listed = teacher.get("/api/teacher/approvals").json()
    assert listed["approvals_enabled"] is False
    assert listed["items"][0]["payload_hash"] == item["payload_hash"]


def test_old_item_ids_are_not_found(teacher: TestClient, model_calls: list[str]) -> None:
    """Bug 4 (the old routes approved one row unsigned, or resumed a student's thread): those ids are 404 now."""
    item = propose_through_the_web(teacher)
    first_id: str = item["payload"]["questions"][0]["id"]
    one_row = teacher.post("/api/teacher/approvals/qb:" + first_id,
                           json={"action": "approve", "payload_hash": item["payload_hash"]})
    assert one_row.status_code == 404
    student_thread = teacher.post("/api/teacher/approvals/graph:ses_123",
                                  json={"action": "approve", "payload_hash": item["payload_hash"]})
    assert student_thread.status_code == 404
    assert statuses([first_id]) == ["pending_approval"]


def test_a_stale_edit_from_a_second_tab_is_refused_not_reported_as_edited(
    teacher: TestClient, model_calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review fix: two tabs show version 1. Tab B's edit lands while tab A's request is on its way, so A's edit
    (signed for version 1) is refused by the gate: the route must say 409, never "edited", and log a refusal."""
    item = propose_through_the_web(teacher)
    first_id: str = item["payload"]["questions"][0]["id"]
    real_decide = approval_gate.decide
    tab_b_done: list[bool] = []

    def decide_after_tab_b(gate_graph: Any, set_id: str, decision: Any) -> dict[str, Any]:
        # Tab B's edit, just before tab A's decision reaches the gate.
        if len(tab_b_done) == 0:
            tab_b_done.append(True)
            changes_b = {first_id: {"gold_answer": "-0.6 m"}}
            signed_b = approval_gate.sign_decision(set_id, "edit", item["payload_hash"], "teacher", changes_b)
            assert real_decide(gate_graph, set_id, signed_b)["status"] == "waiting"
        return real_decide(gate_graph, set_id, decision)

    monkeypatch.setattr(approval_gate, "decide", decide_after_tab_b)
    tab_a = teacher.post("/api/teacher/approvals/" + item["item_id"],
                         json={"action": "edit", "payload_hash": item["payload_hash"],
                               "changes": {first_id: {"gold_answer": "-60.0 cm"}}})
    assert tab_a.status_code == 409, tab_a.text
    assert api.ops.approval_log()[0]["outcome"].startswith("refused")
    # Tab B's version is the one waiting.
    waiting = teacher.get("/api/teacher/approvals").json()["items"][0]
    assert waiting["payload"]["questions"][0]["gold_answer"] == "-0.6 m"


def test_a_broken_list_is_reported_not_shown_as_empty(teacher: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review fix: if the waiting sets can't be read, the view is told so; it never shows "Nothing waiting"."""

    def broken(gate_graph: Any) -> list[dict[str, Any]]:
        raise RuntimeError("checkpoint file unreadable")

    monkeypatch.setattr(approval_gate, "waiting_sets", broken)
    listed = teacher.get("/api/teacher/approvals").json()
    assert listed["items"] == []
    assert "could not be read" in listed["list_error"]


def test_the_teacher_is_told_when_fallback_questions_stood_in(teacher: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review fix: when the model gives no usable question, the agent's fixed fallback question stands in; the
    teacher's note says so (and the repeats of it are refused as duplicates)."""
    calls: list[str] = []

    def model_down(prompt: str, system_prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        calls.append(prompt)
        return {"error": "Failed to complete chat_json: the model is down"}

    monkeypatch.setattr(llm, "chat_json", model_down)
    proposed = teacher.post("/api/teacher/question_sets", json={"concept_id": CONCEPT, "count": 3}).json()
    assert len(calls) == 3
    assert proposed["ok"] is True
    assert proposed["question_count"] == 1
    assert "fixed fallback" in proposed["note"]
    assert len(proposed["refused"]) == 2


def test_the_dashboard_counts_waiting_sets(teacher: TestClient, model_calls: list[str]) -> None:
    """The dashboard's "waiting approvals" counts waiting sets."""
    propose_through_the_web(teacher, count=1)
    # The second request's "easy" draft repeats the first set's question (refused as a duplicate); the medium
    # and hard drafts make the second set.
    second = propose_through_the_web(teacher, count=3)
    assert len(second["payload"]["questions"]) == 2
    assert teacher.get("/api/teacher/dashboard").json()["waiting_approvals"] == 2


def test_the_teacher_routes_need_the_login(files: Any, model_calls: list[str]) -> None:
    """Without the teacher's sign-in, neither proposing nor deciding is possible."""
    stranger = TestClient(app)
    assert stranger.post("/api/teacher/question_sets", json={"concept_id": CONCEPT, "count": 1}).status_code == 401
    assert stranger.post("/api/teacher/approvals/qbset:set_x",
                         json={"action": "approve", "payload_hash": "a" * 64}).status_code == 401
    assert model_calls == []


def test_the_seed_script_submits_one_set(files: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """scripts/seed_demo.py (through web/demo_data.py) puts its five demo questions in as ONE waiting set, with keys
    the grader can read (on temporary files here)."""
    script = config.BASE_DIR / "scripts" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("seed_demo", script)
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    # The script reads its options from the command line: none, so it only proposes the questions.
    monkeypatch.setattr("sys.argv", ["seed_demo"])
    seed.main()
    waiting = approval_gate.waiting_sets(approval_gate.get_approval_graph())
    assert len(waiting) == 1
    assert len(waiting[0]["payload"]["questions"]) == 5
    for question in waiting[0]["payload"]["questions"]:
        assert "=" not in question["gold_answer"]
        assert question_bank_server.answer_key_problem(question["gold_answer"]) is None
