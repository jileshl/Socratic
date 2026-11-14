"""Tests for the question-bank MCP server: the tool list, every flowchart box of propose(), and stdio.

Most tests talk to the server in-process with the official SDK's Client (the same "tools/list" and
"tools/call" messages an agent sends, without a subprocess). One test runs the server as a real
subprocess over stdio, written like the Lecture 7 hands-on client (stdio_client + ClientSession).
MCP clients are asynchronous, so asyncio.run is used inside ordinary test functions (no pytest plugin).

Every test that proposes a question uses the temp_bank fixture: the questions go into a temporary
database, so the real .index/question_bank.db never gets a row from these tests, and the concept list
is a fixed stand-in, so no test reads data/concept_graph.json.
"""

import asyncio
import sqlite3
import sys
import threading
import typing
from pathlib import Path
from typing import Any

import pytest
from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from socratic_tutor import config
from socratic_tutor.tools import question_bank
from socratic_tutor.tools import question_bank_server


# ---------------------------------------------------------------------------
# NCERT-style example questions used by many tests
# ---------------------------------------------------------------------------

# Ohm's law (NCERT Ch 11): I = V / R = 12 / 4 = 3 A.
OHMS_PROMPT: str = "A 12 V battery is connected across a 4 ohm resistor. What is the current?"
OHMS_KEY: str = "3 A"

# Mirror formula (NCERT Ch 9): u = -30 cm, f = -20 cm, so 1/v = 1/f - 1/u = -1/60 and v = -60 cm.
MIRROR_PROMPT: str = (
    "An object is placed 30 cm in front of a concave mirror of focal length 20 cm. Where is the image formed?"
)
MIRROR_KEY: str = "-60 cm"

# The Unicode minus sign, which looks like "-" but is a different character (common in text copied from a PDF).
UNICODE_MINUS: str = "−"


# ---------------------------------------------------------------------------
# Stand-ins and helpers
# ---------------------------------------------------------------------------


def two_known_concepts() -> list[str]:
    """Stand-in for load_concept_ids: two concept ids, so the tests never read data/concept_graph.json."""
    return ["concept_ohms_law", "concept_mirror_formula"]


def no_concepts() -> list[str]:
    """Stand-in for a concept graph that could not be loaded: load_concept_ids then returns an empty list."""
    return []


def locked_database(concept_id: str, difficulty: str, prompt: str, gold_answer: str) -> dict[str, str]:
    """Stand-in for question_bank.propose_question that fails the way SQLite does when the file is locked."""
    raise sqlite3.OperationalError("database is locked")


# A made-up file path with a user's name in it, the kind of text a real OSError message contains.
FAKE_PRIVATE_PATH: str = "C:\\Users\\someone\\x"


def unreadable_file(concept_id: str, difficulty: str, prompt: str, gold_answer: str) -> dict[str, str]:
    """Stand-in for question_bank.propose_question that fails with an error message holding a private path."""
    raise OSError("Cannot open " + FAKE_PRIVATE_PATH)


