"""Tests for the approval gate (socratic_tutor/approval_gate.py): submit, approve, edit, reject, stale and
unsigned decisions, changes in the bank, a restart, a double click, the log, and the live-demo script.

Every test uses a temporary question bank and a temporary checkpoint database (the bank and gate
fixtures), so the real .index/ files are never touched. Decisions are signed with a test key.
"""

import hashlib
import importlib.util
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from socratic_tutor import approval_gate
from socratic_tutor import config
from socratic_tutor.tools import question_bank
from socratic_tutor.tools import question_bank_server


TEST_KEY: str = "test-signing-key"
TEACHER: str = "teacher_1"
OHMS_PROMPT: str = "A 12 V battery is connected across a 4 ohm resistor. What is the current?"
MIRROR_PROMPT: str = "An object is 30 cm in front of a concave mirror of focal length 20 cm. Where is the image?"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def bank(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A temporary, empty question bank, and the test signing key in the environment."""
    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "question_bank.db")
    question_bank._init_db()
    # The gate reads config.APPROVAL_SIGNING_KEY; monkeypatch puts the real value back afterwards.
    monkeypatch.setattr(config, "APPROVAL_SIGNING_KEY", TEST_KEY)


@pytest.fixture
def gate(bank: None, tmp_path: Path) -> Any:
    """An approval graph with a checkpointer on a temporary SQLite file."""
    connection = sqlite3.connect(tmp_path / "checkpoints.sqlite", check_same_thread=False)
    yield approval_gate.build_approval_graph(SqliteSaver(connection))
    # Close the file, so Windows can delete the temporary folder.
    connection.close()


class LineCollector(logging.Handler):
    """Collects the approval-gate log lines, so a test can read exactly what was logged."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def log_lines() -> Any:
    """Every line the gate logs during the test (the logger doesn't pass lines on to pytest's own capture)."""
    collector = LineCollector()
    approval_gate.logger.addHandler(collector)
    yield collector.lines
    approval_gate.logger.removeHandler(collector)


def propose_two() -> list[str]:
    """Propose an Ohm's-law and a mirror question (pending, unseen by students) and return their ids."""
    first = question_bank.propose_question("concept_ohms_law", "easy", OHMS_PROMPT, "3 A")
    second = question_bank.propose_question("concept_mirror_formula", "medium", MIRROR_PROMPT, "-60 cm")
    return [first["question_id"], second["question_id"]]


def sign(set_id: str, action: str, hash_text: str, approver: str = TEACHER, changes: Any = None,
         payload: Any = None) -> dict[str, Any]:
    """A decision signed with the test key, as the teacher view would send it."""
    return approval_gate.sign_decision(set_id, action, hash_text, approver, changes=changes, payload=payload, key=TEST_KEY)


def status_of(question_id: str) -> str:
    """A question's status in the temporary bank."""
    return question_bank.get_questions([question_id])[0]["status"]


def submit(gate: Any, ids: list[str], set_id: str = "set_a") -> dict[str, Any]:
    """Submit a set and check it is waiting."""
    submitted = approval_gate.submit_set(gate, ids, set_id=set_id)
    assert submitted["ok"] is True, submitted
    return submitted


# ---------------------------------------------------------------------------
# The hash and the signature
# ---------------------------------------------------------------------------


def test_payload_hash_is_the_teacher_views_algorithm() -> None:
    """SHA-256 of key-sorted, compact JSON (web/approvals.py's payload_hash), recomputed here independently,
    and compared with the teacher view's own function when that module is present."""
    payload = {"set_id": "s", "questions": [{"id": "Q_1", "prompt": "−60 cm?"}]}
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert approval_gate.payload_hash(payload) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if importlib.util.find_spec("socratic_tutor.web.approvals") is not None:
        from socratic_tutor.web import approvals
        assert approval_gate.payload_hash(payload) == approvals.payload_hash(payload)
    # The order of the keys doesn't matter; one changed character does.
    assert approval_gate.payload_hash({"questions": payload["questions"], "set_id": "s"}) == approval_gate.payload_hash(payload)
    assert approval_gate.payload_hash({"set_id": "t", "questions": payload["questions"]}) != approval_gate.payload_hash(payload)


def test_a_signature_changes_when_anything_signed_changes() -> None:
    """The signature covers the set, the action, the version's hash, the approver and the edits."""
    base = approval_gate.make_signature("set_a", "approve", "h1", TEACHER, None, TEST_KEY)
    assert base == approval_gate.make_signature("set_a", "approve", "h1", TEACHER, None, TEST_KEY)
    others = [
        approval_gate.make_signature("set_b", "approve", "h1", TEACHER, None, TEST_KEY),
        approval_gate.make_signature("set_a", "reject", "h1", TEACHER, None, TEST_KEY),
        approval_gate.make_signature("set_a", "approve", "h2", TEACHER, None, TEST_KEY),
        approval_gate.make_signature("set_a", "approve", "h1", "teacher_2", None, TEST_KEY),
        approval_gate.make_signature("set_a", "approve", "h1", TEACHER, {"Q_1": {"prompt": "x"}}, TEST_KEY),
        approval_gate.make_signature("set_a", "approve", "h1", TEACHER, None, "another-key"),
    ]
    for other in others:
        assert other != base


def test_the_key_is_the_config_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """The key is config.APPROVAL_SIGNING_KEY (loaded from .env like every other setting); blank means no key."""
    monkeypatch.setattr(config, "APPROVAL_SIGNING_KEY", "a-server-key")
    assert approval_gate.signing_key() == "a-server-key"
    monkeypatch.setattr(config, "APPROVAL_SIGNING_KEY", "   ")
    assert approval_gate.signing_key() is None


def test_signing_without_a_key_is_impossible(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no APPROVAL_SIGNING_KEY, sign_decision raises instead of producing an unsigned decision."""
    monkeypatch.setattr(config, "APPROVAL_SIGNING_KEY", "")
    with pytest.raises(ValueError):
        approval_gate.sign_decision("set_a", "approve", "h1", TEACHER)


# ---------------------------------------------------------------------------
# submit_set and collect ([S1]-[S3], [C1]-[C3])
# ---------------------------------------------------------------------------


def test_submit_pauses_on_its_own_thread_and_publishes_nothing(gate: Any) -> None:
    """The set waits on thread "qbset:set_a" with exactly the stored rows; nothing is published yet."""
    ids = propose_two()
    submitted = submit(gate, ids)
    assert submitted["thread_id"] == "qbset:set_a"
    questions = submitted["payload"]["questions"]
    assert len(questions) == 2
    assert sorted(questions[0]) == ["concept_id", "difficulty", "gold_answer", "id", "prompt"]
    assert questions[1]["gold_answer"] == "-60 cm"
    # The teacher view and the gate see the same version.
    waiting = approval_gate.pending_set(gate, "set_a")
    assert waiting["payload"] == submitted["payload"]
    assert waiting["payload_hash"] == submitted["payload_hash"]
    for question_id in ids:
        assert status_of(question_id) == "pending_approval"


def test_the_interrupt_value_is_exactly_the_hashed_payload(gate: Any) -> None:
    """Anyone who hashes what interrupt() shows (the teacher view does) gets the gate's own hash."""
    submitted = submit(gate, propose_two())
    snapshot = gate.get_state(approval_gate.thread_config("set_a"))
    shown = snapshot.tasks[0].interrupts[0].value
    assert shown == submitted["payload"]
    assert approval_gate.payload_hash(shown) == submitted["payload_hash"]


def test_submit_refuses_unknown_or_already_decided_questions(gate: Any) -> None:
    """[C2]: an id not in the bank, or a question already approved, means the set doesn't wait at all."""
    ids = propose_two()
    unknown = approval_gate.submit_set(gate, [ids[0], "Q_missing"], set_id="set_unknown")
    assert unknown == {"ok": False, "error": "Some of the questions aren't in the bank."}
    question_bank.publish_approved_question(ids[1])
    decided = approval_gate.submit_set(gate, ids, set_id="set_decided")
    assert decided["ok"] is False
    assert "already 'approved'" in decided["error"]
    assert approval_gate.pending_set(gate, "set_unknown") is None
    assert approval_gate.pending_set(gate, "set_decided") is None


def test_submit_refuses_bad_inputs(gate: Any) -> None:
    """[S1]: empty or oversized sets, repeated ids, non-text ids, an unsafe set id, and a set id used before."""
    ids = propose_two()
    assert approval_gate.submit_set(gate, [], set_id="s1")["ok"] is False
    assert approval_gate.submit_set(gate, [ids[0], ids[0]], set_id="s2")["ok"] is False
    assert approval_gate.submit_set(gate, ["Q_x"] * (approval_gate.MAX_SET_SIZE + 1), set_id="s3")["ok"] is False
    assert approval_gate.submit_set(gate, [ids[0], 7], set_id="s4")["ok"] is False
    assert approval_gate.submit_set(gate, ids, set_id="bad id!")["ok"] is False
    submit(gate, ids, set_id="s5")
    again = approval_gate.submit_set(gate, ids, set_id="s5")
    assert again == {"ok": False, "error": "This set id is already in use."}


# ---------------------------------------------------------------------------
# Approve and reject ([G2], [G4], [G5])
# ---------------------------------------------------------------------------


def test_a_signed_approval_publishes_the_whole_set(gate: Any) -> None:
    """The happy path: the teacher approves the version on screen; both questions go live."""
    ids = propose_two()
    submitted = submit(gate, ids)
    result = approval_gate.decide(gate, "set_a", sign("set_a", "approve", submitted["payload_hash"]))
    assert result["status"] == "published"
    assert result["note"] == "Published by teacher_1."
    for question_id in ids:
        assert status_of(question_id) == "approved"
    assert approval_gate.pending_set(gate, "set_a") is None


def test_an_approval_for_another_hash_is_refused_as_stale(gate: Any) -> None:
    """[G2]: a decision signed for a different version is refused; nothing is published; the set still waits."""
    ids = propose_two()
    submit(gate, ids)
    result = approval_gate.decide(gate, "set_a", sign("set_a", "approve", "0" * 64))
    assert result["status"] == "waiting"
    assert "stale" in result["note"]
    assert status_of(ids[0]) == "pending_approval"
    assert approval_gate.pending_set(gate, "set_a") is not None


def test_unsigned_or_wrongly_signed_decisions_are_refused(gate: Any) -> None:
    """[G2] (S3-10): no signature, a signature made with another key, or one made for another action."""
    ids = propose_two()
    submitted = submit(gate, ids)
    good = sign("set_a", "approve", submitted["payload_hash"])
    unsigned = dict(good)
    del unsigned["signature"]
    other_key = approval_gate.sign_decision("set_a", "approve", submitted["payload_hash"], TEACHER, key="not-the-key")
    swapped = dict(sign("set_a", "reject", submitted["payload_hash"]))
    swapped["action"] = "approve"
    for decision in [unsigned, other_key, swapped]:
        result = approval_gate.decide(gate, "set_a", decision)
        assert result["status"] == "waiting"
        assert "signature" in result["note"]
    assert status_of(ids[0]) == "pending_approval"


def test_without_a_key_on_the_server_nothing_can_be_decided(gate: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed (S3-10): if APPROVAL_SIGNING_KEY isn't set, every decision is refused."""
    ids = propose_two()
    submitted = submit(gate, ids)
    decision = sign("set_a", "approve", submitted["payload_hash"])
    monkeypatch.setattr(config, "APPROVAL_SIGNING_KEY", "")
    result = approval_gate.decide(gate, "set_a", decision)
    assert result["status"] == "waiting"
    assert "APPROVAL_SIGNING_KEY" in result["note"]
    assert status_of(ids[0]) == "pending_approval"


def test_a_decision_must_name_the_approver(gate: Any) -> None:
    """[G2]: an empty approver is refused, even when signed."""
    submitted = submit(gate, propose_two())
    result = approval_gate.decide(gate, "set_a", sign("set_a", "approve", submitted["payload_hash"], approver=""))
    assert result["status"] == "waiting"
    assert "approver" in result["note"]


def test_an_unknown_action_or_a_decision_that_is_not_a_dict_is_refused(gate: Any) -> None:
    """[G2]: "publish" isn't an action, and a plain string isn't a decision."""
    submitted = submit(gate, propose_two())
    publish = sign("set_a", "approve", submitted["payload_hash"])
    publish["action"] = "publish"
    unknown = approval_gate.decide(gate, "set_a", publish)
    assert unknown["status"] == "waiting"
    assert unknown["note"] == "Unknown action: it must be approve, edit or reject."
    not_a_dict = approval_gate.decide(gate, "set_a", "approve")
    assert not_a_dict["status"] == "waiting"
    assert not_a_dict["note"] == "The decision isn't in the expected form."


def test_an_approver_with_control_characters_or_spaces_is_refused(gate: Any) -> None:
    """[G2]: the approver is the login's id: no line breaks, no surrounding spaces (they could blur the record)."""
    submitted = submit(gate, propose_two())
    for approver in ["teacher_1\nteacher_2", " teacher_1", "x" * (approval_gate.MAX_APPROVER_LENGTH + 1)]:
        result = approval_gate.decide(gate, "set_a", sign("set_a", "approve", submitted["payload_hash"], approver=approver))
        assert result["status"] == "waiting", repr(approver)
    assert approval_gate.pending_set(gate, "set_a") is not None


def test_a_hash_or_signature_that_is_not_64_hex_characters_is_refused(gate: Any) -> None:
    """[G2]: a hash or signature in the wrong form is refused, without ever being compared."""
    submitted = submit(gate, propose_two())
    short_hash = sign("set_a", "approve", "abc")
    assert approval_gate.decide(gate, "set_a", short_hash)["note"].startswith("The decision must carry the hash")
    upper = sign("set_a", "approve", submitted["payload_hash"])
    upper["signature"] = upper["signature"].upper()
    assert "signature" in approval_gate.decide(gate, "set_a", upper)["note"]


def test_a_malformed_signature_does_not_jam_the_set(gate: Any) -> None:
    """Found by the review: a signature like "é" made hmac.compare_digest raise, and LangGraph then replayed the
    same decision on every later resume, so the set was stuck for good. Now it's refused, and a correct
    decision afterwards still works."""
    ids = propose_two()
    submitted = submit(gate, ids)
    bad = sign("set_a", "approve", submitted["payload_hash"])
    bad["signature"] = "é"
    refused = approval_gate.decide(gate, "set_a", bad)
    assert refused["status"] == "waiting"
    # Refused by the signature check itself (not caught later as an "Unexpected problem").
    assert refused["note"] == "The decision's signature doesn't match, so it wasn't made through the teacher's login."
    good = approval_gate.decide(gate, "set_a", sign("set_a", "approve", submitted["payload_hash"]))
    assert good["status"] == "published"
    assert status_of(ids[0]) == "approved"


def test_a_payload_that_cannot_be_hashed_does_not_jam_the_set(gate: Any) -> None:
    """Found by the review: a payload with mixed key types (it can't be key-sorted) used to raise after interrupt()."""
    submitted = submit(gate, propose_two())
    odd = sign("set_a", "approve", submitted["payload_hash"])
    odd["payload"] = {"set_id": "set_a", 1: "x"}
    result = approval_gate.decide(gate, "set_a", odd)
    assert result["status"] == "waiting"
    assert result["note"] == "The payload sent with the decision isn't the version on screen."
    good = approval_gate.decide(gate, "set_a", sign("set_a", "approve", submitted["payload_hash"]))
    assert good["status"] == "published"


def test_a_decision_that_is_not_plain_json_is_refused_before_anything_changes(gate: Any) -> None:
    """Found by the review: a value the checkpointer can't save used to fail AFTER the bank had changed.
    decide() now refuses it first; the set keeps waiting, and the bank is untouched."""
    ids = propose_two()
    submitted = submit(gate, ids)
    unsaveable = sign("set_a", "approve", submitted["payload_hash"])
    unsaveable["extra"] = object()
    result = approval_gate.decide(gate, "set_a", unsaveable)
    assert result["status"] == "waiting"
    assert result["note"] == "The decision can't be read, so it wasn't applied."
    assert status_of(ids[0]) == "pending_approval"
    assert approval_gate.pending_set(gate, "set_a") is not None


def test_a_signed_rejection_rejects_the_whole_set(gate: Any) -> None:
    """[G5]: both questions become 'rejected'; nothing goes live."""
    ids = propose_two()
    submitted = submit(gate, ids)
    result = approval_gate.decide(gate, "set_a", sign("set_a", "reject", submitted["payload_hash"]))
    assert result == {"status": "rejected", "note": "Rejected by teacher_1.", "payload_hash": submitted["payload_hash"]}
    for question_id in ids:
        assert status_of(question_id) == "rejected"


# ---------------------------------------------------------------------------
# Edit ([G3]) and the live demo
# ---------------------------------------------------------------------------


def test_the_live_demo_an_edit_invalidates_the_earlier_approval(gate: Any) -> None:
    """capstone guide p.3: approve H1 after an edit made H2 is refused; approving H2 publishes the edited version."""
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]
    changes = {ids[1]: {"gold_answer": "-60.0 cm"}}
    edited = approval_gate.decide(gate, "set_a", sign("set_a", "edit", hash_one, changes=changes))
    hash_two = edited["payload_hash"]
    assert edited["status"] == "waiting"
    assert hash_two != hash_one
    assert edited["note"] == "Edited: approve this version to publish it."
    stale = approval_gate.decide(gate, "set_a", sign("set_a", "approve", hash_one))
    assert stale["status"] == "waiting"
    assert status_of(ids[0]) == "pending_approval"
    published = approval_gate.decide(gate, "set_a", sign("set_a", "approve", hash_two))
    assert published["status"] == "published"
    assert question_bank.get_questions([ids[1]])[0]["gold_answer"] == "-60.0 cm"


def test_an_edit_changes_the_waiting_version_not_the_bank(gate: Any) -> None:
    """[G3]: until the edited version is approved, the bank still holds the original text."""
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]
    approval_gate.decide(gate, "set_a", sign("set_a", "edit", hash_one, changes={ids[0]: {"prompt": "  Find the current.  "}}))
    waiting = approval_gate.pending_set(gate, "set_a")
    assert waiting["payload"]["questions"][0]["prompt"] == "Find the current."
    assert question_bank.get_questions([ids[0]])[0]["prompt"] == OHMS_PROMPT


def test_an_edit_with_an_unreadable_answer_key_is_refused(gate: Any) -> None:
    """S3-8: an edited key the grader couldn't read ("I = 3 A") is refused, and the version stays as it was."""
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]
    result = approval_gate.decide(gate, "set_a", sign("set_a", "edit", hash_one, changes={ids[0]: {"gold_answer": "I = 3 A"}}))
    assert result["status"] == "waiting"
    assert result["note"].startswith("The edited answer key can't be used")
    assert result["payload_hash"] == hash_one


