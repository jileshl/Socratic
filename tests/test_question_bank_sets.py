"""Tests for the question-set functions in question_bank.py: get_questions, publish_question_set and
reject_question_set (used by the approval gate, socratic_tutor/approval_gate.py).

Every test runs on a temporary database (the temp_bank fixture), so the real .index/question_bank.db is
never touched. The questions are NCERT-style examples written for these tests.
"""

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from socratic_tutor.tools import question_bank


OHMS_PROMPT: str = "A 12 V battery is connected across a 4 ohm resistor. What is the current?"
MIRROR_PROMPT: str = "An object is 30 cm in front of a concave mirror of focal length 20 cm. Where is the image?"


@pytest.fixture
def temp_bank(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the question bank at an empty temporary database for this test."""
    # question_bank reads DB_PATH each time it connects; monkeypatch puts the real path back afterwards.
    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "question_bank.db")
    question_bank._init_db()


def two_pending_questions() -> list[dict[str, Any]]:
    """Propose two questions and return them as the approval gate shows them (the five QUESTION_FIELDS)."""
    first = question_bank.propose_question("concept_ohms_law", "easy", OHMS_PROMPT, "3 A")
    second = question_bank.propose_question("concept_mirror_formula", "medium", MIRROR_PROMPT, "-60 cm")
    shown: list[dict[str, Any]] = []
    for row in question_bank.get_questions([first["question_id"], second["question_id"]]):
        question: dict[str, Any] = {}
        for field in question_bank.QUESTION_FIELDS:
            question[field] = row[field]
        shown.append(question)
    return shown


def stored_rows() -> dict[str, tuple[Any, ...]]:
    """Every row in the questions table, by id: (difficulty, prompt, gold_answer, status)."""
    connection = sqlite3.connect(question_bank.DB_PATH)
    rows = connection.execute("SELECT id, difficulty, prompt, gold_answer, status FROM questions").fetchall()
    connection.close()
    by_id: dict[str, tuple[Any, ...]] = {}
    for row in rows:
        by_id[row[0]] = (row[1], row[2], row[3], row[4])
    return by_id


def copy_of(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A deep-enough copy of a list of questions, so a test can edit one without changing the original."""
    copies: list[dict[str, Any]] = []
    for question in questions:
        copies.append(dict(question))
    return copies


def test_get_questions_keeps_the_order_and_leaves_out_missing_ids(temp_bank: None) -> None:
    """get_questions returns the rows (with their status) in the order asked; an unknown id is simply absent."""
    shown = two_pending_questions()
    found = question_bank.get_questions([shown[1]["id"], "Q_missing", shown[0]["id"]])
    found_ids: list[str] = []
    for row in found:
        found_ids.append(row["id"])
    assert found_ids == [shown[1]["id"], shown[0]["id"]]
    assert found[0]["status"] == "pending_approval"
    assert found[0]["prompt"] == MIRROR_PROMPT


def test_publishing_a_set_approves_every_question(temp_bank: None) -> None:
    """The happy path: both questions become 'approved', unchanged."""
    shown = two_pending_questions()
    result = question_bank.publish_question_set(shown, shown)
    assert result == {"published": [shown[0]["id"], shown[1]["id"]]}
    rows = stored_rows()
    assert rows[shown[0]["id"]] == ("easy", OHMS_PROMPT, "3 A", "approved")
    assert rows[shown[1]["id"]] == ("medium", MIRROR_PROMPT, "-60 cm", "approved")


def test_the_teachers_edits_are_saved_when_published(temp_bank: None) -> None:
    """The approved version may differ in difficulty, prompt or gold_answer; that version is what's published."""
    shown = two_pending_questions()
    approved = copy_of(shown)
    approved[1]["gold_answer"] = "-60.0 cm"
    approved[1]["difficulty"] = "hard"
    question_bank.publish_question_set(shown, approved)
    assert stored_rows()[shown[1]["id"]] == ("hard", MIRROR_PROMPT, "-60.0 cm", "approved")


def test_a_question_changed_since_it_was_shown_publishes_nothing(temp_bank: None) -> None:
    """All or nothing: the second row changed in the bank, so the first row's update is rolled back too."""
    shown = two_pending_questions()
    connection = sqlite3.connect(question_bank.DB_PATH)
    connection.execute("UPDATE questions SET gold_answer = ? WHERE id = ?", ("-50 cm", shown[1]["id"]))
    connection.commit()
    connection.close()
    result = question_bank.publish_question_set(shown, shown)
    assert result == {"published": [], "problem": "Question " + shown[1]["id"] + " changed since it was shown."}
    # The first question was checked and updated inside the transaction, then undone by the ROLLBACK.
    assert stored_rows()[shown[0]["id"]][3] == "pending_approval"


def test_a_question_already_decided_publishes_nothing(temp_bank: None) -> None:
    """A row approved elsewhere (the per-question button) stops the whole set; nothing else changes."""
    shown = two_pending_questions()
    question_bank.publish_approved_question(shown[1]["id"])
    result = question_bank.publish_question_set(shown, shown)
    assert result == {"published": [], "problem": "Question " + shown[1]["id"] + " is already 'approved'."}
    assert stored_rows()[shown[0]["id"]][3] == "pending_approval"


def test_a_question_no_longer_in_the_bank_publishes_nothing(temp_bank: None) -> None:
    """A deleted row stops the set."""
    shown = two_pending_questions()
    connection = sqlite3.connect(question_bank.DB_PATH)
    connection.execute("DELETE FROM questions WHERE id = ?", (shown[0]["id"],))
    connection.commit()
    connection.close()
    result = question_bank.publish_question_set(shown, shown)
    assert result["published"] == []
    assert result["problem"] == "Question " + shown[0]["id"] + " is no longer in the bank."
    assert stored_rows()[shown[1]["id"]][3] == "pending_approval"


def test_lists_that_do_not_match_are_refused_before_the_database(temp_bank: None) -> None:
    """Different lengths, a different id, a changed concept, an empty set or a missing field: refused, nothing changes."""
    shown = two_pending_questions()
    other_concept = copy_of(shown)
    other_concept[0]["concept_id"] = "concept_lens_formula"
    missing_field = copy_of(shown)
    del missing_field[0]["prompt"]
    refused: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = [
        (shown, shown[:1]),
        (shown, list(reversed(shown))),
        (shown, other_concept),
        ([], []),
        (shown, missing_field),
    ]
    for before, after in refused:
        result = question_bank.publish_question_set(before, after)
        assert result["published"] == []
        assert "problem" in result
    for row in stored_rows().values():
        assert row[3] == "pending_approval"


def test_text_that_looks_like_sql_is_stored_as_plain_text(temp_bank: None) -> None:
    """The values go in through "?" placeholders, so an edited prompt containing SQL is just text."""
    shown = two_pending_questions()
    approved = copy_of(shown)
    approved[0]["prompt"] = "x'; DROP TABLE questions; --"
    question_bank.publish_question_set(shown, approved)
    rows = stored_rows()
    # The table is still there, with both rows, and the prompt is stored exactly as written.
    assert len(rows) == 2
    assert rows[shown[0]["id"]][1] == "x'; DROP TABLE questions; --"


def change_a_row_in_the_gap(monkeypatch: pytest.MonkeyPatch, sql: str, values: tuple[Any, ...]) -> None:
    """Make another writer act exactly in the gap: after the rows are read and compared (step [R1]), before the
    transaction starts. The real check runs first and passes; then the other writer's change is saved."""
    real_rows_problem = question_bank._rows_problem

    def check_then_another_writer(shown: list[dict[str, Any]]) -> str | None:
        problem = real_rows_problem(shown)
        connection = sqlite3.connect(question_bank.DB_PATH)
        connection.execute(sql, values)
        connection.commit()
        connection.close()
        return problem

    monkeypatch.setattr(question_bank, "_rows_problem", check_then_another_writer)


def test_an_edit_in_the_gap_between_the_check_and_the_write_publishes_nothing(
    temp_bank: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reads are outside the transaction (to keep it short), so a row can change after the check. Each
    UPDATE repeats the checked values in its WHERE: the changed row updates 0 rows and the whole set rolls back,
    so the other writer's correction is not overwritten and nothing is half-published."""
    shown = two_pending_questions()
    change_a_row_in_the_gap(monkeypatch, "UPDATE questions SET gold_answer = ? WHERE id = ?", ("-50 cm", shown[1]["id"]))
    result = question_bank.publish_question_set(shown, shown)
    assert result == {"published": [], "problem": "Question " + shown[1]["id"] + " changed while the set was being saved."}
    rows = stored_rows()
    # The first row's update was rolled back, and the other writer's correction is still there.
    assert rows[shown[0]["id"]][3] == "pending_approval"
    assert rows[shown[1]["id"]] == ("medium", MIRROR_PROMPT, "-50 cm", "pending_approval")


def test_an_approval_in_the_gap_between_the_check_and_the_write_publishes_nothing(
    temp_bank: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-question button approves a row in the gap: that row updates 0 rows, so the set rolls back."""
    shown = two_pending_questions()
    change_a_row_in_the_gap(monkeypatch, "UPDATE questions SET status = 'approved' WHERE id = ?", (shown[1]["id"],))
    result = question_bank.reject_question_set(shown)
    assert result["rejected"] == []
    assert stored_rows()[shown[0]["id"]][3] == "pending_approval"


def test_rejecting_a_set_rejects_every_question(temp_bank: None) -> None:
    """The happy path for reject: both rows become 'rejected', text unchanged."""
    shown = two_pending_questions()
    result = question_bank.reject_question_set(shown)
    assert result == {"rejected": [shown[0]["id"], shown[1]["id"]]}
    rows = stored_rows()
    assert rows[shown[0]["id"]] == ("easy", OHMS_PROMPT, "3 A", "rejected")
    assert rows[shown[1]["id"]][3] == "rejected"


def test_rejecting_is_all_or_nothing_too(temp_bank: None) -> None:
    """One row already decided: nothing is rejected."""
    shown = two_pending_questions()
    question_bank.publish_approved_question(shown[0]["id"])
    result = question_bank.reject_question_set(shown)
    assert result == {"rejected": [], "problem": "Question " + shown[0]["id"] + " is already 'approved'."}
    assert stored_rows()[shown[1]["id"]][3] == "pending_approval"


def test_the_existing_functions_behave_as_before(temp_bank: None) -> None:
    """propose_question and publish_approved_question (used by the teacher view's per-question button) are unchanged."""
    proposed = question_bank.propose_question("concept_ohms_law", "easy", OHMS_PROMPT, "3 A")
    assert proposed["status"] == "pending_teacher_approval"
    assert question_bank.publish_approved_question(proposed["question_id"]) is True
    assert stored_rows()[proposed["question_id"]][3] == "approved"