@pytest.fixture
def temp_bank(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the question bank at an empty temporary database and use the two stand-in concepts."""
    # question_bank reads DB_PATH each time it connects, so changing it here moves every read and write.
    # monkeypatch puts the real path back after the test.
    monkeypatch.setattr(question_bank, "DB_PATH", tmp_path / "question_bank.db")
    # Create the empty questions table in the temporary file, with Jilesh's own function.
    question_bank._init_db()
    # propose() calls load_concept_ids() by name, so replacing it here changes what [Q3] sees.
    monkeypatch.setattr(question_bank_server, "load_concept_ids", two_known_concepts)


def read_saved_rows() -> list[tuple[Any, ...]]:
    """Every row in the questions table, so a test can check what was (or wasn't) saved."""
    # question_bank.DB_PATH is the temporary file while the temp_bank fixture is active.
    connection = sqlite3.connect(question_bank.DB_PATH)
    # The columns in a fixed order, so row[0] is always the id and row[5] the status.
    query = "SELECT id, concept_id, difficulty, prompt, gold_answer, status FROM questions"
    # fetchall() reads every row at once, as a list of tuples.
    rows = connection.execute(query).fetchall()
    # Close the file, so Windows can delete the temporary folder later.
    connection.close()
    return rows


def set_status(question_id: str, status: str) -> None:
    """Change one saved question's status, as the teacher view would (for example to 'rejected')."""
    connection = sqlite3.connect(question_bank.DB_PATH)
    # The "?" placeholders pass the values as data, never as part of the SQL text.
    connection.execute("UPDATE questions SET status = ? WHERE id = ?", (status, question_id))
    # Without commit() the change would be thrown away when the connection closes.
    connection.commit()
    connection.close()


def ohms_law_arguments() -> dict[str, Any]:
    """The four tool arguments for the Ohm's law example; a test can change one of them before calling."""
    return {
        "concept_id": "concept_ohms_law",
        "difficulty": "easy",
        "prompt": OHMS_PROMPT,
        "gold_answer": OHMS_KEY,
    }


def list_tools() -> list[Any]:
    """Ask the server for its tools, the way an MCP client does at start-up."""

    async def ask() -> list[Any]:
        async with Client(question_bank_server.mcp) as client:
            listing = await client.list_tools()
            return listing.tools

    return asyncio.run(ask())


def call_tool(arguments: dict[str, Any]) -> Any:
    """Call propose_question through the client and return the whole result, so a test can check is_error too."""

    async def ask() -> Any:
        async with Client(question_bank_server.mcp) as client:
            return await client.call_tool("propose_question", arguments)

    return asyncio.run(ask())


def call(arguments: dict[str, Any]) -> dict[str, Any]:
    """Call propose_question through the client and return its result as a plain dict."""
    # structured_content is the dict the tool returned ({"ok": ..., ...}).
    return call_tool(arguments).structured_content


def propose_tool() -> Any:
    """The one tool in the listing (the tool-list tests below check there is exactly one)."""
    tools = list_tools()
    return tools[0]


# ---------------------------------------------------------------------------
# The tool list and its labels (decisions QB1, QB5; evidence: "a tool list with schemas", capstone guide p.3)
# ---------------------------------------------------------------------------


def test_the_server_lists_exactly_one_tool() -> None:
    """QB1: the server only proposes. Adding a publish tool (or any other tool) makes this test fail."""
    names: list[str] = []
    for tool in list_tools():
        names.append(tool.name)
    assert names == ["propose_question"]


def test_the_tool_is_marked_as_a_write_that_never_deletes() -> None:
    """QB5: it writes (not read-only), never deletes or changes a row, repeats add nothing, and stays local."""
    annotations = propose_tool().annotations
    assert annotations is not None
    # It adds a row, so it is not read-only (the export script lists it as "write").
    assert annotations.read_only_hint is False
    # It only adds rows; it never deletes or overwrites one.
    assert annotations.destructive_hint is False
    # The same call twice adds only one row, because [Q5] refuses the copy.
    assert annotations.idempotent_hint is True
    # It touches only the local database, nothing on the internet.
    assert annotations.open_world_hint is False


def test_difficulty_is_a_fixed_list_in_the_schema() -> None:
    """The schema only accepts easy, medium or hard (an "enum"), and DIFFICULTIES matches the Literal type."""
    schema = propose_tool().input_schema
    difficulty_words = schema["properties"]["difficulty"]["enum"]
    assert sorted(difficulty_words) == ["easy", "hard", "medium"]
    # The list propose() checks and the type the schema is built from must agree word for word.
    assert list(typing.get_args(question_bank_server.Difficulty)) == question_bank_server.DIFFICULTIES


def test_the_schema_needs_all_four_inputs() -> None:
    """None of the four inputs has a default, so a call that leaves one out is refused by the schema."""
    schema = propose_tool().input_schema
    assert sorted(schema["required"]) == ["concept_id", "difficulty", "gold_answer", "prompt"]


def test_the_description_says_students_cannot_see_a_draft() -> None:
    """The model reads the description, so it must say the question stays hidden until the teacher approves it."""
    tool = propose_tool()
    assert "students can't see the question until the teacher approves it" in tool.description
    # It also says there is no way around the teacher.
    assert "no publish tool" in tool.description


def test_the_description_states_the_same_limits_as_the_code() -> None:
    """The limits are written into the description by hand, so they must match MAX_PROMPT_LENGTH and
    MAX_GOLD_ANSWER_LENGTH; changing a limit without the description makes this test fail."""
    description = propose_tool().description
    assert "at most " + str(question_bank_server.MAX_PROMPT_LENGTH) + " characters" in description
    assert "at most " + str(question_bank_server.MAX_GOLD_ANSWER_LENGTH) + " characters" in description


def test_the_output_schema_lists_the_result_keys() -> None:
    """QB6: the output schema names every key a result can have, so the model knows what comes back."""
    properties = propose_tool().output_schema["properties"]
    for key in ["ok", "question_id", "status", "detail", "error"]:
        assert key in properties, key


def test_a_difficulty_outside_the_list_is_rejected_before_our_code(temp_bank: None) -> None:
    """Through MCP, "tough" fails the schema check: an error result (is_error), and nothing is saved."""
    arguments = ohms_law_arguments()
    arguments["difficulty"] = "tough"
    result = call_tool(arguments)
    assert result.is_error is True
    assert read_saved_rows() == []


# ---------------------------------------------------------------------------
# The happy path through the client: [Q1]-[Q6] all pass, then [R]
# ---------------------------------------------------------------------------


def test_happy_path_through_the_client_saves_one_pending_row(temp_bank: None) -> None:
    """A good Ohm's law question is saved once, as 'pending_approval', and the result says so."""
    result = call_tool(ohms_law_arguments())
    # A saved question is a normal result, not an MCP error.
    assert result.is_error is False
    content = result.structured_content
    assert content["ok"] is True
    # Jilesh's ids look like "Q_" plus 8 hex characters, for example "Q_1a2b3c4d".
    assert content["question_id"].startswith("Q_")
    assert len(content["question_id"]) == 10
    # QB6: the status is passed through unchanged from question_bank.propose_question.
    assert content["status"] == "pending_teacher_approval"
    # QB6: the detail tells the model the question is not live yet.
    assert content["detail"] == question_bank_server.SAVED_DETAIL

    # Exactly one row, holding what was proposed, waiting for the teacher.
    rows = read_saved_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == content["question_id"]
    assert row[1] == "concept_ohms_law"
    assert row[2] == "easy"
    assert row[3] == OHMS_PROMPT
    assert row[4] == OHMS_KEY
    assert row[5] == "pending_approval"


# ---------------------------------------------------------------------------
# [Q1] tidy the three text inputs
# ---------------------------------------------------------------------------


def test_spaces_around_the_inputs_are_removed_before_saving(temp_bank: None) -> None:
    """[Q1]: spaces and new lines at both ends are stripped; the stored row has the tidy text."""
    result = question_bank_server.propose(
        concept_id="  concept_ohms_law ",
        difficulty="easy",
        prompt="\n  " + OHMS_PROMPT + "  \n",
        gold_answer="  3 A ",
    )
    assert result["ok"] is True
    row = read_saved_rows()[0]
    assert row[1] == "concept_ohms_law"
    assert row[3] == OHMS_PROMPT
    assert row[4] == "3 A"


def test_tidy_text_keeps_the_inside_as_written() -> None:
    """[Q1]: only the ends are tidied; spaces inside the text stay, so the teacher sees what was written."""
    assert question_bank_server.tidy_text("  3 A ") == "3 A"
    assert question_bank_server.tidy_text(" 3  A ") == "3  A"


# ---------------------------------------------------------------------------
# [Q2] length and difficulty
# ---------------------------------------------------------------------------


def test_an_empty_prompt_is_refused(temp_bank: None) -> None:
    """[Q2]: a prompt of only spaces is empty after [Q1], so it is refused and nothing is saved."""
    result = question_bank_server.propose(
        concept_id="concept_ohms_law", difficulty="easy", prompt="   ", gold_answer=OHMS_KEY,
    )
    assert result["ok"] is False
    assert result["error"] == "prompt is empty."
    assert read_saved_rows() == []


def test_an_empty_gold_answer_is_refused(temp_bank: None) -> None:
    """[Q2]: a question without an answer key can't be graded, so it is refused and nothing is saved."""
    result = question_bank_server.propose(
        concept_id="concept_ohms_law", difficulty="easy", prompt=OHMS_PROMPT, gold_answer="",
    )
    assert result["ok"] is False
    assert result["error"] == "gold_answer is empty."
    assert read_saved_rows() == []


def test_a_prompt_at_the_limit_is_accepted_and_one_more_character_is_refused(temp_bank: None) -> None:
    """[Q2]: MAX_PROMPT_LENGTH characters is still fine; one more is refused, and the message names the limit."""
    limit = question_bank_server.MAX_PROMPT_LENGTH
    # Not a real question, just text of exactly the right length.
    at_limit = question_bank_server.propose(
        concept_id="concept_ohms_law", difficulty="easy", prompt="a" * limit, gold_answer=OHMS_KEY,
    )
    over_limit = question_bank_server.propose(
        concept_id="concept_ohms_law", difficulty="easy", prompt="b" * (limit + 1), gold_answer=OHMS_KEY,
    )
    assert at_limit["ok"] is True
    assert over_limit["ok"] is False
    # The message says which input, what the limit is, and how long the text was.
    assert over_limit["error"] == "prompt is longer than " + str(limit) + " characters (" + str(limit + 1) + ")."
    # Only the question at the limit was saved.
    assert len(read_saved_rows()) == 1


def test_an_overlong_concept_id_is_refused(temp_bank: None) -> None:
    """[Q2]: a concept_id over MAX_CONCEPT_ID_LENGTH is refused before the concept list is even checked."""
    long_concept_id = "concept_" + "x" * question_bank_server.MAX_CONCEPT_ID_LENGTH
    result = question_bank_server.propose(
        concept_id=long_concept_id, difficulty="easy", prompt=OHMS_PROMPT, gold_answer=OHMS_KEY,
    )
    assert result["ok"] is False
    assert "concept_id is longer than " + str(question_bank_server.MAX_CONCEPT_ID_LENGTH) in result["error"]
    assert read_saved_rows() == []


def test_an_overlong_gold_answer_is_refused(temp_bank: None) -> None:
    """[Q2]: an answer key over MAX_GOLD_ANSWER_LENGTH is refused, so a runaway model can't paste pages of text."""
    long_key = "3" * (question_bank_server.MAX_GOLD_ANSWER_LENGTH + 1)
    result = question_bank_server.propose(
        concept_id="concept_ohms_law", difficulty="easy", prompt=OHMS_PROMPT, gold_answer=long_key,
    )
    assert result["ok"] is False
    assert "gold_answer is longer than " + str(question_bank_server.MAX_GOLD_ANSWER_LENGTH) in result["error"]
    assert read_saved_rows() == []


def test_a_difficulty_outside_the_list_in_a_direct_python_call(temp_bank: None) -> None:
    """[Q2] without the schema in between: "tough" is refused with a message listing the three words."""
    result = question_bank_server.propose(
        concept_id="concept_ohms_law", difficulty="tough", prompt=OHMS_PROMPT, gold_answer=OHMS_KEY,
    )
    assert result["ok"] is False
    assert "easy, medium, hard" in result["error"]
    assert "'tough'" in result["error"]
    assert read_saved_rows() == []


def test_length_problem_messages() -> None:
    """[Q2] on its own: empty, too long (with the length), and fine (None)."""
    assert question_bank_server.length_problem("prompt", "", 10) == "prompt is empty."
    assert question_bank_server.length_problem("prompt", "abc", 2) == "prompt is longer than 2 characters (3)."
    # Exactly at the limit is allowed.
    assert question_bank_server.length_problem("prompt", "ab", 2) is None


# ---------------------------------------------------------------------------
# [Q3] the concept must be in the concept graph
# ---------------------------------------------------------------------------


def test_an_unknown_concept_is_refused_with_the_known_ids(temp_bank: None) -> None:
    """[Q3]: a concept that isn't in the graph is refused, and the message lists the ids that are."""
    result = question_bank_server.propose(
        concept_id="concept_photosynthesis", difficulty="easy", prompt=OHMS_PROMPT, gold_answer=OHMS_KEY,
    )
    assert result["ok"] is False
    assert "Unknown concept_id 'concept_photosynthesis'" in result["error"]
    # The model can pick a correct id from the message and call again.
    assert "concept_ohms_law, concept_mirror_formula" in result["error"]
    assert read_saved_rows() == []


def test_an_empty_concept_list_fails_closed(temp_bank: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """[Q3]: if the concept graph can't be loaded, nothing can be checked, so nothing is saved (fail closed)."""
    # Replace the fixture's stand-in with one that returns no concepts at all.
    monkeypatch.setattr(question_bank_server, "load_concept_ids", no_concepts)
    result = question_bank_server.propose(**ohms_law_arguments())
    assert result["ok"] is False
    assert "could not be loaded" in result["error"]
    assert read_saved_rows() == []


# ---------------------------------------------------------------------------
# [Q4a] "name = value", "value = name" and "name = arithmetic" keys are refused
# ---------------------------------------------------------------------------


def test_a_name_equals_value_key_is_refused_with_the_value_suggested(temp_bank: None) -> None:
    """[Q4a]: "I = 3 A" is refused, and the message suggests writing just "3 A"."""
    result = question_bank_server.propose(
        concept_id="concept_ohms_law", difficulty="easy", prompt=OHMS_PROMPT, gold_answer="I = 3 A",
    )
    assert result["ok"] is False
    assert "'3 A' instead of 'I = 3 A'" in result["error"]
    assert read_saved_rows() == []


def test_a_name_equals_negative_value_key_is_refused(temp_bank: None) -> None:
    """[Q4a]: "v = -60 cm" is refused too; the sign stays in the suggested value."""
    result = question_bank_server.propose(
        concept_id="concept_mirror_formula", difficulty="medium", prompt=MIRROR_PROMPT, gold_answer="v = -60 cm",
    )
    assert result["ok"] is False
    assert "'-60 cm' instead of 'v = -60 cm'" in result["error"]
    assert read_saved_rows() == []


def test_a_value_equals_name_key_is_refused_with_the_left_side_suggested(temp_bank: None) -> None:
    """[Q4a] the other way round: "3 A = I" is refused, the message says 'value = name' and suggests "3 A"."""
    result = question_bank_server.propose(
        concept_id="concept_ohms_law", difficulty="easy", prompt=OHMS_PROMPT, gold_answer="3 A = I",
    )
    assert result["ok"] is False
    assert "'value = name'" in result["error"]
    assert "'3 A' instead of '3 A = I'" in result["error"]
    assert read_saved_rows() == []


def test_a_negative_value_equals_name_key_is_refused(temp_bank: None) -> None:
    """[Q4a]: "-60 cm = v" is refused too, and the suggested value keeps its sign."""
    result = question_bank_server.propose(
        concept_id="concept_mirror_formula", difficulty="medium", prompt=MIRROR_PROMPT, gold_answer="-60 cm = v",
    )
    assert result["ok"] is False
    assert "'value = name'" in result["error"]
    assert "'-60 cm' instead of '-60 cm = v'" in result["error"]
    assert read_saved_rows() == []


def test_a_name_equals_arithmetic_key_is_refused_with_calculate_suggested(temp_bank: None) -> None:
    """[Q4a]: "f = 1 + 2" is a sum left unworked; the message says to work it out with math-tools' calculate.
    "f = 1/20" is readable as a fractional quantity, so it is refused as 'name = value'."""
    result = question_bank_server.propose(
        concept_id="concept_mirror_formula",
        difficulty="medium",
        prompt="A convex lens has a power of 20 D. What is its focal length in metres?",
        gold_answer="f = 1 + 2",
    )
    assert result["ok"] is False
    assert "'name = arithmetic'" in result["error"]
    # It names the arithmetic to work out, and the math-tools tool that does it.
    assert "'1 + 2'" in result["error"]
    assert "calculate" in result["error"]
    assert read_saved_rows() == []

    # Also verify fractional quantity format is refused as 'name = value'
    result_frac = question_bank_server.propose(
        concept_id="concept_mirror_formula",
        difficulty="medium",
        prompt="A convex lens has a power of 20 D. What is its focal length in metres?",
        gold_answer="f = 1/20",
    )
    assert result_frac["ok"] is False
    assert "'name = value'" in result_frac["error"]


def test_arithmetic_with_no_letters_is_refused_even_when_calculate_refuses_it(temp_bank: None) -> None:
    """[Q4a]: "x = 1/0" and "x = 2^1000" have no letter on the right, so they aren't formulas. calculate can't
    work them out either (dividing by zero, a power that is too big), yet they are still refused as arithmetic."""
    for key in ["x = 1/0", "x = 2^1000"]:
        result = question_bank_server.propose(
            concept_id="concept_ohms_law", difficulty="easy", prompt=OHMS_PROMPT, gold_answer=key,
        )
        assert result["ok"] is False, key
        assert "'name = arithmetic'" in result["error"], key
        assert "calculate" in result["error"], key
    assert read_saved_rows() == []


def test_arithmetic_followed_by_a_unit_is_accepted_a_documented_limit(temp_bank: None) -> None:
    """[Q4a]: "f = 1/20 m" has a unit 'm' with a fractional quantity '1/20 m', which is now read as a
    quantity by math_tools.read_quantity and cleanly refused as 'name = value'."""
    result = question_bank_server.propose(
        concept_id="concept_mirror_formula",
        difficulty="medium",
        prompt="A convex lens has a power of 20 D. What is its focal length?",
        gold_answer="f = 1/20 m",
    )
    # The server now refuses it as 'name = value' because '1/20 m' is parsed by read_quantity
    assert result["ok"] is False
    assert "'name = value'" in result["error"]
    assert read_saved_rows() == []


def test_has_a_letter_cases() -> None:
    """[Q4a] helper: a formula side needs at least one letter (a quantity); digits and symbols alone don't count."""
    assert question_bank_server.has_a_letter("V/I") is True
    assert question_bank_server.has_a_letter("1/R1 + 1/R2") is True
    # The unit letter counts as a letter: this is why "f = 1/20 m" isn't caught (see the test above).
    assert question_bank_server.has_a_letter("1/20 m") is True
    assert question_bank_server.has_a_letter("1/0") is False
    assert question_bank_server.has_a_letter("2^1000") is False
    assert question_bank_server.has_a_letter("") is False


# ---------------------------------------------------------------------------
# [Q4b] formula keys must be readable by check_equivalence
# ---------------------------------------------------------------------------


def test_formula_keys_are_accepted(temp_bank: None) -> None:
    """[Q4b]: "R = V/I", the mirror formula "1/f = 1/v + 1/u" and the parallel-resistor formula all have
    letters on both sides, so [Q4a] lets them through; the grader's equivalence check can read them, so all
    are saved."""
    # (concept_id, prompt, answer key): different prompts, so [Q5] doesn't refuse any as a copy.
    examples: list[tuple[str, str, str]] = [
        ("concept_ohms_law", "Write Ohm's law as a formula for the resistance R.", "R = V/I"),
        ("concept_mirror_formula", "Write the mirror formula.", "1/f = 1/v + 1/u"),
        ("concept_ohms_law", "Write the formula for two resistors R1 and R2 in parallel.", "1/R = 1/R1 + 1/R2"),
    ]
    for concept_id, prompt, gold_answer in examples:
        result = question_bank_server.propose(
            concept_id=concept_id, difficulty="easy", prompt=prompt, gold_answer=gold_answer,
        )
        assert result["ok"] is True, gold_answer + ": " + str(result.get("error"))
    # The keys are stored exactly as written.
    rows = read_saved_rows()
    assert rows[0][4] == "R = V/I"
    assert rows[1][4] == "1/f = 1/v + 1/u"
    assert rows[2][4] == "1/R = 1/R1 + 1/R2"


def test_an_unreadable_formula_key_is_refused(temp_bank: None) -> None:
    """[Q4b]: "R = (V/I" has a bracket that is never closed, so the grader couldn't read it; it is refused."""
    result = question_bank_server.propose(
        concept_id="concept_ohms_law",
        difficulty="easy",
        prompt="Write Ohm's law as a formula for the resistance R.",
        gold_answer="R = (V/I",
    )
    assert result["ok"] is False
    assert "looks like a formula, but it can't be read" in result["error"]
    assert read_saved_rows() == []


# ---------------------------------------------------------------------------
# [Q4c] keys that start like a number must be readable as a number with a known unit
# ---------------------------------------------------------------------------


def test_number_keys_are_accepted(temp_bank: None) -> None:
    """[Q4c]: a value with its unit, a bare number, and "x 10^8" notation are all readable, so all are saved."""
    # (concept_id, prompt, answer key): each prompt is different, so [Q5] doesn't refuse any as a copy.
    examples: list[tuple[str, str, str]] = [
        ("concept_mirror_formula", MIRROR_PROMPT, "-60 cm"),
        ("concept_ohms_law", "A 5 ohm resistor carries 0.5 A. What is the potential difference in volts?", "2.5"),
        ("concept_mirror_formula", "What is the speed of light in vacuum?", "3 x 10^8 m/s"),
    ]
    for concept_id, prompt, gold_answer in examples:
        result = question_bank_server.propose(
            concept_id=concept_id, difficulty="easy", prompt=prompt, gold_answer=gold_answer,
        )
        assert result["ok"] is True, gold_answer + ": " + str(result.get("error"))
    assert len(read_saved_rows()) == 3


def test_a_unicode_minus_key_is_accepted_and_stored_as_written(temp_bank: None) -> None:
    """[Q4c]: "−60 cm" with the Unicode minus (as copied from a PDF) is readable, and is saved as written."""
    key = UNICODE_MINUS + "60 cm"
    result = question_bank_server.propose(
        concept_id="concept_mirror_formula", difficulty="medium", prompt=MIRROR_PROMPT, gold_answer=key,
    )
    assert result["ok"] is True
    # [Q1] only strips the ends, so the Unicode minus is kept; the grader's read_quantity understands it.
    assert read_saved_rows()[0][4] == key


def test_an_unknown_unit_key_is_refused(temp_bank: None) -> None:
    """[Q4c]: "-60 parsecs" starts with a number, but parsecs is not a unit the grader knows, so it is refused."""
    result = question_bank_server.propose(
        concept_id="concept_mirror_formula", difficulty="medium", prompt=MIRROR_PROMPT, gold_answer="-60 parsecs",
    )
    assert result["ok"] is False
    assert "its number and unit can't be read" in result["error"]
    # The message shows the model how to write it.
    assert "'-60 cm'" in result["error"]
    assert read_saved_rows() == []


def test_a_key_of_only_punctuation_is_refused(temp_bank: None) -> None:
    """[Q4c]: ".", ";" and "..." have no number or words, so they are refused with a message (they used to
    crash with IndexError, found by these tests) and nothing is saved."""
    for key in [".", ";", "..."]:
        result = question_bank_server.propose(
            concept_id="concept_ohms_law", difficulty="easy", prompt=OHMS_PROMPT, gold_answer=key,
        )
        assert result["ok"] is False, key
        assert result["error"] == "The answer key has no number or words in it, only punctuation.", key
    assert read_saved_rows() == []


# ---------------------------------------------------------------------------
# [Q4d] anything else is a text answer, read by the teacher
# ---------------------------------------------------------------------------


def test_a_text_answer_key_is_accepted(temp_bank: None) -> None:
    """[Q4d]: "real and inverted" doesn't start like a number and has no "=", so it is saved for the teacher."""
    result = question_bank_server.propose(
        concept_id="concept_mirror_formula",
        difficulty="easy",
        prompt="An object is placed beyond C in front of a concave mirror. What is the nature of the image?",
        gold_answer="real and inverted",
    )
    assert result["ok"] is True
    assert read_saved_rows()[0][4] == "real and inverted"


def test_answer_key_problem_cases() -> None:
    """[Q4] on its own: the accepted keys give None, the refused keys give a message."""
    accepted = [
        "3 A", "-60 cm", "2.5", "+2.5 D", "3 x 10^8 m/s", UNICODE_MINUS + "60 cm",
        "R = V/I", "1/f = 1/v + 1/u", "1/R = 1/R1 + 1/R2", "f = R/2", "2u = v", "y = 2x",
        "real and inverted",
    ]
    for key in accepted:
        assert question_bank_server.answer_key_problem(key) is None, key
    refused = [
        "I = 3 A", "v = -60 cm", "3 A = I", "-60 cm = v", "f = 1/20", "x = 1/0", "x = 2^1000",
        "R = (V/I", "R =", "-60 parsecs", "2 metres and a bit", ".",
    ]
    for key in refused:
        assert question_bank_server.answer_key_problem(key) is not None, key


# ---------------------------------------------------------------------------
# [Q5] not a duplicate (decision QB9): same concept and same text, case and spaces ignored, any status
# ---------------------------------------------------------------------------


def test_the_same_question_twice_is_refused_the_second_time(temp_bank: None) -> None:
    """[Q5]: the second identical call saves nothing, and names the first question's id and status."""
    first = question_bank_server.propose(**ohms_law_arguments())
    second = question_bank_server.propose(**ohms_law_arguments())
    assert first["ok"] is True
    assert second["ok"] is False
    # The model (and the teacher) can see which question it copies.
    assert first["question_id"] in second["error"]
    assert "status: pending_approval" in second["error"]
    assert len(read_saved_rows()) == 1


def test_a_copy_with_different_capitals_and_spaces_is_refused(temp_bank: None) -> None:
    """[Q5]: capitals and extra spaces don't make a new question, so the copy is refused."""
    first = question_bank_server.propose(**ohms_law_arguments())
    copy = question_bank_server.propose(
        concept_id="concept_ohms_law",
        difficulty="easy",
        prompt="a 12 V BATTERY is connected   across a 4 ohm resistor.\n What is the CURRENT?",
        gold_answer=OHMS_KEY,
    )
    assert copy["ok"] is False
    assert first["question_id"] in copy["error"]
    assert len(read_saved_rows()) == 1


def test_the_same_text_under_another_concept_is_accepted(temp_bank: None) -> None:
    """[Q5]: a duplicate needs the same concept as well as the same text, so another concept is a new question."""
    first = question_bank_server.propose(**ohms_law_arguments())
    other_concept = question_bank_server.propose(
        concept_id="concept_mirror_formula", difficulty="easy", prompt=OHMS_PROMPT, gold_answer=OHMS_KEY,
    )
    assert first["ok"] is True
    assert other_concept["ok"] is True
    assert len(read_saved_rows()) == 2


def test_a_rejected_question_is_not_proposed_again(temp_bank: None) -> None:
    """[Q5], any status: once the teacher rejects a question, the same question can't be sent back again."""
    first = question_bank_server.propose(**ohms_law_arguments())
    # The teacher rejects it in the teacher view.
    set_status(first["question_id"], "rejected")
    again = question_bank_server.propose(**ohms_law_arguments())
    assert again["ok"] is False
    assert first["question_id"] in again["error"]
    assert "rejected" in again["error"]
    assert len(read_saved_rows()) == 1


def test_normalise_text_cases() -> None:
    """[Q5] compares texts in lower case with single spaces, whatever spaces, tabs or new lines were typed."""
    assert question_bank_server.normalise_text("  State the LAWS  of reflection.") == "state the laws of reflection."
    assert question_bank_server.normalise_text("What is\tthe\ncurrent?") == "what is the current?"
    # Punctuation is kept: "current?" and "current" are different texts.
    assert question_bank_server.normalise_text("Current?") != question_bank_server.normalise_text("Current")
    assert question_bank_server.normalise_text("") == ""


# ---------------------------------------------------------------------------
# [Q5] + [Q6] under SAVE_LOCK: identical calls arriving at the same moment
# ---------------------------------------------------------------------------

# How many identical calls the race test sends at once (the review found 8 calls saving 4 rows without the lock).
RACE_THREADS: int = 8


def propose_when_all_are_ready(start_together: threading.Barrier, results: list[dict[str, Any]]) -> None:
    """One of the simultaneous callers: wait until every caller is ready, then propose the Ohm's law question."""
    # The barrier holds each thread here until all of them have arrived, so the calls really overlap.
    # The timeout stops the test from hanging for ever if a thread never arrives.
    start_together.wait(timeout=10)
    result = question_bank_server.run_and_log("concept_ohms_law", "easy", OHMS_PROMPT, OHMS_KEY)
    # list.append is safe to call from several threads at once.
    results.append(result)


def test_identical_calls_at_the_same_moment_save_only_one_row(temp_bank: None) -> None:
    """SAVE_LOCK: 8 identical calls in 8 threads at once save exactly one row; the other 7 are refused as copies.

    Without the lock, several calls pass [Q5] before any of them has saved: a check run with the lock
    removed saved 5 rows out of 8, so this test would catch a missing lock.
    """
    # A Barrier for 8 threads: none of them goes past wait() until all 8 have called it.
    start_together = threading.Barrier(RACE_THREADS)
    # Each thread adds its result here.
    results: list[dict[str, Any]] = []
    # Create the threads first; each one will run propose_when_all_are_ready(start_together, results).
    threads: list[threading.Thread] = []
    for thread_number in range(RACE_THREADS):
        threads.append(threading.Thread(target=propose_when_all_are_ready, args=(start_together, results)))
    for thread in threads:
        thread.start()
    # join() waits for each thread to finish, so every result is in before the checks.
    for thread in threads:
        thread.join(timeout=30)

    # Every call came back with a result (none crashed).
    assert len(results) == RACE_THREADS
    # Exactly one call saved the question...
    saved_count = 0
    for result in results:
        if result["ok"] is True:
            saved_count = saved_count + 1
    assert saved_count == 1
    # ...and the bank holds exactly one row.
    assert len(read_saved_rows()) == 1


# ---------------------------------------------------------------------------
# [Q6] save, then [R] the result
# ---------------------------------------------------------------------------


def test_a_saved_result_has_exactly_the_four_success_keys(temp_bank: None) -> None:
    """[R]: a success has ok, question_id, status and detail (no error), and the id is the saved row's id."""
    result = question_bank_server.propose(**ohms_law_arguments())
    assert sorted(result) == ["detail", "ok", "question_id", "status"]
    assert result["question_id"] == read_saved_rows()[0][0]
    # The stored status is 'pending_approval'; the result passes Jilesh's 'pending_teacher_approval' through.
    assert result["status"] == "pending_teacher_approval"


def test_a_refusal_has_only_ok_and_error(temp_bank: None) -> None:
    """[E]: a refusal has ok False and an error message, and nothing that looks like a saved question."""
    result = question_bank_server.propose(
        concept_id="concept_ohms_law", difficulty="easy", prompt=OHMS_PROMPT, gold_answer="I = 3 A",
    )
    assert sorted(result) == ["error", "ok"]
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# [W] unexpected problems become error results, never crashes
# ---------------------------------------------------------------------------


def test_a_locked_database_becomes_an_error_result(temp_bank: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """[W]: if saving raises (here "database is locked"), run_and_log returns ok False with the error's type."""
    # propose() calls question_bank.propose_question by name, so this replaces the save step [Q6].
    monkeypatch.setattr(question_bank, "propose_question", locked_database)
    result = question_bank_server.run_and_log("concept_ohms_law", "easy", OHMS_PROMPT, OHMS_KEY)
    assert result["ok"] is False
    assert result["error"] == "Unexpected problem in propose_question (OperationalError), so nothing was saved."
    # Only the type goes back to the model, not the exception's own text.
    assert "database is locked" not in result["error"]


def test_an_unexpected_error_does_not_show_its_own_text(temp_bank: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """[W]: an error's own text can hold a file path with the user's name in it, so the model gets only the
    error's type (OSError), never the path, and can't repeat it to a student."""
    monkeypatch.setattr(question_bank, "propose_question", unreadable_file)
    result = question_bank_server.run_and_log("concept_ohms_law", "easy", OHMS_PROMPT, OHMS_KEY)
    assert result["ok"] is False
    assert "(OSError)" in result["error"]
    assert FAKE_PRIVATE_PATH not in result["error"]
    assert "someone" not in result["error"]


def test_a_locked_database_through_the_client_is_a_normal_result(
    temp_bank: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[W] through MCP: the agent gets a normal result (is_error False) saying what went wrong, not a crash."""
    monkeypatch.setattr(question_bank, "propose_question", locked_database)
    result = call_tool(ohms_law_arguments())
    assert result.is_error is False
    assert result.structured_content["ok"] is False
    assert "Unexpected problem" in result.structured_content["error"]
    assert "(OperationalError)" in result.structured_content["error"]


# ---------------------------------------------------------------------------
# [L] one log line per call: the id, never the question text
# ---------------------------------------------------------------------------


def test_log_line_for_a_success() -> None:
    """[L]: a saved question is logged by its id and the time, nothing else."""
    result = {"ok": True, "question_id": "Q_1a2b3c4d", "status": "pending_teacher_approval", "detail": "Saved."}
    line = question_bank_server.log_line(result, 2.34)
    assert line == "tool=propose_question ok=True question_id=Q_1a2b3c4d ms=2.3"


def test_log_line_for_a_saved_question_has_the_id_but_not_the_text(temp_bank: None) -> None:
    """[L] end to end: the log line of a real save has the new id, but not the question or its answer key."""
    result = question_bank_server.propose(**ohms_law_arguments())
    line = question_bank_server.log_line(result, 1.0)
    assert result["question_id"] in line
    assert OHMS_PROMPT not in line
    assert "battery" not in line
    assert OHMS_KEY not in line


def test_log_line_for_an_error_is_cut_to_80_characters() -> None:
    """[L]: a refused call logs its error, cut to at most 80 characters so a long message can't flood the log."""
    result = {"ok": False, "error": "x" * 200}
    line = question_bank_server.log_line(result, 0.5)
    assert line.startswith('tool=propose_question ok=False error="')
    # Take out the text between error=" and the closing quote before ms=.
    start = line.index('error="') + len('error="')
    end = line.index('" ms=')
    logged_error = line[start:end]
    assert logged_error == "x" * 80


def test_log_line_never_contains_the_question_text(temp_bank: None) -> None:
    """[L]: whether the call saves or is refused (bad concept, bad key, a copy), the question text is never logged.

    A refused call may quote part of the answer key (the setter's own value), so only the prompt is checked.
    """
    results: list[dict[str, Any]] = []
    # A save.
    results.append(question_bank_server.propose(**ohms_law_arguments()))
    # Refused at [Q3]: unknown concept.
    results.append(question_bank_server.propose(
        concept_id="concept_photosynthesis", difficulty="easy", prompt=OHMS_PROMPT, gold_answer=OHMS_KEY,
    ))
    # Refused at [Q4a]: "name = value".
    results.append(question_bank_server.propose(
        concept_id="concept_ohms_law", difficulty="easy", prompt=OHMS_PROMPT, gold_answer="I = 3 A",
    ))
    # Refused at [Q5]: the same question again.
    results.append(question_bank_server.propose(**ohms_law_arguments()))
    for result in results:
        line = question_bank_server.log_line(result, 1.0)
        assert OHMS_PROMPT not in line, line
        # A distinctive word of the prompt, in case only part of it slipped in.
        assert "battery" not in line, line


def test_log_line_replaces_line_breaks_in_an_error() -> None:
    """[L]: a line break in an error becomes a space, so an input can't write a second, fake log line."""
    # The second half would look like a real log line saying a question was saved.
    fake_line = "question-bank tool=propose_question ok=True'"
    fake_newline = {"ok": False, "error": "Unknown concept_id 'x\n" + fake_line}
    # Windows ends a line with "\r\n", so the carriage return "\r" must go too.
    fake_carriage_return = {"ok": False, "error": "Unknown concept_id 'x\r\n" + fake_line}
    for result in [fake_newline, fake_carriage_return]:
        line = question_bank_server.log_line(result, 1.0)
        assert "\n" not in line
        assert "\r" not in line
        # It's still one honest line: the call was refused.
        assert line.startswith("tool=propose_question ok=False")


def test_log_line_keeps_a_quote_and_control_codes_inside_the_error_field() -> None:
    """[L]: a " in the error can't close the error="..." field early and add a fake question_id field, and the
    ESC code "\\x1b[1A" (move the cursor up a line, which could hide the line above) doesn't reach the log."""
    result = {"ok": False, "error": "Unknown concept_id 'x\" ok=True question_id=Q_fake\x1b[1A'"}
    line = question_bank_server.log_line(result, 1.0)
    # Exactly two " characters: the ones log_line puts around the error field, so the field isn't closed early.
    assert line.count('"') == 2
    # The closing " is the one just before the time, at the end of the line.
    assert line.endswith('" ms=1.0')
    assert "\x1b" not in line
    assert "\n" not in line
    assert "\r" not in line


def test_safe_for_log_cases() -> None:
    """[L] helper: every unprintable character becomes a space and " becomes '; printable text stays as it is."""
    # (text in, text out)
    examples: list[tuple[str, str]] = [
        ("a\nb", "a b"),               # new line
        ("a\r\nb", "a  b"),            # Windows line end: two characters, so two spaces
        ("a\tb", "a b"),               # tab
        ("\x1b[1A", " [1A"),           # ESC: the start of a terminal control code
        ("x\x85y", "x y"),             # "next line", a line break in some programs
        ("x\x0by", "x y"),             # vertical tab
        ("x\u2028y", "x y"),           # Unicode line separator
        ('say "hi"', "say 'hi'"),      # a double quote becomes a single quote
        ("Unknown concept_id 'concept_x'.", "Unknown concept_id 'concept_x'."),  # ordinary text is unchanged
        (UNICODE_MINUS + "60 cm", UNICODE_MINUS + "60 cm"),                      # printable Unicode is kept
    ]
    for text, expected in examples:
        assert question_bank_server.safe_for_log(text) == expected, repr(text)


def test_a_concept_id_with_a_line_break_logs_one_line(temp_bank: None) -> None:
    """[L] end to end: the unknown concept_id is quoted in the error, but its line break doesn't reach the log."""
    result = question_bank_server.propose(
        concept_id="x\nquestion-bank tool=propose_question ok=True",
        difficulty="easy",
        prompt=OHMS_PROMPT,
        gold_answer=OHMS_KEY,
    )
    # [Q3] refuses it and quotes it, line break and all, in the error message...
    assert result["ok"] is False
    assert "\n" in result["error"]
    # ...but the log line has no line break.
    line = question_bank_server.log_line(result, 1.0)
    assert "\n" not in line
    assert read_saved_rows() == []


# ---------------------------------------------------------------------------
# End to end over stdio, written like the Lecture 7 hands-on client (Lesson 7)
# ---------------------------------------------------------------------------


def test_server_over_stdio_lists_only_propose_question() -> None:
    """Launch the server as a real subprocess, then initialize -> discover. It only lists tools, because a
    call here would write to the real question bank (the subprocess can't see the temp_bank fixture)."""

    async def mcp_demo() -> list[str]:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "socratic_tutor.tools.question_bank_server"],
            # Start in the repository folder (taken from config.py) so "-m socratic_tutor..." can be found.
            cwd=str(config.BASE_DIR),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()                                        # 1. handshake
                tools = await session.list_tools()                                # 2. discover
                names: list[str] = []
                for tool in tools.tools:
                    names.append(tool.name)
                return names

    names = asyncio.run(mcp_demo())
    assert names == ["propose_question"]