def test_edits_outside_the_editable_fields_or_the_set_are_refused(gate: Any) -> None:
    """[G3]: concept_id can't be edited; an unknown question, a bad difficulty, an empty prompt or a bad shape is refused."""
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]
    refused_changes: list[Any] = [
        {ids[0]: {"concept_id": "concept_lens_formula"}},
        {"Q_not_in_set": {"prompt": "x"}},
        {ids[0]: {"difficulty": "tough"}},
        {ids[0]: {"prompt": "   "}},
        {ids[0]: "3 A"},
        {},
        "change it",
    ]
    expected_notes = [
        "Only difficulty, prompt, gold_answer can be edited, not concept_id.",
        "The edit names a question that isn't in this set.",
        "difficulty must be one of easy, medium, hard.",
        "The edited prompt is empty.",
        "The edit for a question must be {field: new value}.",
        "An edit needs 'changes': {question_id: {field: new value}}.",
        "An edit needs 'changes': {question_id: {field: new value}}.",
    ]
    for changes, expected_note in zip(refused_changes, expected_notes):
        result = approval_gate.decide(gate, "set_a", sign("set_a", "edit", hash_one, changes=changes))
        assert result["status"] == "waiting", changes
        assert result["payload_hash"] == hash_one, changes
        # The note says why, so the test can't pass because of some other refusal (a signature problem, say).
        assert result["note"] == expected_note, changes


