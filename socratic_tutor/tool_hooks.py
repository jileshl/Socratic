"""Tool hooks (R4): one check before every tool call, and one log line after it.

The capstone guide: "Every tool call passes through hooks that check permissions and budget before the call
and log it afterwards" (capstone guide p.2). For this project: "Hooks pre-tool: mode rules (quiz vs practice)
+ budget · post-tool: trace" (p.11, Figure 4), and "In practice mode, hooks prohibit complete worked
solutions" (p.11, step 2).

The check asks the security lecture's three questions, in this order: allowed? whose data? under the cap?
(AAI-15-2 p.46). It is plain code outside the model, so a cleverly worded message can't talk its way past it
(AAI-14 p.19). It fails closed: when it can't decide, it blocks (AAI-15-2 p.46).

It is a WRAPPER, not a callback. A LangChain callback is only told about a call; if it raises, the tool still
runs (AAI-14 p.22). A wrapper holds the "run the tool" button and presses it only when the check passes
(AAI-15-2 p.47). A blocked call is not a crash: the caller gets the text "BLOCKED: <reason>" instead of the
tool's result, the same way a course notebook returns "ERROR: ..." from its run_tool (L13 cell 13).

Two ways in, one rule set (decision S4-1):
    style 1  hooked_tool_node(agent, tools)          the prebuilt agent loop (L7 cell 36): a LangGraph ToolNode
                                                      that runs every call through our wrappers
    style 2  run_tool(agent, tool, arguments, state)  our own tool step (L11 cell 22's take_action), and today's
                                                      direct calls in graph.py
Once per student turn, the graph's first node calls start_turn(session_id), which resets the budget.

The session facts (session_id, student_id, mode) are read from the graph state, which the web server fills
from the stored session (the Practice / Quiz button), never from the chat or the model's arguments (S4-2).
"""

import hashlib
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from socratic_tutor import config


# ---------------------------------------------------------------------------
# The rules, as data. The check reads them, and the tests read them too.
# frozenset = a set that can't be changed by accident while the app runs.
# ---------------------------------------------------------------------------

# [allowed?] Which agent may call which tool (decision S4-3: Discussion post 1's map, with the 11 real tool
# names from docs/mcp_tool_list.json). The keys are the node names in Jilesh's graph. An agent or a tool that
# isn't here is blocked.
AGENT_TOOLS: dict[str, frozenset[str]] = {
    # The supervisor (code, no model) routes and plans. It is the only one that may read or write the learner model
    # (the learner-store server, added 13 Nov); no model-driven agent can change a student's mastery.
    "supervisor": frozenset({"get_learner_profile", "update_mastery"}),
    # The diagnostician asks a probing question; it may read the textbook.
    "diagnostician": frozenset({"search_textbook", "get_section", "get_exemplar"}),
    # The tutor gives cited hints from the textbook. It never gets the solvers, so it can't hand over a
    # complete worked solution from our tools (capstone guide p.11, step 2).
    "tutor": frozenset({"search_textbook", "get_section", "get_exemplar"}),
    # The question setter works out each answer key in code before a question is shown (p.11, step 5), and is
    # the only agent that may propose questions for the shared bank (p.12).
    "question_setter": frozenset({
        "search_textbook", "get_section", "get_exemplar",
        "solve_optics", "solve_electricity", "convert_to_si", "convert_from_si", "calculate",
        "propose_question",
    }),
    # The grader checks a student's answer with the solver, the numeric check and the equivalence check (p.11, step 6).
    "grader": frozenset({
        "solve_optics", "solve_electricity", "convert_to_si", "convert_from_si", "calculate",
        "check_numeric_answer", "check_equivalence",
    }),
}

# [allowed?, the mode rule] In a quiz only the grader may use tools, and only its two checking tools (decision
# S4-4). Every other agent gets nothing. Jilesh's graph already sends a quiz only to the grader; this keeps the
# same rule in code, in case the routing breaks or a model starts choosing the route.
QUIZ_MODE_TOOLS: dict[str, frozenset[str]] = {
    "grader": frozenset({"check_numeric_answer", "check_equivalence"}),
}

# The two session modes (capstone guide p.12: "a session graph with practice and quiz modes").
KNOWN_MODES: tuple[str, ...] = ("practice", "quiz")

