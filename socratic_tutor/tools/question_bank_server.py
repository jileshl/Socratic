"""question-bank MCP server: one WRITE tool, propose_question, that saves a draft question for the teacher.

Built with the official MCP Python SDK (MCPServer), the same way as math_tools_server.py and the
Lecture 7 hands-on: one @mcp.tool(), mcp.run(transport="stdio").

The capstone guide asks for "question-bank (propose; publish behind the gate)" and "allow only the
question setter to propose items to the shared bank" (capstone guide p.12). So this server has exactly
one tool, and it only PROPOSES (decision QB1):
    propose_question    - save a new question with status 'pending_approval'; students can't see it
There is deliberately NO publish tool. Publishing (question_bank.publish_approved_question) happens only
after the teacher approves the exact question in the teacher view; no agent can reach it.

Before saving, the tool checks the inputs in code (decisions QB2-QB4, QB9):
    [Q1] tidy -> [Q2] length and difficulty -> [Q3] known concept -> [Q4] readable answer key
    -> [Q5] not a duplicate -> [Q6] save with question_bank.propose_question (Jilesh's, unchanged, QB7)
Errors come back as results ({"ok": False, "error": ...}), never as crashes (capstone guide p.3).

Run it (stdio transport, for development):
    python -m socratic_tutor.tools.question_bank_server
"""

import logging
import sqlite3
import sys
import threading
import time
from typing import Any, Literal, TypedDict

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from socratic_tutor.concept_graph import ConceptGraph
from socratic_tutor.tools import math_tools
from socratic_tutor.tools import question_bank


# ---------------------------------------------------------------------------
# Limits and allowed values (decisions QB2, QB3).
# The limits stop a runaway model from flooding the teacher's queue with pages of text [own choice].
# ---------------------------------------------------------------------------
MAX_CONCEPT_ID_LENGTH: int = 60
MAX_PROMPT_LENGTH: int = 1000
MAX_GOLD_ANSWER_LENGTH: int = 200

# The three difficulty words. Literal makes the MCP schema accept only these (an "enum"), and
# DIFFICULTIES lets propose() check them too when it is called directly from Python.
Difficulty = Literal["easy", "medium", "hard"]
DIFFICULTIES: list[str] = ["easy", "medium", "hard"]

# The detail every successful result carries, so the model never tells a student the question is live (QB6).
SAVED_DETAIL: str = (
    "Saved for teacher approval. Students can't see this question until the teacher approves it."
)

# The SDK runs each tool call in its own worker thread, so two identical calls can arrive at the same moment.
# Without this lock both could pass the duplicate check [Q5] before either has saved [Q6], and the bank would
# get two copies (8 simultaneous calls saved 4 rows without it). The lock lets only one call at a time do
# "check for a copy, then save". It works within one server process. Two separate server processes could
# still race: stopping that would need the check and the insert in one database transaction (or a lock file),
# inside Jilesh's question_bank.py, which stays unchanged (QB7).
SAVE_LOCK: threading.Lock = threading.Lock()


# ---------------------------------------------------------------------------
# The result shape the tool returns, so the server can publish an output schema (decision QB6).
# total=False: a success has ok/question_id/status/detail; an error has ok/error.
# ---------------------------------------------------------------------------
class ProposeResult(TypedDict, total=False):
    ok: bool
    question_id: str
    status: str
    detail: str
    error: str