def test_an_edit_for_an_older_version_is_refused(gate: Any) -> None:
    """[G2]: after one edit, a second edit still signed for the first version is refused."""
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]
    approval_gate.decide(gate, "set_a", sign("set_a", "edit", hash_one, changes={ids[0]: {"gold_answer": "3.0 A"}}))
    result = approval_gate.decide(gate, "set_a", sign("set_a", "edit", hash_one, changes={ids[0]: {"gold_answer": "3 A"}}))
    assert result["status"] == "waiting"
    assert "older version" in result["note"]


# ---------------------------------------------------------------------------
# The payload sent with a decision (the teacher view always sends one)
# ---------------------------------------------------------------------------


def test_the_teacher_views_payload_of_the_current_version_is_accepted(gate: Any) -> None:
    """web/server.py sends the stored payload with every decision; when it's the version on screen, it's fine."""
    ids = propose_two()
    submitted = submit(gate, ids)
    result = approval_gate.decide(gate, "set_a", sign("set_a", "approve", submitted["payload_hash"], payload=submitted["payload"]))
    assert result["status"] == "published"


def test_an_old_version_sent_with_its_own_hash_is_refused_after_an_edit(gate: Any) -> None:
    """Found by the review: after an edit made V2, an approval signed for H1 that carried V1 itself was accepted,
    the original key went live and the edit was lost. Every decision must now be for the version on screen."""
    ids = propose_two()
    submitted = submit(gate, ids)
    approval_gate.decide(gate, "set_a", sign("set_a", "edit", submitted["payload_hash"], changes={ids[1]: {"gold_answer": "-60.0 cm"}}))
    for action in ["approve", "reject"]:
        result = approval_gate.decide(gate, "set_a", sign("set_a", action, submitted["payload_hash"], payload=submitted["payload"]))
        assert result["status"] == "waiting", action
        assert "stale" in result["note"], action
    assert status_of(ids[1]) == "pending_approval"
    assert question_bank.get_questions([ids[1]])[0]["gold_answer"] == "-60 cm"