# [log] Arguments whose VALUES may be written to the log: ids, formula names, numbers and units (decision S4-7).
SAFE_TO_LOG_ARGUMENTS: frozenset[str] = frozenset({
    "formula", "values", "length_unit", "unit", "value", "si_value", "tolerance",
    "concept_id", "difficulty", "chapter", "class_num", "top_k", "section_id", "exemplar_id",
})
# [log] Arguments that hold free text (a student's words, a question, an answer key): only their LENGTH is logged.
FREE_TEXT_ARGUMENTS: frozenset[str] = frozenset({
    "query", "prompt", "student_text", "gold_text", "gold_answer", "expression",
})
# Any other argument name is only counted, because the name itself could be text the model made up.

# A logged value, or a name inside a reason, is cut to this many characters.
MAX_LOGGED_VALUE_LENGTH: int = 60
# Even a safe-list argument is free text the model can fill, so a string value is logged only if it looks like
# an id, a unit or a formula name: at most this many characters, from the characters below, with no space, no
# "@" and no run of this many digits in a row (a phone number). Anything else is logged as its length.
MAX_TOKEN_LENGTH: int = 20
TOKEN_CHARACTERS: str = "._-/^"
MAX_DIGITS_IN_A_ROW: int = 5
# The keys of the solver's "values" dict (u, f, R, V ...) are logged only if they are this short.
MAX_VALUE_KEY_LENGTH: int = 10

# What a blocked call returns instead of the tool's result, followed by the reason.
BLOCKED_PREFIX: str = "BLOCKED: "

# The kill switch (decision S4-8): start the app with TOOLS_PAUSED=1 and every tool call is blocked.
PAUSE_VARIABLE: str = "TOOLS_PAUSED"

# The fixed reasons. The ones that depend on the call are built where they are used.
REASON_FACTS_MISSING: str = "session facts missing"
REASON_PAUSED: str = "tools paused by an operator"
REASON_OTHER_STUDENT: str = "another student's data"
REASON_TURN_BUDGET: str = "tool budget for this turn used up"
REASON_HOOK_ERROR: str = "hook error"
REASON_BAD_ARGUMENTS: str = "the arguments must be a plain dict of name -> value"
REASON_FACTS_CHANGED: str = "a tool may not change the session facts"

# The session facts: only the web server sets them (S4-2). No tool may change them (see changes_session_facts).
SESSION_FACT_KEYS: tuple[str, ...] = ("session_id", "student_id", "mode")

# "The button": what LangGraph's ToolNode hands a wrapper, so the wrapper can run the tool (style 1).
RunTheTool = Callable[[ToolCallRequest], ToolMessage | Command]
AsyncRunTheTool = Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]