# ---------------------------------------------------------------------------
# Logging: one line per tool call, to stderr (as in math_tools_server.py, decision S8).
# With the stdio transport, stdout is the message channel, so nothing may be printed there.
# The question text is never logged. A refused call logs the start of its error message (at most 80
# characters, line breaks removed). That can quote part of the answer key: the setter's own value
# from math-tools, not anything a student typed.
# ---------------------------------------------------------------------------
logger: logging.Logger = logging.getLogger("question-bank")
if not logger.handlers:
    # Send the log lines to stderr, with a timestamp and the server's name.
    stderr_handler: logging.StreamHandler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter("%(asctime)s question-bank %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(stderr_handler)
    logger.setLevel(logging.INFO)
    # Keep these lines out of other loggers (for example the app's root logger).
    logger.propagate = False


def safe_for_log(text: str) -> str:
    """Make text safe to put inside one log line: every unprintable character becomes a space, " becomes '.

    An input like 'x\\ntool=propose_question ok=True' could otherwise write a second, fake log line, and a
    " could close the error="..." field early and add a fake field after it. Terminal control codes
    (ESC sequences that move the cursor) are unprintable too, so they become spaces as well.
    """
    safe = ""
    for character in text:
        if not character.isprintable():
            # Line breaks, tabs, ESC and other control characters.
            safe = safe + " "
        elif character == '"':
            safe = safe + "'"
        else:
            safe = safe + character
    return safe


def log_line(result: dict[str, Any], milliseconds: float) -> str:
    """Build the one-line log for a call: the tool, ok, the new question id (if any) and the time. No question text."""
    line = "tool=propose_question ok=" + str(result.get("ok"))
    # A saved question is identified by its id, never by its text.
    if result.get("ok") is True:
        line = line + " question_id=" + str(result.get("question_id"))
    # A refused call says why, cut short so a long message doesn't flood the log.
    if result.get("ok") is False:
        short_error = str(result.get("error", ""))[:80]
        # The error can quote the inputs, so make it safe first: it must stay inside this one line and this one field.
        short_error = safe_for_log(short_error)
        line = line + ' error="' + short_error + '"'
    line = line + " ms=" + str(round(milliseconds, 1))
    return line


def run_and_log(concept_id: str, difficulty: str, prompt: str, gold_answer: str) -> dict[str, Any]:
    """Run propose(), turn any unexpected exception into an error result, and log one line."""
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [W] start the clock; run propose(...)
    #          |  any unexpected exception (e.g. a locked database)?
    #          |  yes -> {ok: False, error: "Unexpected problem ... (ErrorType)"}
    #          v
    #   [L] one log line to stderr (log_line), then return the result

    # [W] start the clock, so the log line can say how long the call took.
    started = time.perf_counter()
    try:
        result = propose(concept_id, difficulty, prompt, gold_answer)
    except Exception as error:  # [W] any unexpected problem becomes a structured error, never a crash
        # Only the error's TYPE goes back to the model: its message can contain file paths (with the user's
        # name) that the model might repeat to a student. The log line gets only the type too.
        result = math_tools.make_error(
            "Unexpected problem in propose_question (" + type(error).__name__ + "), so nothing was saved."
        )
    # [L] how long the call took, in milliseconds, then one log line.
    milliseconds = (time.perf_counter() - started) * 1000
    logger.info(log_line(result, milliseconds))
    return result


# ---------------------------------------------------------------------------
# One helper per flowchart box, so each check can be read and tested on its own.
# ---------------------------------------------------------------------------


def tidy_text(text: str) -> str:
    """[Q1] Remove spaces at both ends, e.g. '  3 A ' -> '3 A'. The text inside is kept as written."""
    return text.strip()


def length_problem(input_name: str, text: str, limit: int) -> str | None:
    """[Q2] Say what's wrong if the text is empty or longer than the limit; None if its length is fine."""
    # An empty input can't be a question, a concept or an answer key.
    if text == "":
        return input_name + " is empty."
    # A text over the limit is refused, and the message says how long it was.
    if len(text) > limit:
        return input_name + " is longer than " + str(limit) + " characters (" + str(len(text)) + ")."
    return None


def load_concept_ids() -> list[str]:
    """[Q3] The concept ids in the concept graph (data/concept_graph.json), e.g. 'concept_ohms_law'.

    Returns an empty list if the graph can't be loaded; propose() then refuses (fail closed).
    """
    # ConceptGraph reads the JSON file; .concepts is a dict keyed by concept id. A missing file gives {}.
    graph = ConceptGraph()
    # Copy the ids into a plain list: propose() checks "is it in the list?" and prints the list in its message.
    concept_ids: list[str] = []
    for concept_id in graph.concepts:
        concept_ids.append(concept_id)
    return concept_ids


def has_a_letter(text: str) -> bool:
    """True if the text contains at least one letter. A formula side needs a letter (a quantity such as V or R)."""
    for character in text:
        if character.isalpha():
            return True
    return False


def answer_key_problem(gold_answer: str) -> str | None:
    """[Q4] Say what's wrong if the grader's code couldn't read this answer key; None if it can (decision QB4).

    Accepted: a number with its unit ('-60 cm', '3 A'), a bare number ('2.5'), a formula ('R = V/I'),
    or a short text answer ('real and inverted').
    Refused: 'name = value' written either way round ('I = 3 A', '3 A = I'), 'name = arithmetic' ('f = 1/20'),
    a formula the equivalence check can't read, a number with an unknown unit, and punctuation only ('.').
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   contains "="?
    #      | yes                                        | no
    #      v                                            v
    #   [Q4a] a value on either side, or            [Q4c] only punctuation?  yes -> refuse
    #         plain arithmetic on the right?               | no
    #      | yes -> refuse: "write only the value"         v
    #      | no                                     starts with a digit, +, - or . ?
    #      v                                           | yes -> read_quantity must read it
    #   [Q4b] a formula: check_equivalence             | no
    #         must be able to read it                  v
    #                                               [Q4d] a text answer: accepted

    if "=" in gold_answer:
        # Split at the first "=" only: "I = 3 A" -> left "I", right "3 A".
        parts = gold_answer.split("=", 1)
        left_side = parts[0].strip()
        right_side = parts[1].strip()

        # [Q4a] "name = value". The grader compares VALUES, so the key must be just the value.
        # Four ways to spot it:
        #   the right side is a quantity:       "I = 3 A", "v = -60 cm"
        #   the left side is a quantity:        "3 A = I", "-60 cm = v"
        #   the right side is plain arithmetic: "f = 1/20"
        #   the right side has no letters:      "x = 1/0", "x = 2^1000" (arithmetic that calculate refuses)
        # Not caught: arithmetic followed by a unit ("f = 1/20 m"). It passes as a formula; the teacher reviews it.
        if math_tools.read_quantity(right_side)["ok"]:
            return (
                "Write only the value, not 'name = value': for example '" + right_side
                + "' instead of '" + gold_answer + "'."
            )
        if math_tools.read_quantity(left_side)["ok"]:
            return (
                "Write only the value, not 'value = name': for example '" + left_side
                + "' instead of '" + gold_answer + "'."
            )
        if math_tools.calculate(right_side)["ok"] or not has_a_letter(right_side):
            return (
                "Write only the value, not 'name = arithmetic': work out '" + right_side
                + "' with math-tools (calculate) and write the result with its unit."
            )

        # [Q4b] Otherwise it's a formula such as "R = V/I". The grader's equivalence check must be
        # able to read it, so read it once against itself.
        formula_reading = math_tools.check_equivalence(gold_answer, gold_answer)
        if not formula_reading["ok"]:
            return "The answer key looks like a formula, but it can't be read: " + formula_reading["error"]
        return None

    # [Q4c] tidy_answer_text turns the Unicode minus into "-", moves "Rs" or "₹" behind the number, and drops
    # a full stop at the end. A key of only punctuation (".", ";") becomes empty, so refuse it here, before
    # looking at its first character, which an empty text doesn't have (it would crash with IndexError).
    tidy_key = math_tools.tidy_answer_text(gold_answer)
    if tidy_key == "":
        return "The answer key has no number or words in it, only punctuation."
    # [Q4c] A key that starts like a number must be readable as a number with a known unit.
    first_character = tidy_key[0]
    if first_character.isdigit() or first_character in "+-.":
        reading = math_tools.read_quantity(gold_answer)
        if not reading["ok"]:
            # The grader couldn't read it either, so say what's wrong and show the form that works.
            return (
                "The answer key starts with a number, but its number and unit can't be read: "
                + reading["error"] + " Write it like '-60 cm' or '3 A'."
            )
        return None

    # [Q4d] Anything else is a text answer, such as "real and inverted". The teacher reads it.
    return None


def normalise_text(text: str) -> str:
    """Lower case with single spaces, for comparing questions: '  State the LAWS  of reflection.' -> 'state the laws of reflection.'"""
    # split() breaks the text at any run of spaces, tabs or new lines; joining with " " leaves single spaces.
    words = text.split()
    return " ".join(words).lower()


def find_duplicate(concept_id: str, prompt: str) -> dict[str, str] | None:
    """[Q5] Find a question with the same concept and the same text (case and spaces ignored), in any status.

    Returns {"id": ..., "status": ...} for the first match, or None (decision QB9).
    Reads the questions table directly; question_bank.py itself stays unchanged (QB7).
    """
    # The proposed text, in the form used for comparing.
    wanted = normalise_text(prompt)
    # Open the database file. question_bank.DB_PATH is read here, at call time, so tests can point it at a
    # temporary file.
    connection = sqlite3.connect(question_bank.DB_PATH)
    try:
        # The "?" placeholder passes concept_id as data, never as part of the SQL text.
        rows = connection.execute(
            "SELECT id, prompt, status FROM questions WHERE concept_id = ?",
            (concept_id,),
        ).fetchall()
    finally:
        # Always close the file, even if the query fails. ("with sqlite3.connect(...)" only commits; it doesn't close.)
        connection.close()
    # The texts are compared here in Python, not in SQL: SQL can't easily ignore extra spaces and tabs, and one
    # concept has only a handful of questions, so reading them all is cheap.
    for row in rows:
        row_id = row[0]
        row_prompt = row[1]
        row_status = row[2]
        if normalise_text(row_prompt) == wanted:
            return {"id": row_id, "status": row_status}
    return None


# ---------------------------------------------------------------------------
# The whole check-then-save, as one plain function (the tests call it directly too).
# ---------------------------------------------------------------------------


def propose(concept_id: str, difficulty: str, prompt: str, gold_answer: str) -> dict[str, Any]:
    """Check a proposed question and, if every check passes, save it with status 'pending_approval'.

    Returns {"ok": True, "question_id", "status", "detail"} when saved, or {"ok": False, "error"} with
    the first problem found. Nothing is saved unless every check passes.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [Q1] tidy the three text inputs
    #          |
    #          v
    #   [Q2] each text empty or too long? difficulty not easy/medium/hard?   yes -> [E] error
    #          | no
    #          v
    #   [Q3] concept list loaded, and concept_id in it?                       no  -> [E] error
    #          | yes
    #          v
    #   [Q4] answer key readable (answer_key_problem)?                        no  -> [E] error
    #          | yes
    #          v
    #   [Q5] the same question already in the bank (any status)?              yes -> [E] error
    #          | no                                    ([Q5] and [Q6] run together under SAVE_LOCK)
    #          v
    #   [Q6] save with question_bank.propose_question -> row 'pending_approval'
    #          |
    #          v
    #   [R]  {ok: True, question_id, status, detail}

    # [Q1] tidy the three text inputs.
    tidy_concept_id = tidy_text(concept_id)
    tidy_prompt = tidy_text(prompt)
    tidy_gold_answer = tidy_text(gold_answer)

    # [Q2] each text must be non-empty and within its limit. The first problem found is returned, [E].
    problem = length_problem("concept_id", tidy_concept_id, MAX_CONCEPT_ID_LENGTH)
    if problem is not None:
        return math_tools.make_error(problem)  # [E]
    problem = length_problem("prompt", tidy_prompt, MAX_PROMPT_LENGTH)
    if problem is not None:
        return math_tools.make_error(problem)  # [E]
    problem = length_problem("gold_answer", tidy_gold_answer, MAX_GOLD_ANSWER_LENGTH)
    if problem is not None:
        return math_tools.make_error(problem)  # [E]
    # [Q2] the difficulty must be one of the three words. Through MCP the schema already enforces this;
    # the check also protects direct Python calls.
    if difficulty not in DIFFICULTIES:
        return math_tools.make_error(  # [E]
            "difficulty must be one of " + ", ".join(DIFFICULTIES) + ", not '" + str(difficulty) + "'."
        )

    # [Q3] the concept must be in the concept graph. If the graph can't be loaded, refuse rather than
    # let an unchecked question through (fail closed, AAI-14 p.22).
    known_concept_ids = load_concept_ids()
    if len(known_concept_ids) == 0:
        return math_tools.make_error(  # [E]
            "The concept list could not be loaded, so the concept_id can't be checked and nothing was saved."
        )
    if tidy_concept_id not in known_concept_ids:
        # The message lists the known ids, so the model can pick the right one and call again.
        return math_tools.make_error(  # [E]
            "Unknown concept_id '" + tidy_concept_id + "'. Known concept ids: " + ", ".join(known_concept_ids) + "."
        )

    # [Q4] the grader's code must be able to read the answer key.
    problem = answer_key_problem(tidy_gold_answer)
    if problem is not None:
        return math_tools.make_error(problem)  # [E]

    # [Q5] + [Q6] under the lock, so two identical calls arriving together can't both pass [Q5] (see SAVE_LOCK).
    with SAVE_LOCK:
        # [Q5] an exact copy of a question already in the bank is not saved again (any status, QB9).
        duplicate = find_duplicate(tidy_concept_id, tidy_prompt)
        if duplicate is not None:
            # This status is the word stored in the table ('pending_approval', 'approved', 'rejected').
            return math_tools.make_error(  # [E]
                "This question is already in the bank as " + duplicate["id"] + " (status: " + duplicate["status"]
                + "), so it was not saved again."
            )

        # [Q6] save it with Jilesh's function, which adds one row with status 'pending_approval'.
        saved = question_bank.propose_question(tidy_concept_id, difficulty, tidy_prompt, tidy_gold_answer)

    # [R] the result. The status is passed through unchanged from question_bank.propose_question (QB6). Note that
    # it says 'pending_teacher_approval', while the table stores 'pending_approval': two words for the same state,
    # both written by Jilesh's file, which stays unchanged (QB7).
    result: dict[str, Any] = {"ok": True}
    result["question_id"] = saved["question_id"]
    result["status"] = saved["status"]
    result["detail"] = SAVED_DETAIL
    return result


# ---------------------------------------------------------------------------
# The server and its one tool. It's a WRITE tool (decision QB5): it adds a row, never deletes or
# changes one (not destructive); a repeated identical call adds nothing, because [Q5] refuses
# copies (idempotent); and it touches only the local database (not open-world).
# ---------------------------------------------------------------------------
mcp: MCPServer = MCPServer(
    "question-bank",
    instructions=(
        "Draft NCERT Class 10 practice questions for teacher approval. "
        "Nothing here publishes a question: students only see questions the teacher has approved."
    ),
)

# The guide's read/write mark (capstone guide p.3): this tool writes. The export script lists it as "write".
WRITE: ToolAnnotations = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)