def test_a_version_edited_outside_the_gate_is_refused(gate: Any) -> None:
    """Edits go through the gate's own "edit" action. A payload edited elsewhere, signed with its own hash, is
    stale; one sent with the current hash but different content isn't the version on screen."""
    ids = propose_two()
    submitted = submit(gate, ids)
    edited_elsewhere = json.loads(json.dumps(submitted["payload"]))
    edited_elsewhere["questions"][0]["difficulty"] = "medium"
    own_hash = approval_gate.decide(gate, "set_a", sign("set_a", "approve", approval_gate.payload_hash(edited_elsewhere), payload=edited_elsewhere))
    assert own_hash["status"] == "waiting"
    assert "stale" in own_hash["note"]
    current_hash = approval_gate.decide(gate, "set_a", sign("set_a", "approve", submitted["payload_hash"], payload=edited_elsewhere))
    assert current_hash["note"] == "The payload sent with the decision isn't the version on screen."
    for question_id in ids:
        assert status_of(question_id) == "pending_approval"


def test_an_edit_back_to_the_original_text_does_not_revive_the_old_approval(gate: Any) -> None:
    """Found by the review: if an edit brought the text back to version 1, an old approval for H1 fitted again.
    The version number is part of the payload, so every version has a new hash."""
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]
    second = approval_gate.decide(gate, "set_a", sign("set_a", "edit", hash_one, changes={ids[0]: {"gold_answer": "3.0 A"}}))
    third = approval_gate.decide(gate, "set_a", sign("set_a", "edit", second["payload_hash"], changes={ids[0]: {"gold_answer": "3 A"}}))
    assert third["payload_hash"] != hash_one
    result = approval_gate.decide(gate, "set_a", sign("set_a", "approve", hash_one))
    assert result["status"] == "waiting"
    assert "stale" in result["note"]


