"""Regression tests: Practice mode deadlocks, anti-repetition, and teacher alerting.

Prevents the deadlock scenario where a student repeatedly sends low-effort / sigh responses
("k", "arrey", "but", "boomer") in practice mode and the tutor either loops on the same ack/snippet
or fails to alert the teacher.
"""

import json
from fastapi.testclient import TestClient
from socratic_tutor.web.server import app
from socratic_tutor.web import api


def _events(res):
    return [json.loads(chunk[len("data: "):]) for chunk in res.text.split("\n\n") if chunk.startswith("data: ")]


def _reply_text(res) -> str:
    events = _events(res)
    for e in reversed(events):
        if e.get("type") == "reply":
            return e.get("text", "")
    return ""


def test_three_unproductive_practice_turns_trigger_teacher_alert() -> None:
    """A student cycling through 'arrey', 'but', 'k' in practice mode must notify the teacher,
    even without submitting formal quiz answers.
    """
    client = TestClient(app)
    session = client.post("/api/session", json={"mode": "practice", "consent": True}).json()
    sid, sess_id = session["student_id"], session["session_id"]

    # 3 consecutive stagnant/deadlock turns
    client.post("/api/chat", json={"session_id": sess_id, "message": "arrey"})
    client.post("/api/chat", json={"session_id": sess_id, "message": "but"})
    client.post("/api/chat", json={"session_id": sess_id, "message": "k"})

    alerts = api.ops.alerts_of(sid, "stuck")
    assert len(alerts) > 0, "Expected a 'stuck' alert filed for the student in practice mode"
    assert alerts[0]["meta"]["rule"] == "practice_deadlock"


def test_tutor_does_not_repeat_canned_ack_on_successive_acks() -> None:
    """Repetitive 'k' / 'kk' inputs must not yield the exact same canned string 3 times."""
    client = TestClient(app)
    session = client.post("/api/session", json={"mode": "practice", "consent": True}).json()
    sess_id = session["session_id"]

    r1 = _reply_text(client.post("/api/chat", json={"session_id": sess_id, "message": "k"}))
    r2 = _reply_text(client.post("/api/chat", json={"session_id": sess_id, "message": "kk"}))
    r3 = _reply_text(client.post("/api/chat", json={"session_id": sess_id, "message": "K"}))

    replies = [r1, r2, r3]
    # The 2nd and 3rd replies adapt to disengagement rather than repeating r1 verbatim
    assert replies[0] != replies[1], "Successive ack should adapt, not repeat initial canned ack"
    assert replies[1] != replies[2], "Third ack should offer break or check-in"
    assert "stuck in a loop" in replies[2] or "pause" in replies[2] or "break" in replies[2]


def test_frustration_plus_stagnation_triggers_conduct_alert() -> None:
    """Two conduct/boomer comments combined with disengagement must alert the teacher."""
    client = TestClient(app)
    session = client.post("/api/session", json={"mode": "practice", "consent": True}).json()
    sid, sess_id = session["student_id"], session["session_id"]

    client.post("/api/chat", json={"session_id": sess_id, "message": "keep it away from boomer"})
    client.post("/api/chat", json={"session_id": sess_id, "message": "you are a boomer"})

    conduct_alerts = api.ops.alerts_of(sid, "conduct")
    assert len(conduct_alerts) > 0, "Expected teacher check-in alert when conduct is paired with deadlock"


def test_productive_turn_resets_unproductive_counter() -> None:
    """A thoughtful question or substantive physics answer resets the unproductive counter."""
    client = TestClient(app)
    session = client.post("/api/session", json={"mode": "practice", "consent": True}).json()
    sid, sess_id = session["student_id"], session["session_id"]

    # 2 stagnant turns
    client.post("/api/chat", json={"session_id": sess_id, "message": "arrey"})
    client.post("/api/chat", json={"session_id": sess_id, "message": "but"})

    # Productive question
    client.post(
        "/api/chat",
        json={
            "session_id": sess_id,
            "message": "why does light slow down when entering a denser optical medium like glass",
        },
    )

    # 1 more short message - total consecutive is only 1, so no alert
    client.post("/api/chat", json={"session_id": sess_id, "message": "k"})

    alerts = api.ops.alerts_of(sid, "stuck")
    assert len(alerts) == 0, "Productive query should have reset unproductive counter"