# What the model reads about the tool. It's the tool's real instructions, so it states every rule the checks enforce.
PROPOSE_DESCRIPTION: str = (
    "Save ONE new practice question as a DRAFT for the teacher to review (NCERT Class 10 Science, Ch 9-11).\n"
    "It does not publish anything: students can't see the question until the teacher approves it, and there\n"
    "is no publish tool. Use it only for a new question.\n"
    "- concept_id: a concept id from the concept graph (at most 60 characters), for example concept_ohms_law\n"
    "  or concept_mirror_formula.\n"
    "- difficulty: easy, medium or hard.\n"
    "- prompt: the question text the student will see (at most 1000 characters).\n"
    "- gold_answer: the answer key (at most 200 characters), computed with math-tools first. Write one of:\n"
    "  a number with a known unit in the NCERT sign convention ('-60 cm', '3 A', '2.5 D'), or a bare number;\n"
    "  a formula ('R = V/I'), in English letters, with ^ for powers and Greek letters as words ('rho'),\n"
    "  at most 100 characters; or a short text answer ('real and inverted').\n"
    "  Don't write 'name = value' ('I = 3 A'), 'value = name', or unworked arithmetic ('f = 1/20').\n"
    "An exact copy of a question already in the bank (any status) is refused. If it is refused as a copy,\n"
    "don't propose it again with small changes.\n"
    "The result says whether it was saved (with its question_id) or why not; for any other problem, fix it\n"
    "and call again."
)


@mcp.tool(description=PROPOSE_DESCRIPTION, annotations=WRITE)
def propose_question(concept_id: str, difficulty: Difficulty, prompt: str, gold_answer: str) -> ProposeResult:
    # This is the MCP tool. It has the same name as question_bank.propose_question, but it's a different
    # function: this one checks first ([Q1]-[Q5]) and only then calls that one ([Q6]).
    return run_and_log(concept_id, difficulty, prompt, gold_answer)


if __name__ == "__main__":
    # stdio transport (development, capstone guide p.5), like math_tools_server.py.
    mcp.run(transport="stdio")