# ---------------------------------------------------------------------------
# The bank changes while the set waits ([G4] all or nothing)
# ---------------------------------------------------------------------------


def test_a_question_changed_in_the_bank_since_the_pause_publishes_nothing(gate: Any) -> None:
    """S3-6: one row changed through the per-question view; the approval publishes nothing, and the set waits
    again with the fresh version (a new hash), saying why."""
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]
    connection = sqlite3.connect(question_bank.DB_PATH)
    connection.execute("UPDATE questions SET gold_answer = ? WHERE id = ?", ("-50 cm", ids[1]))
    connection.commit()
    connection.close()
    result = approval_gate.decide(gate, "set_a", sign("set_a", "approve", hash_one))
    assert result["status"] == "waiting"
    assert result["payload_hash"] != hash_one
    assert "changed since it was shown" in result["note"]
    assert status_of(ids[0]) == "pending_approval"
    fresh = approval_gate.pending_set(gate, "set_a")
    assert fresh["payload"]["questions"][1]["gold_answer"] == "-50 cm"
    # One approval of the fresh version then publishes all of it.
    published = approval_gate.decide(gate, "set_a", sign("set_a", "approve", fresh["payload_hash"]))
    assert published["status"] == "published"


def test_a_question_decided_elsewhere_ends_the_set_without_changing_it(gate: Any) -> None:
    """A row approved through the per-question button: the set can't be completed, so it ends; the other row stays pending."""
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]
    question_bank.publish_approved_question(ids[1])
    result = approval_gate.decide(gate, "set_a", sign("set_a", "approve", hash_one))
    assert result["status"] == "refused"
    assert result["note"].endswith("Nothing in this set was changed.")
    assert status_of(ids[0]) == "pending_approval"


def test_a_database_error_while_publishing_is_a_refusal_not_a_crash(gate: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """[G4]: an unexpected error is reported by its type; nothing is published and the set waits again."""
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]

    def locked(shown: list[dict[str, Any]], approved: list[dict[str, Any]]) -> dict[str, Any]:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(question_bank, "publish_question_set", locked)
    result = approval_gate.decide(gate, "set_a", sign("set_a", "approve", hash_one))
    assert result["status"] == "waiting"
    assert result["note"] == "Unexpected problem (OperationalError); nothing was changed."
    assert status_of(ids[0]) == "pending_approval"


