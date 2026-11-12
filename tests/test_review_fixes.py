"""The gaps found in the team review of 12 Nov (student, teacher and monitoring), one test or more each."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from socratic_tutor import book, config, graph, intent
from socratic_tutor.tools import question_bank
from socratic_tutor.web import api, metrics
from socratic_tutor.web.server import app


def _teacher() -> TestClient:
    c = TestClient(app)
    assert c.post("/api/teacher/login", json={"pin": "test-pin"}).status_code == 200
    return c


def _named_student(name: str = "Priya") -> tuple[str, str]:
    sid = _teacher().post("/api/teacher/students", json={"name": name}).json()["student_id"]
    return sid, api.ops.student_code(sid)


# --------------------------------------------------------------------------- 1. classmates' records


def test_a_named_students_record_needs_their_code() -> None:
    sid, code = _named_student()
    pupil = TestClient(app)
    assert pupil.get(f"/api/student/{sid}/access").json() == {"student_id": sid, "allowed": False, "named": True}
    assert pupil.get(f"/api/student/{sid}/progress").status_code == 403
    assert pupil.get(f"/api/student/{sid}/plan").status_code == 403
    assert pupil.get(f"/api/student/{sid}/game").status_code == 403
    assert pupil.post("/api/session", json={"mode": "practice", "student_id": sid}).status_code == 403
    assert pupil.post(f"/api/student/{sid}/unlock", json={"code": "wrong"}).status_code == 403
    assert pupil.post(f"/api/student/{sid}/unlock", json={"code": code}).status_code == 200
    assert pupil.get(f"/api/student/{sid}/progress").status_code == 200
    assert pupil.post("/api/session", json={"mode": "practice", "student_id": sid}).status_code == 200


def test_only_the_teacher_deletes_a_named_student() -> None:
    sid, code = _named_student("Kiran")
    pupil = TestClient(app)
    pupil.post(f"/api/student/{sid}/unlock", json={"code": code})
    assert pupil.post("/api/forget_me", json={"student_id": sid}).status_code == 403
    assert sid in api.ops.roster()
    assert _teacher().post(f"/api/teacher/students/{sid}/forget").status_code == 200
    assert sid not in api.ops.roster()


def test_a_devices_own_id_can_still_delete_itself() -> None:
    me = TestClient(app)
    sid = me.post("/api/session", json={"mode": "practice", "consent": True}).json()["student_id"]
    assert me.post("/api/forget_me", json={"student_id": sid}).status_code == 200


def test_the_demo_class_stays_open_in_presenter_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "OPS_DEMO", "1")
    api.ops.add_student("stu_demo_zz", "Demo kid")
    try:
        assert TestClient(app).get("/api/student/stu_demo_zz/progress").status_code == 200
    finally:
        api.ops.forget("stu_demo_zz")  # other tests count the demo class


def test_teacher_sees_the_code() -> None:
    sid, code = _named_student("Asha")
    t = _teacher()
    assert t.get(f"/api/teacher/students/{sid}").json()["code"] == code
    assert any(s["student_id"] == sid and s["code"] == code for s in t.get("/api/teacher/students").json()["items"])


# --------------------------------------------------------------------------- 2. handled alerts come back


def test_a_handled_stuck_alert_comes_back_only_for_new_trouble(monkeypatch: pytest.MonkeyPatch) -> None:
    sid, ses = "stu_review_stuck", "ses_review_stuck"
    streak = {"n": 3}
    monkeypatch.setattr(api.learners, "get_profile", lambda s: {"failure_streaks": {"concept_mirror_formula": streak["n"]}, "mastery_map": {}})
    assert api._update_stuck_alerts(sid, ses, "concept_mirror_formula", None, None) is True
    alert = next(a for a in api.ops.open_alerts() if a["student_id"] == sid)
    api.ops.ack_alert(alert["id"])                                   # the teacher: "Mark as handled"
    assert api._update_stuck_alerts(sid, ses, "concept_mirror_formula", None, None) is False
    streak["n"] = 5
    assert api._update_stuck_alerts(sid, ses, "concept_mirror_formula", None, None) is False
    streak["n"] = 6                                                  # three more misses since it was handled
    assert api._update_stuck_alerts(sid, ses, "concept_mirror_formula", None, None) is True


def test_the_ten_minute_rule_fires_once_per_session(monkeypatch: pytest.MonkeyPatch) -> None:
    sid, ses = "stu_review_minutes", "ses_review_minutes"
    monkeypatch.setattr(api.learners, "get_profile", lambda s: {"failure_streaks": {}, "mastery_map": {}})
    monkeypatch.setattr(api.ops, "session_progress", lambda s: (12.0, 0.0))
    assert api._update_stuck_alerts(sid, ses, "concept_ohms_law", None, None) is True
    api.ops.ack_alert(next(a for a in api.ops.open_alerts() if a["student_id"] == sid)["id"])
    assert api._update_stuck_alerts(sid, ses, "concept_ohms_law", None, None) is False


def test_distress_alerts_are_listed_first() -> None:
    api.ops.add_alert("stu_review_order", None, "stuck", "stuck one")
    api.ops.add_alert("stu_review_order", None, "distress", "distress one")
    mine = [a["kind"] for a in api.ops.open_alerts() if a["student_id"] == "stu_review_order"]
    assert mine[0] == "distress"


# --------------------------------------------------------------------------- 3 and 4. the intent check


@pytest.mark.parametrize("message,in_conversation,expected", [
    ("I don't know", True, "confused"),
    ("idk", True, "confused"),
    ("I already answered that", True, "physics"),
    ("give me a harder one", True, "physics"),
    ("this is too easy", True, "physics"),
    ("I want to learn about electricity", False, "physics"),
    ("hi", True, "small_talk"),
    ("what is photosynthesis", False, "off_syllabus"),
    ("explain newton's laws of motion", False, "off_syllabus"),
    ("help me with my maths homework", True, "off_syllabus"),
    ("Why is the image in a concave mirror upside down?", False, "physics"),
])
def test_intent_cases_from_the_review(message: str, in_conversation: bool, expected: str) -> None:
    assert intent.classify(message, in_conversation=in_conversation)[0] == expected


def test_off_syllabus_gets_its_own_reply() -> None:
    assert "Light, the Human Eye and Electricity" in intent.reply_for("off_syllabus", "off_syllabus")


# --------------------------------------------------------------------------- 5. quiz answers under the question's topic


def test_a_quiz_answer_is_filed_under_its_questions_topic(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "qb.db")
    question_bank._init_db()
    saved = question_bank.propose_question("concept_mirror_formula", "easy", "u = -30 cm, f = -20 cm. Find v.", "-60 cm")
    question_bank.publish_approved_question(saved["question_id"])
    app_graph: Any = graph.build_graph(checkpointer=InMemorySaver())
    out = app_graph.invoke({"session_id": "ses_rq", "student_id": "stu_review_quiz", "mode": "quiz", "query": "100 cm",
                            "current_question_id": saved["question_id"], "current_concept_id": "concept_concave_ray_diagrams",
                            "messages": [], "steps": []}, config={"configurable": {"thread_id": "rq"}})
    assert out["current_concept_id"] == "concept_mirror_formula"


# --------------------------------------------------------------------------- 7, 9, 13, 14


def test_lesson_says_how_many_right_answers_are_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api.learners, "get_profile", lambda s: {"mastery_map": {"concept_mirror_formula": 0.33}, "failure_streaks": {}})
    monkeypatch.setattr(api.learners, "recent_scores", lambda s, c, n: [1.0, 0.0, 0.0])
    out = TestClient(app).get("/api/lesson/concept_mirror_formula?student_id=stu_review_lesson").json()
    assert out["right_needed"] == 2     # one more right: (1 + 1 + 0) / 3 = 0.67, not enough; two more: 1.0


def test_a_quiz_question_shows_its_topics_own_figure() -> None:
    fig = book.pick_figure("An object is 60 cm from a convex lens of focal length 20 cm. Find the image distance.",
                           "concept_lens_formula", book.CONCEPT_SECTIONS["concept_lens_formula"], prefer_own=True)
    assert fig and fig["figure"] in book.CONCEPT_FIGURES["concept_lens_formula"]


def test_book_text_glitches_are_gone() -> None:
    text = " ".join(book._sentences("9.2.1"))
    if not text:
        pytest.skip("the book index is not built here")
    assert "deter mining" not in text and "In, you" not in text


def test_session_state_returns_the_conversation() -> None:
    c = TestClient(app)
    s = c.post("/api/session", json={"mode": "practice", "consent": True}).json()
    c.post("/api/chat", json={"session_id": s["session_id"], "message": "hi"})
    msgs = c.get(f"/api/session/{s['session_id']}/state").json()["messages"]
    assert msgs[0] == {"role": "student", "text": "hi"} and msgs[-1]["role"] == "tutor"


# --------------------------------------------------------------------------- 10. monitoring


def test_metrics_show_open_alerts_by_kind_and_message_kinds() -> None:
    api.ops.add_alert("stu_review_metrics", None, "distress", "test")
    c = TestClient(app)
    s = c.post("/api/session", json={"mode": "practice", "consent": True}).json()
    c.post("/api/chat", json={"session_id": s["session_id"], "message": "what is photosynthesis"})
    text = c.get("/metrics").text
    assert 'socratic_open_alerts{kind="distress"}' in text
    assert 'socratic_intents_total{intent="off_syllabus"}' in text


def test_approval_wait_is_recorded() -> None:
    before = metrics.APPROVAL_LATENCY._sum.get()
    count_before = sum(b.get() for b in metrics.APPROVAL_LATENCY._buckets)
    fake = SimpleNamespace(get_state_history=lambda cfg: [SimpleNamespace(created_at="2026-11-12T10:00:00+00:00")])
    api._observe_approval_wait(fake, "set_x")
    assert sum(b.get() for b in metrics.APPROVAL_LATENCY._buckets) == count_before + 1
    assert metrics.APPROVAL_LATENCY._sum.get() > before