# ---------------------------------------------------------------------------
# Logging: one JSON line per tool call, allowed or blocked, to stderr (decision S4-7).
# json.dumps escapes quotes and line breaks, so a value can't fake a second field or a second line.
# ---------------------------------------------------------------------------
logger: logging.Logger = logging.getLogger("tool-hooks")
if not logger.handlers:
    # Send the log lines to stderr, with a timestamp, like the three MCP servers do.
    stderr_handler: logging.StreamHandler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter("%(asctime)s tool-hooks %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(stderr_handler)
    logger.setLevel(logging.INFO)
    # Keep these lines out of other loggers (for example the app's root logger).
    logger.propagate = False


# ---------------------------------------------------------------------------
# The budget counters (decision S4-6): per session, for the current turn, shared by all agents
# ("one circuit breaker for the group", AAI-15-2 p.54). They live in memory, behind a lock, because
# ToolNode runs the calls of one model message at the same time, on several threads.
# ---------------------------------------------------------------------------


@dataclass
class TurnCounts:
    """How many tool calls one session has made in its current turn."""

    # Every attempt this turn that reached the counting step [H2], allowed or blocked.
    attempts: int = 0
    # How often each exact call (tool name + its arguments) was attempted this turn. The key is a SHA-256
    # fingerprint of the call, so the student's words are never kept in memory.
    same_call: dict[str, int] = field(default_factory=dict)


# session_id -> that session's counts for the current turn.
_TURN_COUNTS: dict[str, TurnCounts] = {}
# Only one thread at a time may read or change _TURN_COUNTS.
_COUNTS_LOCK: threading.Lock = threading.Lock()


def start_turn(session_id: str) -> None:
    """Reset one session's tool budget. The graph's first node calls this once per student turn."""
    # Flowchart:
    #
    #   [T1] replace the session's counts with fresh ones (0 attempts, no calls seen)

    # [T1] fresh counts for this session; the lock keeps a call that is being counted right now consistent.
    with _COUNTS_LOCK:
        _TURN_COUNTS[session_id] = TurnCounts()


def normalised(value: Any) -> Any:
    """A value written the same way however the model spelled it: text trimmed and in one case, 4.0 as 4.

    Used only to recognise "the same call again"; the tool itself always gets the arguments unchanged.
    """
    # Text: "Concave mirror " and "concave mirror" are the same search.
    if isinstance(value, str):
        return value.strip().casefold()
    # A whole number written as a float (4.0) is the same as 4.
    if isinstance(value, float) and value.is_integer():
        return int(value)
    # A dict: the same, key by key (the keys too).
    if isinstance(value, dict):
        tidy_dict: dict[str, Any] = {}
        for key in value:
            tidy_dict[str(normalised(str(key)))] = normalised(value[key])
        return tidy_dict
    # A list: the same, item by item.
    if isinstance(value, (list, tuple)):
        tidy_list: list[Any] = []
        for item in value:
            tidy_list.append(normalised(item))
        return tidy_list
    # Numbers, True/False and None stay as they are.
    return value


def call_fingerprint(tool_name: str, arguments: dict[str, Any]) -> str:
    """A SHA-256 fingerprint of one call (the tool + its normalised arguments, keys sorted)."""
    call_text = tool_name + " " + json.dumps(normalised(arguments), sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(call_text.encode("utf-8")).hexdigest()


def count_attempt(session_id: str, tool_name: str, arguments: dict[str, Any]) -> tuple[int, int]:
    """Count one attempt for this session's turn. Returns (attempts this turn, times this exact call was made)."""
    # The same tool with the same arguments, however the model spelled them, gives the same fingerprint.
    call_key = call_fingerprint(tool_name, arguments)
    with _COUNTS_LOCK:
        # A session that never called start_turn still gets counted: its counts just keep growing,
        # so a forgotten start_turn ends in blocks that show up in the log, never in "no limit".
        counts = _TURN_COUNTS.get(session_id)
        if counts is None:
            counts = TurnCounts()
            _TURN_COUNTS[session_id] = counts
        # One more attempt this turn.
        counts.attempts = counts.attempts + 1
        # One more time for this exact call.
        times_before = counts.same_call.get(call_key, 0)
        counts.same_call[call_key] = times_before + 1
        return counts.attempts, counts.same_call[call_key]


# ---------------------------------------------------------------------------
# The check: one place, used by both ways in.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HookDecision:
    """What the check decided: allowed or not, and why not (an empty reason when allowed)."""

    allowed: bool
    reason: str


def short(text: Any) -> str:
    """Any value as text, cut to MAX_LOGGED_VALUE_LENGTH characters (for reasons and log fields)."""
    return str(text)[:MAX_LOGGED_VALUE_LENGTH]


def read_session_facts(state: Any) -> dict[str, str] | None:
    """The session facts from the graph state: session_id, student_id and mode. None if any is missing or wrong."""
    # The graph state is a dict (SocraticState is a TypedDict). Anything else can't be read safely.
    if not isinstance(state, dict):
        return None
    facts: dict[str, str] = {}
    # session_id and student_id must be non-empty text; the web server sets both when the session starts.
    for key in ("session_id", "student_id"):
        value = state.get(key)
        if not isinstance(value, str) or value.strip() == "":
            return None
        facts[key] = value
    # mode must be one of the two known modes. A missing mode is NOT treated as practice (fail closed, S4-2).
    mode = state.get("mode")
    if mode not in KNOWN_MODES:
        return None
    facts["mode"] = mode
    return facts


def tools_paused() -> bool:
    """True when an operator started the app with TOOLS_PAUSED=1 (the kill switch, S4-8). Read on every call."""
    return os.environ.get(PAUSE_VARIABLE, "").strip() == "1"


def tool_is_allowed(agent_name: str, tool_name: str, mode: str) -> bool:
    """True if this agent may call this tool in this mode (the permission map, then the quiz rule)."""
    if mode == "quiz":
        # In a quiz, only the quiz table counts (S4-4); an agent missing from it gets nothing.
        allowed_tools = QUIZ_MODE_TOOLS.get(agent_name, frozenset())
    else:
        # In practice, the agent's own list (S4-3); an unknown agent gets nothing.
        allowed_tools = AGENT_TOOLS.get(agent_name, frozenset())
    return tool_name in allowed_tools


def belongs_to_another_student(arguments: dict[str, Any], student_id: str) -> bool:
    """True if the call names a student_id that isn't the session's own student (the confused deputy, S4-5)."""
    # A call without a student_id argument reads nobody's record by id.
    if "student_id" not in arguments:
        return False
    named_student = arguments["student_id"]
    # Only exactly the session's own id is fine; anything else (another id, a number, None) is another student.
    if isinstance(named_student, str) and named_student == student_id:
        return False
    return True


def is_plain_arguments(arguments: Any) -> bool:
    """True for a plain dict of argument name (text) -> value, the only shape a tool call's arguments may have."""
    # Not a dict at all: nothing to check.
    if not isinstance(arguments, dict):
        return False
    # A dict shaped like a WHOLE tool call: a LangChain tool's invoke() would run its inner arguments instead.
    if arguments.get("type") == "tool_call":
        return False
    # Every argument name must be text (a model's arguments always are; code could pass anything).
    for name in arguments:
        if not isinstance(name, str):
            return False
    return True


def blocked(reason: str) -> HookDecision:
    """A decision to block, with its reason."""
    return HookDecision(allowed=False, reason=reason)


def decide_tool_call(agent_name: str, tool_name: str, arguments: dict[str, Any], state: Any) -> HookDecision:
    """The three questions, in order. May raise on strange input: check_tool_call turns that into a block."""
    # [H0] the session facts, from the graph state (never from the chat or the model's arguments).
    facts = read_session_facts(state)
    if facts is None:
        return blocked(REASON_FACTS_MISSING)
    # [H1] the kill switch.
    if tools_paused():
        return blocked(REASON_PAUSED)
    # The arguments must be a plain dict (name -> value). Anything else can't be checked, so it is blocked. So is
    # a dict shaped like a WHOLE tool call ({"type": "tool_call", "args": {...}}): a LangChain tool's invoke()
    # would unpack it and run the INNER arguments, which this check never saw (found by the independent review).
    if not is_plain_arguments(arguments):
        return blocked(REASON_BAD_ARGUMENTS)
    # [H2] count this attempt before the checks below, so attempts they block count too: a model that keeps
    # calling a locked tool runs out of budget as well. (Calls blocked above aren't counted: they have no
    # session to count against, or nothing can run while the tools are paused.)
    attempts, same_call_count = count_attempt(facts["session_id"], tool_name, arguments)
    # [H3] allowed? The permission map in practice, the quiz table in a quiz.
    if not tool_is_allowed(agent_name, tool_name, facts["mode"]):
        return blocked(name_for_log(tool_name) + " is not allowed for " + short(agent_name) + " in " + facts["mode"] + " mode")
    # [H4] whose data? Only the session's own student.
    if belongs_to_another_student(arguments, facts["student_id"]):
        return blocked(REASON_OTHER_STUDENT)
    # [H5] under the cap? The whole turn first, then this exact call.
    if attempts > config.MAX_TOOL_CALLS_PER_TURN:
        return blocked(REASON_TURN_BUDGET)
    if same_call_count > config.MAX_IDENTICAL_TOOL_CALLS:
        return blocked("the same call was already made " + str(config.MAX_IDENTICAL_TOOL_CALLS) + " times this turn")
    # Every question passed.
    return HookDecision(allowed=True, reason="")


def check_tool_call(agent_name: str, tool_name: str, arguments: dict[str, Any], state: Any) -> HookDecision:
    """Decide whether one tool call may run. Never raises: a problem inside the check blocks the call."""
    # Flowchart (each [box] matches a comment in decide_tool_call):
    #
    #   [H0] session_id, student_id, mode from the graph state     missing or unknown -> BLOCK
    #   [H1] TOOLS_PAUSED=1?                                        yes -> BLOCK
    #   [H2] count this attempt (this turn; this exact call)
    #   [H3] allowed? practice: AGENT_TOOLS; quiz: QUIZ_MODE_TOOLS  no -> BLOCK
    #   [H4] whose data? a student_id that isn't the session's     -> BLOCK
    #   [H5] under the cap? > MAX_TOOL_CALLS_PER_TURN this turn, or this exact call
    #        > MAX_IDENTICAL_TOOL_CALLS times                        -> BLOCK
    #   any error inside [H0]-[H5] -> BLOCK "hook error" (fail closed; the turn goes on)
    try:
        return decide_tool_call(agent_name, tool_name, arguments, state)
    except Exception:  # fail closed: if the check itself breaks, the tool must not run
        return blocked(REASON_HOOK_ERROR)


# ---------------------------------------------------------------------------
# The log line [P1].
# ---------------------------------------------------------------------------


def known_tool_names() -> set[str]:
    """Every tool name in the permission map: the only tool names the log writes out in full."""
    names: set[str] = set()
    for tools in AGENT_TOOLS.values():
        names.update(tools)
    return names


def name_for_log(tool_name: Any) -> str:
    """A tool name as the log (and a BLOCKED reason) may show it: a real tool's name, otherwise only its length.

    In the prebuilt loop the model writes the tool name itself, so a made-up "name" could carry a student's words.
    """
    tool_text = str(tool_name)
    if tool_text in known_tool_names():
        return tool_text
    return "<unknown tool, " + str(len(tool_text)) + " chars>"


def looks_like_a_token(text: str) -> bool:
    """True for a short id, unit or formula name ("9.2.4", "cm", "mirror", "kWh"); False for anything else.

    No spaces, no "@" and no long run of digits, so sentences, e-mail addresses and phone numbers are never
    logged, even when the model puts them into a safe-list argument such as "unit".
    """
    if len(text) == 0 or len(text) > MAX_TOKEN_LENGTH:
        return False
    digits_in_a_row = 0
    for character in text:
        # Only ASCII letters, digits and a few id/unit characters ("._-/^").
        if not character.isascii():
            return False
        if not (character.isalnum() or character in TOKEN_CHARACTERS):
            return False
        # Count digits in a row: 5 or more could be part of a phone number.
        if character.isdigit():
            digits_in_a_row = digits_in_a_row + 1
            if digits_in_a_row >= MAX_DIGITS_IN_A_ROW:
                return False
        else:
            digits_in_a_row = 0
    return True


def is_a_number(value: Any) -> bool:
    """True for an int or a float (not True/False, which Python also counts as numbers)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_numbers(value: Any) -> bool:
    """True for a number, or a list of numbers (the solver's values: {"u": -15} or {"resistors": [2, 3]})."""
    if is_a_number(value):
        return True
    if isinstance(value, list):
        for item in value:
            if not is_a_number(item):
                return False
        return True
    return False


def numbers_for_log(values: dict[Any, Any]) -> str:
    """The solver's values dict for the log: short keys with numbers are shown; any other entry is only counted."""
    kept: dict[str, Any] = {}
    hidden_count = 0
    for key in sorted(values, key=str):
        key_text = str(key)
        if len(key_text) <= MAX_VALUE_KEY_LENGTH and looks_like_a_token(key_text) and is_numbers(values[key]):
            kept[key_text] = values[key]
        else:
            hidden_count = hidden_count + 1
    if hidden_count > 0:
        kept["hidden"] = hidden_count
    return short(json.dumps(kept, sort_keys=True, ensure_ascii=True))


def safe_value(value: Any) -> Any:
    """A safe-list argument, ready for the log: numbers as they are, an id-like text as it is, anything else hidden."""
    # Numbers, True/False and None are logged as they are.
    if value is None or isinstance(value, (bool, int, float)):
        return value
    # Text is logged only if it looks like an id, a unit or a formula name; otherwise only its length.
    if isinstance(value, str):
        if looks_like_a_token(value):
            return value
        return "<" + str(len(value)) + " chars>"
    # The solver's values dict: short keys with numbers only.
    if isinstance(value, dict):
        return numbers_for_log(value)
    # A list or anything else: only what kind of value it was.
    if isinstance(value, (list, tuple)):
        return "<list of " + str(len(value)) + " items>"
    return "<" + type(value).__name__ + ">"


def arguments_for_log(arguments: Any) -> dict[str, Any]:
    """The arguments as the log may show them: safe values as values, free text as its length, others counted."""
    shown: dict[str, Any] = {}
    # Arguments that aren't a dict are only described, never shown.
    if not isinstance(arguments, dict):
        shown["not_a_dict"] = type(arguments).__name__
        return shown
    other_count = 0
    # Sorted, so the same call always gives the same line.
    for name in sorted(arguments, key=str):
        value = arguments[name]
        if name in SAFE_TO_LOG_ARGUMENTS:
            # An id, a formula name, a number or a unit (if it really looks like one).
            shown[name] = safe_value(value)
        elif name in FREE_TEXT_ARGUMENTS:
            # A student's words, a question or an answer key: only how long it was.
            shown[name] = "<" + str(len(str(value))) + " chars>"
        else:
            # Any other name (student_id, or a name the model made up) is only counted.
            other_count = other_count + 1
    if other_count > 0:
        shown["other_arguments"] = other_count
    return shown


def build_log_line(agent_name: str, tool_name: str, arguments: Any, state: Any, decision: HookDecision,
                   milliseconds: float | None, ok: bool | None) -> str:
    """The JSON line for one tool call. May raise on strange input: log_attempt catches that."""
    # The session and mode as the state holds them (they may be missing: that's why a call was blocked).
    # They come from the web server, not the model, so they are only cut short.
    session_id = None
    mode = None
    if isinstance(state, dict):
        session_id = state.get("session_id")
        mode = state.get("mode")
    # "allowed" or "blocked", in words, so the log can be counted (blocked calls are worth an alert, AAI-15-2 p.59).
    decision_word = "blocked"
    if decision.allowed:
        decision_word = "allowed"
    # The time, rounded; None when the tool never ran.
    rounded_ms = None
    if milliseconds is not None:
        rounded_ms = round(milliseconds, 1)
    record: dict[str, Any] = {
        "event": "tool_call",
        "session": short(session_id),
        "agent": short(agent_name),
        "tool": name_for_log(tool_name),
        "mode": short(mode),
        "decision": decision_word,
        "reason": decision.reason,
        "ms": rounded_ms,
        "ok": ok,
        "args": arguments_for_log(arguments),
    }
    # ensure_ascii=True: the line stays plain ASCII, so a Windows console can always print it.
    return json.dumps(record, ensure_ascii=True, default=str)


def log_attempt(agent_name: str, tool_name: str, arguments: Any, state: Any, decision: HookDecision,
                milliseconds: float | None, ok: bool | None) -> str:
    """Write one JSON line about one tool call (allowed or blocked) to the "tool-hooks" logger, and return it.

    Never raises: by the time it runs, an allowed tool has already done its work, so a logging problem must not
    crash the turn or lose the tool's result (found by the independent review).
    """
    # Flowchart:
    #
    #   [P1] who (session, agent), what (tool, mode, arguments as the log may show them),
    #        the decision and its reason, how long the tool took, and whether it worked
    #        -> one JSON line. The student id and the student's words are never written.
    #   [P2] building the line failed? -> a fixed fallback line instead (never an exception)

    # [P1] the normal line.
    try:
        line = build_log_line(agent_name, tool_name, arguments, state, decision, milliseconds, ok)
    except Exception:
        # [P2] something in the call couldn't be written (e.g. an argument that refers to itself): say so plainly.
        decision_word = "blocked"
        if decision.allowed:
            decision_word = "allowed"
        line = json.dumps({"event": "tool_call", "decision": decision_word, "log_error": True})
    # Writing the line must not raise either (a broken log handler is not the student's problem).
    try:
        logger.info(line)
    except Exception:
        pass
    return line


def result_ok(result: Any) -> bool | None:
    """Whether a tool's result says it worked: our tools' {"ok": ...}, or a ToolMessage that isn't an error.

    None if that can't be read; it is only used for the log line, so it never raises.
    """
    try:
        # A LangGraph ToolMessage with status "error" means the tool failed.
        if isinstance(result, ToolMessage):
            return result.status != "error"
        # Our tools return {"ok": True/False, ...}.
        if isinstance(result, dict) and isinstance(result.get("ok"), bool):
            return result["ok"]
        # Anything else (a list of search hits, a number, a Command) counts as worked.
        return True
    except Exception:
        return None


def changes_session_facts(result: Any) -> bool:
    """True if a tool's result is a LangGraph Command that would change session_id, student_id or mode.

    A tool may return Command(update={...}) to change the graph state. If it could change the session facts,
    every later check would trust the new values (a quiz could turn into practice), so such a result is refused
    (found by the independent review). An update we can't read is refused too (fail closed).
    """
    if not isinstance(result, Command):
        return False
    update = result.update
    # No update at all (for example a Command that only moves to another node).
    if update is None:
        return False
    keys: list[str] = []
    if isinstance(update, dict):
        # The usual form: {"key": new value, ...}.
        for key in update:
            keys.append(str(key))
    elif isinstance(update, (list, tuple)):
        # The other form LangGraph accepts: [("key", new value), ...].
        for pair in update:
            if isinstance(pair, (list, tuple)) and len(pair) > 0:
                keys.append(str(pair[0]))
            else:
                return True
    else:
        # Any other kind of update can't be checked here, so it is refused.
        return True
    for key in keys:
        if key in SESSION_FACT_KEYS:
            return True
    return False


def after_the_tool(agent_name: str, tool_name: str, arguments: Any, state: Any, decision: HookDecision,
                   started: float, result: Any) -> HookDecision:
    """The post-tool step, shared by both ways in: refuse a result that changes the session facts, then log.

    Returns the decision that was logged: the same allowed decision, or a block if the result was refused.
    The tool has already run either way; a refused result only means its state change is thrown away.
    """
    # How long the tool took.
    milliseconds = (time.perf_counter() - started) * 1000
    # A result that would change the session facts is refused (its state change is never applied).
    if changes_session_facts(result):
        refused = blocked(REASON_FACTS_CHANGED)
        log_attempt(agent_name, tool_name, arguments, state, refused, milliseconds, False)
        return refused
    # The normal case: one log line about the call that ran.
    log_attempt(agent_name, tool_name, arguments, state, decision, milliseconds, result_ok(result))
    return decision


# ---------------------------------------------------------------------------
# Style 2: run_tool, for our own tool step (L11 cell 22) and for today's direct calls.
# ---------------------------------------------------------------------------


def name_of_tool(tool: Any) -> str:
    """The tool's name: a LangChain tool's .name, or a plain Python function's own name ("" if neither)."""
    try:
        tool_name = getattr(tool, "name", None)
        if isinstance(tool_name, str):
            return tool_name
        return str(getattr(tool, "__name__", ""))
    except Exception:
        # A name that can't be read is an unknown tool, which the check blocks.
        return ""


def run_tool(agent_name: str, tool: Any, arguments: dict[str, Any], state: Any) -> Any:
    """Run one tool for one agent through the hook. Returns the tool's own result, or "BLOCKED: <reason>"."""
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [R1] check_tool_call(agent, the tool's name, arguments, state)
    #          |
    #          |-- blocked -> [R2] log it; return "BLOCKED: <reason>" (the tool never runs)
    #          v
    #   [R3] allowed -> run it (a LangChain tool: tool.run(arguments); a function: tool(**arguments)), time it
    #          |  the tool raises? log it with ok=False, then let the error go up as before
    #          v
    #   [R4] the result would change the session facts? -> log it; return "BLOCKED: ..." instead
    #        otherwise log it; return the tool's result, unchanged

    # [R1] the check, under the tool's own name.
    tool_name = name_of_tool(tool)
    decision = check_tool_call(agent_name, tool_name, arguments, state)
    # [R2] blocked: the tool is never run.
    if not decision.allowed:
        log_attempt(agent_name, tool_name, arguments, state, decision, None, None)
        return BLOCKED_PREFIX + decision.reason
    # [R3] allowed: run it, and time it.
    started = time.perf_counter()
    try:
        if isinstance(tool, BaseTool):
            # A LangChain tool takes its arguments as one dict. run(), not invoke(): invoke() would unpack a
            # dict shaped like a whole tool call and run its INNER arguments (found by the independent review).
            result = tool.run(arguments)
        else:
            # A plain Python function takes them as keyword arguments.
            result = tool(**arguments)
    except Exception:
        # The hook doesn't change how a tool's own error is handled: it logs it, then lets it go up.
        log_attempt(agent_name, tool_name, arguments, state, decision, (time.perf_counter() - started) * 1000, False)
        raise
    # [R4] the post-tool step: refuse a result that changes the session facts; log.
    final_decision = after_the_tool(agent_name, tool_name, arguments, state, decision, started, result)
    if not final_decision.allowed:
        return BLOCKED_PREFIX + final_decision.reason
    # The result exactly as the tool returned it.
    return result


def is_blocked(result: Any) -> bool:
    """True if run_tool blocked the call (its result is "BLOCKED: <reason>"), so a caller can tell."""
    return isinstance(result, str) and result.startswith(BLOCKED_PREFIX)


# ---------------------------------------------------------------------------
# Style 1: the wrappers, and hooked_tool_node for the prebuilt agent loop (L7 cell 36).
# ---------------------------------------------------------------------------


def parts_of_request(request: ToolCallRequest) -> tuple[str, Any, str]:
    """The tool name, the arguments and the call id from a ToolNode request (parts that can't be read become empty)."""
    try:
        call = request.tool_call
        tool_name = str(call.get("name", ""))
        arguments = call.get("args", {})
        call_id = str(call.get("id", ""))
        return tool_name, arguments, call_id
    except Exception:
        # An unreadable request: an empty name and no arguments, which the check blocks.
        return "", None, ""


def blocked_message(tool_name: str, call_id: str, reason: str) -> ToolMessage:
    """The error result the model sees instead of the tool's result (AAI-15-2 p.47)."""
    return ToolMessage(content=BLOCKED_PREFIX + reason, tool_call_id=call_id, name=name_for_log(tool_name), status="error")


def make_tool_hook(agent_name: str) -> Callable[[ToolCallRequest, RunTheTool], ToolMessage | Command]:
    """Build the wrapper for one agent, for ToolNode(wrap_tool_call=...). The agent's name is fixed here, in code."""

    def tool_hook(request: ToolCallRequest, run_the_tool: RunTheTool) -> ToolMessage | Command:
        """LangGraph hands us the call and the button that runs it; we press it only if the check passes."""
        # Flowchart (each [box] matches a comment in the code below):
        #
        #   [W1] check_tool_call(agent, tool name, arguments, the graph state)
        #          |-- blocked -> [W2] log it; return an error ToolMessage "BLOCKED: <reason>" (the button isn't pressed)
        #          v
        #   [W3] allowed -> press the button (run_the_tool), time it
        #          v
        #   [W4] the result would change the session facts? -> an error ToolMessage instead (the change is dropped)
        #        otherwise log it; return the tool's result

        # [W1] the check; the state is the graph's state, not anything the model wrote.
        tool_name, arguments, call_id = parts_of_request(request)
        decision = check_tool_call(agent_name, tool_name, arguments, request.state)
        # [W2] blocked: return an error result without pressing the button, so the tool never runs.
        if not decision.allowed:
            log_attempt(agent_name, tool_name, arguments, request.state, decision, None, None)
            return blocked_message(tool_name, call_id, decision.reason)
        # [W3] allowed: press the button, and time it.
        started = time.perf_counter()
        try:
            result = run_the_tool(request)
        except Exception:
            log_attempt(agent_name, tool_name, arguments, request.state, decision, (time.perf_counter() - started) * 1000, False)
            raise
        # [W4] the post-tool step: refuse a result that changes the session facts; log.
        final_decision = after_the_tool(agent_name, tool_name, arguments, request.state, decision, started, result)
        if not final_decision.allowed:
            return blocked_message(tool_name, call_id, final_decision.reason)
        return result

    return tool_hook


def make_async_tool_hook(agent_name: str) -> Callable[[ToolCallRequest, AsyncRunTheTool], Awaitable[ToolMessage | Command]]:
    """The same wrapper for async runs (ToolNode(awrap_tool_call=...)): MCP tools loaded through an adapter are async."""

    async def async_tool_hook(request: ToolCallRequest, run_the_tool: AsyncRunTheTool) -> ToolMessage | Command:
        """The same boxes as tool_hook, [W1]-[W4]; only pressing the button is awaited."""
        # [W1] the check.
        tool_name, arguments, call_id = parts_of_request(request)
        decision = check_tool_call(agent_name, tool_name, arguments, request.state)
        # [W2] blocked: the button isn't pressed.
        if not decision.allowed:
            log_attempt(agent_name, tool_name, arguments, request.state, decision, None, None)
            return blocked_message(tool_name, call_id, decision.reason)
        # [W3] allowed: press the button (and wait for it), and time it.
        started = time.perf_counter()
        try:
            result = await run_the_tool(request)
        except Exception:
            log_attempt(agent_name, tool_name, arguments, request.state, decision, (time.perf_counter() - started) * 1000, False)
            raise
        # [W4] the post-tool step.
        final_decision = after_the_tool(agent_name, tool_name, arguments, request.state, decision, started, result)
        if not final_decision.allowed:
            return blocked_message(tool_name, call_id, final_decision.reason)
        return result

    return async_tool_hook


def hooked_tool_node(agent_name: str, tools: list[Any]) -> ToolNode:
    """A LangGraph ToolNode for one agent that runs every call through the hook, in sync and async runs alike.

    Both wrappers are set: with only the sync one, an async tool (an MCP tool) is blocked correctly but crashes
    the turn when it is allowed ("does not support sync invocation"). Measured with langgraph-prebuilt 1.1.1.
    """
    # Flowchart:
    #
    #   [N1] every tool offered must be in the agent's own list (AGENT_TOOLS); otherwise refuse to build the node,
    #        because offering a tool the agent may never call is a wiring mistake (least privilege, guide p.3)
    #   [N2] ToolNode(tools, wrap_tool_call=<sync wrapper>, awrap_tool_call=<async wrapper>)

    # [N1] find any offered tool that isn't on the agent's list.
    allowed_tools = AGENT_TOOLS.get(agent_name, frozenset())
    not_allowed: list[str] = []
    for tool in tools:
        tool_name = name_of_tool(tool)
        if tool_name not in allowed_tools:
            not_allowed.append(tool_name)
    if len(not_allowed) > 0:
        raise ValueError("Tools not allowed for " + agent_name + ": " + ", ".join(not_allowed))
    # [N2] the tool node, with both wrappers.
    return ToolNode(tools, wrap_tool_call=make_tool_hook(agent_name), awrap_tool_call=make_async_tool_hook(agent_name))