def test_a_database_error_keeps_the_teachers_edit(gate: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Found by the review: after a temporary error, the waiting version used to be reset to the bank rows, which
    threw away the teacher's edit. Now the same (edited) version waits, and approving it once the database is
    back publishes the edit."""
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]
    edited = approval_gate.decide(gate, "set_a", sign("set_a", "edit", hash_one, changes={ids[1]: {"gold_answer": "-60.0 cm"}}))
    real_publish = question_bank.publish_question_set

    def locked(shown: list[dict[str, Any]], approved: list[dict[str, Any]]) -> dict[str, Any]:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(question_bank, "publish_question_set", locked)
    failed = approval_gate.decide(gate, "set_a", sign("set_a", "approve", edited["payload_hash"]))
    assert failed["payload_hash"] == edited["payload_hash"]
    monkeypatch.setattr(question_bank, "publish_question_set", real_publish)
    published = approval_gate.decide(gate, "set_a", sign("set_a", "approve", edited["payload_hash"]))
    assert published["status"] == "published"
    assert question_bank.get_questions([ids[1]])[0]["gold_answer"] == "-60.0 cm"


# ---------------------------------------------------------------------------
# The life of a run: restart, double click, other threads, collect once, nothing at submit
# ---------------------------------------------------------------------------


def test_a_restart_keeps_the_waiting_set(bank: None, tmp_path: Path) -> None:
    """A new connection and a new graph on the same checkpoint file still see the set, and can approve it."""
    ids = propose_two()
    checkpoint_file = tmp_path / "restart.sqlite"
    first_connection = sqlite3.connect(checkpoint_file, check_same_thread=False)
    first_graph = approval_gate.build_approval_graph(SqliteSaver(first_connection))
    hash_one = submit(first_graph, ids)["payload_hash"]
    # "Restart": everything in memory is gone; only the file remains.
    first_connection.close()
    second_connection = sqlite3.connect(checkpoint_file, check_same_thread=False)
    try:
        second_graph = approval_gate.build_approval_graph(SqliteSaver(second_connection))
        assert approval_gate.pending_set(second_graph, "set_a")["payload_hash"] == hash_one
        result = approval_gate.decide(second_graph, "set_a", sign("set_a", "approve", hash_one))
        assert result["status"] == "published"
    finally:
        second_connection.close()


def test_a_second_click_changes_nothing(gate: Any) -> None:
    """[D1]: after the set is published, the same decision again reports not_waiting."""
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]
    decision = sign("set_a", "approve", hash_one)
    assert approval_gate.decide(gate, "set_a", decision)["status"] == "published"
    assert approval_gate.decide(gate, "set_a", decision)["status"] == "not_waiting"
    assert approval_gate.decide(gate, "no_such_set", decision)["status"] == "not_waiting"


def decide_when_all_are_ready(gate: Any, set_id: str, start_together: threading.Barrier, decision: dict[str, Any],
                              results: list[dict[str, Any]]) -> None:
    """One of two simultaneous clicks on set_id: wait until both are ready, then decide."""
    start_together.wait(timeout=10)
    results.append(approval_gate.decide(gate, set_id, decision))


def test_two_decisions_at_the_same_moment_report_what_really_happened(gate: Any) -> None:
    """Found by the review: approve + reject at the same moment could report "refused" although the set was
    published. Now one decision applies and the other is told the truth, whichever goes first."""
    for second_action in ["reject", "edit"]:
        ids = propose_two()
        set_id = "set_race_" + second_action
        hash_one = submit(gate, ids, set_id=set_id)["payload_hash"]
        approve = approval_gate.sign_decision(set_id, "approve", hash_one, TEACHER, key=TEST_KEY)
        changes = None
        if second_action == "edit":
            changes = {ids[0]: {"gold_answer": "3.0 A"}}
        other = approval_gate.sign_decision(set_id, second_action, hash_one, TEACHER, changes=changes, key=TEST_KEY)
        start_together = threading.Barrier(2)
        results: list[dict[str, Any]] = []
        first = threading.Thread(target=decide_when_all_are_ready, args=(gate, set_id, start_together, approve, results))
        second = threading.Thread(target=decide_when_all_are_ready, args=(gate, set_id, start_together, other, results))
        first.start()
        second.start()
        first.join(timeout=30)
        second.join(timeout=30)
        statuses: list[str] = []
        for result in results:
            statuses.append(result["status"])
        statuses.sort()
        bank_status = status_of(ids[0])
        # Each possible order, and what both callers must have been told:
        if bank_status == "approved":
            assert statuses == ["not_waiting", "published"]      # approve first; the other click found nothing waiting
        elif bank_status == "rejected":
            assert statuses == ["not_waiting", "rejected"]       # reject first
        else:
            assert statuses == ["waiting", "waiting"]            # edit first; the approval was then for an older version


def test_a_decision_waits_for_another_decision_on_the_same_set(gate: Any) -> None:
    """The per-set lock, checked directly: while the set's lock is held, decide() doesn't go ahead."""
    hash_one = submit(gate, propose_two())["payload_hash"]
    results: list[dict[str, Any]] = []
    lock = approval_gate.lock_for("set_a")
    lock.acquire()
    worker = threading.Thread(target=decide_when_all_are_ready, args=(gate, "set_a", threading.Barrier(1), sign("set_a", "approve", hash_one), results))
    worker.start()
    worker.join(timeout=0.5)
    # Still blocked: nothing decided while the other decision holds the lock.
    assert results == []
    lock.release()
    worker.join(timeout=30)
    assert results[0]["status"] == "published"


def test_sets_and_other_threads_are_independent(gate: Any) -> None:
    """Two sets wait side by side; deciding one leaves the other waiting; a student's thread has no state here."""
    first_ids = propose_two()
    second_ids = propose_two()
    first = submit(gate, first_ids, set_id="set_one")
    submit(gate, second_ids, set_id="set_two")
    approval_gate.decide(gate, "set_one", sign("set_one", "approve", first["payload_hash"]))
    assert approval_gate.pending_set(gate, "set_one") is None
    assert approval_gate.pending_set(gate, "set_two") is not None
    assert status_of(second_ids[0]) == "pending_approval"
    assert gate.get_state({"configurable": {"thread_id": "session-123"}}).values == {}


def test_collect_runs_once_and_nothing_is_published_at_submit(gate: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """collect reads the rows once (not again on each resume), and submitting never publishes."""
    calls: dict[str, int] = {"get_questions": 0, "publish": 0}
    real_get_questions = question_bank.get_questions
    real_publish = question_bank.publish_question_set

    def counting_get_questions(question_ids: list[str]) -> list[dict[str, Any]]:
        calls["get_questions"] = calls["get_questions"] + 1
        return real_get_questions(question_ids)

    def counting_publish(shown: list[dict[str, Any]], approved: list[dict[str, Any]]) -> dict[str, Any]:
        calls["publish"] = calls["publish"] + 1
        return real_publish(shown, approved)

    monkeypatch.setattr(question_bank, "get_questions", counting_get_questions)
    monkeypatch.setattr(question_bank, "publish_question_set", counting_publish)
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]
    assert calls == {"get_questions": 1, "publish": 0}
    # An edit and a refused decision resume the gate twice; collect doesn't run again.
    edited = approval_gate.decide(gate, "set_a", sign("set_a", "edit", hash_one, changes={ids[0]: {"gold_answer": "3.0 A"}}))
    approval_gate.decide(gate, "set_a", sign("set_a", "approve", "0" * 64))
    assert calls == {"get_questions": 1, "publish": 0}
    approval_gate.decide(gate, "set_a", sign("set_a", "approve", edited["payload_hash"]))
    assert calls == {"get_questions": 1, "publish": 1}


# ---------------------------------------------------------------------------
# The log ([A5]/[G6])
# ---------------------------------------------------------------------------


def test_the_log_names_the_approver_but_never_the_question_text(gate: Any, log_lines: list[str]) -> None:
    """One line per submit and per decision; the approver and the wait are there, the questions are not."""
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]
    approval_gate.decide(gate, "set_a", sign("set_a", "approve", "0" * 64))
    approval_gate.decide(gate, "set_a", sign("set_a", "approve", hash_one))
    assert len(log_lines) == 3
    assert log_lines[0].startswith("set=set_a action=submit outcome=waiting questions=2")
    assert "outcome=refused approver=teacher_1" in log_lines[1]
    assert "outcome=published approver=teacher_1" in log_lines[2]
    # The approval came within a second of the submit, so it's flagged as fast.
    assert "fast=True" in log_lines[2]
    for line in log_lines:
        assert "battery" not in line
        assert "concave" not in line
        assert "-60 cm" not in line


def test_a_crafted_approver_name_cannot_add_log_fields(gate: Any, log_lines: list[str]) -> None:
    """An approver like 'x outcome=published' is logged as one safe field."""
    hash_one = submit(gate, propose_two())["payload_hash"]
    approval_gate.decide(gate, "set_a", sign("set_a", "reject", hash_one, approver="x outcome=published"))
    line = log_lines[-1]
    assert line.count(" outcome=") == 1
    assert "approver=x_outcome_published" in line


def test_double_clicks_and_refused_submits_are_logged_too(gate: Any, log_lines: list[str]) -> None:
    """Found by the review: some decisions wrote no log line. Every submit and every decision now writes one."""
    approval_gate.submit_set(gate, [], set_id="set_empty")
    approval_gate.decide(gate, "set_nothing", sign("set_nothing", "approve", "0" * 64))
    assert log_lines[0].startswith("set=set_empty action=submit outcome=refused")
    assert log_lines[1].startswith("set=set_nothing action=unknown outcome=not_waiting")


def test_fast_is_measured_from_when_the_version_appeared(gate: Any, log_lines: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Found by the review: the wait was counted from the submit. An approval 1 s after an edit (which showed a
    new version) is fast, even though the set itself had waited 100 s."""
    clock = {"now": 1000.0}

    def fake_now() -> float:
        return clock["now"]

    monkeypatch.setattr(approval_gate, "now", fake_now)
    ids = propose_two()
    hash_one = submit(gate, ids)["payload_hash"]
    clock["now"] = 1100.0
    edited = approval_gate.decide(gate, "set_a", sign("set_a", "edit", hash_one, changes={ids[0]: {"gold_answer": "3.0 A"}}))
    clock["now"] = 1101.0
    approval_gate.decide(gate, "set_a", sign("set_a", "approve", edited["payload_hash"]))
    assert "wait_s=100.0" in log_lines[1]
    assert "wait_s=1.0 fast=True" in log_lines[2]


# ---------------------------------------------------------------------------
# propose_set (the question setter's one call) and the shared graph
# ---------------------------------------------------------------------------


def two_known_concepts() -> list[str]:
    """Stand-in for the concept graph, so these tests never read data/concept_graph.json."""
    return ["concept_ohms_law", "concept_mirror_formula"]


@pytest.fixture
def known_concepts(monkeypatch: pytest.MonkeyPatch) -> None:
    """The question-bank checks see two known concepts."""
    monkeypatch.setattr(question_bank_server, "load_concept_ids", two_known_concepts)


def draft(concept_id: str, prompt: str, gold_answer: str) -> dict[str, Any]:
    """One draft question, as the question setter would make it."""
    return {"concept_id": concept_id, "difficulty": "medium", "prompt": prompt, "gold_answer": gold_answer}


def test_propose_set_saves_the_drafts_and_sends_one_set_to_the_teacher(gate: Any, known_concepts: None) -> None:
    """[P2]-[P5]: both drafts are checked and saved (pending), and they wait as ONE set; the student is told."""
    result = approval_gate.propose_set(
        [draft("concept_ohms_law", OHMS_PROMPT, "3 A"), draft("concept_mirror_formula", MIRROR_PROMPT, "-60 cm")],
        set_id="set_p", graph=gate,
    )
    assert result["ok"] is True
    assert result["thread_id"] == "qbset:set_p"
    assert len(result["question_ids"]) == 2
    assert result["refused"] == []
    assert result["student_message"] == "Your teacher will review 2 new practice questions."
    waiting = approval_gate.pending_set(gate, "set_p")
    ids_waiting: list[str] = []
    for question in waiting["payload"]["questions"]:
        ids_waiting.append(question["id"])
    assert ids_waiting == result["question_ids"]
    for question_id in result["question_ids"]:
        assert status_of(question_id) == "pending_approval"


def test_propose_set_reports_a_refused_draft_and_sends_the_rest(gate: Any, known_concepts: None) -> None:
    """[P2]: a draft with an unreadable key ("I = 3 A") is refused with its reason; the good one still goes."""
    result = approval_gate.propose_set(
        [draft("concept_mirror_formula", MIRROR_PROMPT, "-60 cm"), draft("concept_ohms_law", OHMS_PROMPT, "I = 3 A")],
        set_id="set_q", graph=gate,
    )
    assert result["ok"] is True
    assert len(result["question_ids"]) == 1
    assert result["refused"][0]["draft"] == 1
    assert result["refused"][0]["error"].startswith("Write only the value")
    assert result["student_message"] == "Your teacher will review 1 new practice question."


def test_propose_set_with_nothing_valid_sends_nothing(gate: Any, known_concepts: None) -> None:
    """[P3]: every draft refused (an unknown concept, a non-text field): nothing is saved and nothing waits."""
    result = approval_gate.propose_set(
        [draft("concept_photosynthesis", OHMS_PROMPT, "3 A"), {"concept_id": "concept_ohms_law", "difficulty": "easy", "prompt": None, "gold_answer": "3 A"}],
        set_id="set_r", graph=gate,
    )
    assert result["ok"] is False
    assert result["error"] == "None of the drafts could be saved, so nothing was sent to the teacher."
    assert len(result["refused"]) == 2
    assert result["refused"][1]["error"] == "The draft's prompt is missing or isn't text."
    assert approval_gate.pending_set(gate, "set_r") is None


def test_propose_set_refuses_a_bad_list(gate: Any, known_concepts: None) -> None:
    """[P1]: not a list, an empty list, or too many drafts."""
    too_many: list[dict[str, Any]] = []
    for number in range(approval_gate.MAX_SET_SIZE + 1):
        too_many.append(draft("concept_ohms_law", OHMS_PROMPT + " " + str(number), "3 A"))
    for drafts in ["a draft", [], too_many]:
        result = approval_gate.propose_set(drafts, graph=gate)
        assert result["ok"] is False
        assert result["error"].startswith("propose_set needs 1 to")


def test_propose_set_never_publishes_anything(gate: Any, known_concepts: None) -> None:
    """Proposing only saves drafts: until the teacher approves, students see none of them."""
    result = approval_gate.propose_set([draft("concept_ohms_law", OHMS_PROMPT, "3 A")], set_id="set_s", graph=gate)
    assert status_of(result["question_ids"][0]) == "pending_approval"


@pytest.fixture
def shared_graph_in_tmp(bank: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """get_approval_graph() builds its graph on config.INDEX_DIR: point that at tmp_path, with a fresh holder."""
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path)
    holder: dict[str, Any] = {"graph": None, "connection": None}
    monkeypatch.setattr(approval_gate, "APPROVAL_GRAPH_HOLDER", holder)
    yield holder
    if holder["connection"] is not None:
        holder["connection"].close()


def test_get_approval_graph_is_one_shared_graph_on_the_app_checkpoint_file(shared_graph_in_tmp: Any, tmp_path: Path) -> None:
    """The question setter and the teacher view get the SAME graph, so the view sees the sets the setter submits."""
    first = approval_gate.get_approval_graph()
    second = approval_gate.get_approval_graph()
    assert first is second
    submit(first, propose_two(), set_id="set_shared")
    assert (tmp_path / "checkpoints.sqlite").exists()
    assert approval_gate.pending_set(second, "set_shared") is not None


def test_propose_set_uses_the_shared_graph_by_default(shared_graph_in_tmp: Any, known_concepts: None) -> None:
    """Without a graph argument, propose_set submits to the shared graph, where the teacher view will look."""
    result = approval_gate.propose_set([draft("concept_ohms_law", OHMS_PROMPT, "3 A")], set_id="set_default")
    assert result["ok"] is True
    assert approval_gate.pending_set(approval_gate.get_approval_graph(), "set_default") is not None


# ---------------------------------------------------------------------------
# The teacher view's list of waiting sets (R4 plumbing PR-2)
# ---------------------------------------------------------------------------


def test_waiting_sets_lists_only_waiting_question_sets(gate: Any) -> None:
    """Two waiting sets, one published set, and a paused run on a thread that isn't a set: only the two sets."""
    ids = propose_two()
    submit(gate, [ids[0]], set_id="set_one")
    submit(gate, [ids[1]], set_id="set_two")
    # A third set, approved: it has finished, so it isn't listed.
    third = question_bank.propose_question("concept_ohms_law", "easy", "A 6 V battery is across 3 ohm. Current?", "2 A")
    done = submit(gate, [third["question_id"]], set_id="set_done")
    assert approval_gate.decide(gate, "set_done", sign("set_done", "approve", done["payload_hash"]))["status"] == "published"
    # A run paused on a thread that doesn't start with "qbset:" (the shared file also holds students' threads).
    fourth = question_bank.propose_question("concept_ohms_law", "easy", "A 9 V battery is across 3 ohm. Current?", "3 A")
    gate.invoke({"set_id": "set_other", "question_ids": [fourth["question_id"]]}, {"configurable": {"thread_id": "session-123"}})
    # Only the two waiting sets, the most recently active first.
    listed = approval_gate.waiting_sets(gate)
    listed_ids: list[str] = []
    for item in listed:
        listed_ids.append(item["set_id"])
    assert listed_ids == ["set_two", "set_one"]
    # Each item is exactly what pending_set gives for that set.
    assert listed[1] == approval_gate.pending_set(gate, "set_one")


def test_waiting_sets_does_not_hang_on_the_checkpointer_lock(gate: Any) -> None:
    """SqliteSaver.list holds the saver's lock while it yields; asking each set inside that loop would hang.
    Run waiting_sets in a separate thread and check that it finishes."""
    submit(gate, propose_two(), set_id="set_lock")
    results: list[Any] = []

    def run() -> None:
        results.append(approval_gate.waiting_sets(gate))

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(10)
    assert not worker.is_alive(), "waiting_sets hung on the checkpointer's lock"
    assert len(results[0]) == 1


def test_waiting_sets_shows_the_current_version_after_an_edit(gate: Any) -> None:
    """After an edit, the list shows the NEW version and its hash, so the teacher approves what they see."""
    submitted = submit(gate, propose_two(), set_id="set_edit")
    first_id = submitted["payload"]["questions"][0]["id"]
    changes = {first_id: {"prompt": "A 12 V battery is connected across a 6 ohm resistor. What is the current?",
                          "gold_answer": "2 A"}}
    edited = approval_gate.decide(gate, "set_edit", sign("set_edit", "edit", submitted["payload_hash"], changes=changes))
    assert edited["status"] == "waiting"
    listed = approval_gate.waiting_sets(gate)
    assert len(listed) == 1
    assert listed[0]["payload_hash"] == edited["payload_hash"]
    assert listed[0]["payload_hash"] != submitted["payload_hash"]
    assert listed[0]["payload"]["version"] == 2


def test_waiting_sets_without_a_checkpointer_is_empty() -> None:
    """A graph compiled without a checkpointer keeps no sets, so there is nothing to list."""
    assert approval_gate.waiting_sets(approval_gate.build_approval_graph(None)) == []


# ---------------------------------------------------------------------------
# The live-demo script
# ---------------------------------------------------------------------------


def test_the_demo_script_shows_the_edit_invalidating_the_approval(
    bank: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scripts/demo_edit_invalidates_approval.py runs on temporary files and shows the six steps.
    (run_demo points question_bank.DB_PATH at tmp_path; the bank fixture puts the real path back afterwards.)"""
    script = config.BASE_DIR / "scripts" / "demo_edit_invalidates_approval.py"
    spec = importlib.util.spec_from_file_location("demo_edit_invalidates_approval", script)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    # The demo signs with its own key; the gate reads the key from the environment.
    monkeypatch.setattr(config, "APPROVAL_SIGNING_KEY", demo.DEMO_KEY)
    lines = demo.run_demo(tmp_path)
    assert len(lines) == 6
    assert lines[3].startswith("4. approve with H1: waiting (This decision is for an older version")
    assert lines[4].startswith("5. approve with H2: published;")
    assert lines[4].endswith("key now -60.0 cm")
    assert lines[5] == "6. approve again: not_waiting"
