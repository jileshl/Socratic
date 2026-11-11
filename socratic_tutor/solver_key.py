"""The solver computes every answer key (R4 plumbing, PR-2; decision I2: "the model proposes; code decides").

The question setter's model writes a question and a CALCULATION: which formula, the given values, the length
unit and what is asked. This module makes that call in code (math-tools' solve_optics / solve_electricity) and
writes the answer key from the solver's result. The model's own answer key is never read.
This is the course's "the model reads, code applies the rules" split (L12 cells 62-65): the model fills a typed
record and is told not to work out the answer; code does the arithmetic; what code can't read goes to a person,
here as a refusal the teacher sees.

The calculation the model sends (decision P2-3):
    {"formula": "mirror_formula", "values": {"u": -30, "f": -20}, "length_unit": "cm", "find": "v"}
Jilesh's flat shape from #53 (the values next to "formula") is read too, so his fallback questions still work.

A draft is REFUSED, not proposed, when:
- there is no calculation (decision P2-4: numeric questions only), or it is malformed;
- the formula or an input name is unknown;
- a given number is not written in the question text (P2-5);
- a "concave"/"convex" question gives f, a radius or a power with the wrong sign (P2-13; never flipped);
- the solver refuses (for example the object is at the focus);
- the solver solved for something other than what the question asks ("find");
- the key's unit can't be read by the grader (for example "ohm m").

Nothing here raises: every problem comes back as {"ok": False, "error": ...} (L7 cell 26: errors are values).
The solver functions are called in-process, by name (decision I3), so PR-3 can wrap each call in a tool hook.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from socratic_tutor import policy
from socratic_tutor.tools import math_tools_server
from socratic_tutor.tools.question_bank_server import answer_key_problem


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Formulas whose result is always the same quantity, so the model may leave "find" out
# (checked against the solved_for names that math_tools.py returns).
ONE_WAY_RESULTS: dict[str, str] = {
    "focal_length_from_radius": "f",
    "image_nature": "nature",
    "combine_lens_powers": "P",
    "wire_area": "area",
    "series_resistance": "Rs",
    "parallel_resistance": "Rp",
}
# Short names a model (or #53's fallback questions) may use for a formula; code maps them to the catalogue name.
# Moved here from Jilesh's FORMULA_ALIASES in graph.py (#53); the catalogue names map to themselves already.
FORMULA_ALIASES: dict[str, str] = {
    "mirror": "mirror_formula",
    "lens": "lens_formula",
    "power": "lens_power",
    "parallel": "parallel_resistance",
    "resistors_parallel": "parallel_resistance",
    "series": "series_resistance",
    "resistors_series": "series_resistance",
    "ohm": "ohms_law",
    "ohms": "ohms_law",
    "joule": "joule_heating",
    "heating": "joule_heating",
}
# The keys of a calculation that are not given values.
NOT_VALUE_KEYS: list[str] = ["formula", "find", "length_unit", "values"]
# Two numbers count as the same when they agree to 1 part in a million (float noise, e.g. 0.5 mm = 0.0005 m).
SAME_NUMBER_TOLERANCE: float = 1e-6
# The optics inputs whose sign follows from "concave" (negative) or "convex" (positive), per formula (P2-13).
SIGN_CHECKED_INPUTS: dict[str, list[str]] = {
    "mirror_formula": ["f"],
    "lens_formula": ["f"],
    "focal_length_from_radius": ["radius_of_curvature"],
    "lens_power": ["f", "p"],
}
# The order in which a set's drafts are asked for (decision P2-2: easy, medium, hard, then round again).
DIFFICULTY_ORDER: list[str] = ["easy", "medium", "hard"]
# The most drafts one teacher request may ask for (P2-2; approval_gate.MAX_SET_SIZE stays the hard cap).
MAX_DRAFTS: int = 5
# The longest model error text passed on to the teacher.
MAX_ERROR_TEXT: int = 160


# ---------------------------------------------------------------------------
# What the model is shown
# ---------------------------------------------------------------------------


def formula_list_for_the_model() -> str:
    """The formulas the question setter may use, with their input names, as text for its prompt."""
    lines: list[str] = []
    # The optics catalogue, with the length-unit rule.
    lines.append("Optics (Ch 9 and 10; give length_unit, the unit of every distance, for example \"cm\"):")
    lines.append(math_tools_server.catalogue_text(math_tools_server.OPTICS_FORMULAS))
    # The electricity catalogue, with the SI rule.
    lines.append("Electricity (Ch 11; every value in SI units: V, A, ohm, s, C, J, W, m):")
    lines.append(math_tools_server.catalogue_text(math_tools_server.ELECTRICITY_FORMULAS))
    # What "find" means, and the formulas whose result is fixed.
    lines.append("find = the input you left out. These formulas always give one result, so find is that result:")
    for name in ONE_WAY_RESULTS:
        lines.append("- " + name + ": find is " + ONE_WAY_RESULTS[name])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reading the model's calculation
# ---------------------------------------------------------------------------


def is_plain_number(value: Any) -> bool:
    """True for an int or a float, but not for True/False (a bool is an int in Python) and not for NaN or inf."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    # NaN and infinity can't be a given value of a school question.
    return math.isfinite(value)


def catalogue_name(raw_formula: str) -> str:
    """The catalogue name for a formula the model wrote: lowercase, no surrounding spaces, aliases mapped."""
    name: str = raw_formula.strip().lower()
    if name in FORMULA_ALIASES:
        return FORMULA_ALIASES[name]
    return name


def read_value(name: str, value: Any) -> tuple[Any, str | None]:
    """[C4] One given value: a plain number, or a non-empty list of plain numbers (resistors, powers).

    Returns (a copy of the value, None) or (None, the problem).
    """
    # A single number.
    if is_plain_number(value):
        return value, None
    # A list of numbers, copied so the model's reply can't change it later.
    if isinstance(value, list) and len(value) > 0:
        numbers: list[Any] = []
        for item in value:
            if not is_plain_number(item):
                return None, "The value of " + name + " must be numbers only."
            numbers.append(item)
        return numbers, None
    return None, "The value of " + name + " must be a number (or a list of numbers)."


def read_calculation(calculation: Any) -> tuple[dict[str, Any] | None, str | None]:
    """[C1]-[C6] Read the model's calculation into {"formula", "values", "find", "length_unit"}, or a problem.

    Returns (the calculation, None) or (None, what is wrong with it).
    """
    # Flowchart (each [box] matches a comment below):
    #
    #   [C1] an object (a dict)?                                     no -> problem
    #   [C2] "formula": non-empty text? (aliases mapped)              no -> problem
    #   [C3] the values: calculation["values"], or every other key (#53's flat shape)
    #   [C4] each value a number, or a non-empty list of numbers?    no -> problem
    #   [C5] "find": text; missing only for a one-way formula        no -> problem
    #   [C6] "length_unit": text, or missing                         no -> problem
    #   [R]  ({"formula", "values", "find", "length_unit"}, None)

    # [C1] the calculation must be an object.
    if not isinstance(calculation, dict):
        return None, "The calculation must be an object: {formula, values, length_unit, find}."

    # [C2] the formula's name.
    raw_formula: Any = calculation.get("formula")
    if not isinstance(raw_formula, str) or raw_formula.strip() == "":
        return None, "The calculation needs a formula name."
    formula: str = catalogue_name(raw_formula)

    # [C3] where the given values are: a "values" object, or (#53's flat shape) every key that isn't a setting.
    raw_values: dict[str, Any] = {}
    if "values" in calculation:
        if not isinstance(calculation["values"], dict):
            return None, "The calculation's values must be an object: {input name: number}."
        raw_values = calculation["values"]
        # In this shape, no other keys are allowed next to the four settings.
        for key in calculation:
            if key not in NOT_VALUE_KEYS:
                return None, "Unexpected key '" + str(key) + "' next to values in the calculation."
    else:
        for key in calculation:
            if key not in NOT_VALUE_KEYS:
                raw_values[key] = calculation[key]
    if len(raw_values) == 0:
        return None, "The calculation gives no values."

    # [C4] every value must be a number, or a list of numbers.
    values: dict[str, Any] = {}
    for name in raw_values:
        value, problem = read_value(str(name), raw_values[name])
        if problem is not None:
            return None, problem
        values[str(name)] = value

    # [C5] what the question asks for. Only a one-way formula may leave it out (its result is fixed).
    find: Any = calculation.get("find")
    if find is None or find == "":
        if formula not in ONE_WAY_RESULTS:
            return None, "The calculation must say which quantity the question asks for (find)."
        find = ONE_WAY_RESULTS[formula]
    if not isinstance(find, str):
        return None, "find must be the name of the quantity the question asks for."

    # [C6] the unit of the distances (optics only); missing or empty means none.
    length_unit: Any = calculation.get("length_unit")
    if length_unit == "":
        length_unit = None
    if length_unit is not None and not isinstance(length_unit, str):
        return None, "length_unit must be text, for example \"cm\"."

    # [R] the calculation, read.
    return {"formula": formula, "values": values, "find": find.strip(), "length_unit": length_unit}, None


# ---------------------------------------------------------------------------
# Checks against the question text
# ---------------------------------------------------------------------------


def numbers_to_find(values: dict[str, Any]) -> list[tuple[str, float]]:
    """[V2] Every given number with its input name; each item of a list counts on its own."""
    numbers: list[tuple[str, float]] = []
    for name in values:
        value: Any = values[name]
        if isinstance(value, list):
            for item in value:
                numbers.append((name, float(item)))
        else:
            numbers.append((name, float(value)))
    return numbers


def number_is_written(number: float, quantities: list[dict[str, Any]]) -> bool:
    """[V3] True if some number in the text has the same size, ignoring the sign: as written, or in SI units."""
    for quantity in quantities:
        # The number as the text writes it ("30" in "30 cm") and its SI value (0.3 m).
        for key in ("read_number", "value"):
            seen: Any = quantity.get(key)
            if is_plain_number(seen):
                if math.isclose(abs(float(seen)), abs(number), rel_tol=SAME_NUMBER_TOLERANCE, abs_tol=1e-12):
                    return True
    return False


def given_values_problem(question_text: str, values: dict[str, Any]) -> str | None:
    """[V1]-[V4] Every given number must be written in the question text (P2-5); None if they all are.

    Otherwise the solver would compute a right key for numbers the student never sees.
    """
    # Flowchart:
    #
    #   [V1] the numbers in the text (policy.find_quantities: each with its written number and its SI value)
    #   [V2] the given numbers (each item of a list on its own)
    #   [V3] each given number: some text number of the same size (ignoring the sign), as written or in SI?
    #   [V4] the first one that isn't -> "u = -25 is not in the question"; all found -> None

    # [V1] the numbers in the question.
    quantities: list[dict[str, Any]] = policy.find_quantities(question_text)
    # [V2] + [V3] + [V4] look for each given number.
    for name, number in numbers_to_find(values):
        if not number_is_written(number, quantities):
            return "The given value " + name + " = " + format(number, "g") + " is not in the question text."
    return None


def sign_problem(question_text: str, formula: str, values: dict[str, Any]) -> str | None:
    """[S1]-[S3] P2-13: a "concave" question needs a negative f (radius, power), a "convex" one a positive one.

    The sign is never flipped (code changing the model's numbers silently would hide a bad draft); the draft is
    refused instead. A text that names both kinds, or neither, is not checked.
    """
    # Flowchart:
    #
    #   [S1] a formula with a sign rule (mirror, lens, radius, lens power)?   no -> None
    #   [S2] the text says exactly one of "concave" / "convex"?               no -> None
    #   [S3] each signed input given: concave -> must be < 0; convex -> must be > 0   wrong -> problem

    # [S1] only these formulas have a sign that follows from the words.
    if formula not in SIGN_CHECKED_INPUTS:
        return None
    # [S2] which word the question uses.
    lowered: str = question_text.lower()
    has_concave: bool = "concave" in lowered
    has_convex: bool = "convex" in lowered
    if has_concave == has_convex:
        return None
    # [S3] each signed input the model gave.
    for name in SIGN_CHECKED_INPUTS[formula]:
        if name in values and is_plain_number(values[name]):
            value: float = float(values[name])
            if has_concave and value > 0:
                return ("The question is about a concave mirror or lens, so " + name + " must be negative "
                        "(New Cartesian sign convention), but " + name + " = " + format(value, "g") + " was given.")
            if has_convex and value < 0:
                return ("The question is about a convex mirror or lens, so " + name + " must be positive "
                        "(New Cartesian sign convention), but " + name + " = " + format(value, "g") + " was given.")
    return None


# ---------------------------------------------------------------------------
# The solver and the key
# ---------------------------------------------------------------------------


def run_solver(formula: str, values: dict[str, Any], length_unit: str | None) -> dict[str, Any]:
    """[K2] + [K4] Call math-tools' solve_optics or solve_electricity in-process (decision I3).

    These are the MCP tool functions themselves (the decorator returns the plain function), so PR-3 can wrap each
    call with tool_hooks.run_tool. Their own checks run inside (names, signs, zero, "at infinity").
    """
    try:
        # [K2] the catalogue that knows this formula.
        if formula in math_tools_server.OPTICS_FORMULAS:
            result: Any = math_tools_server.solve_optics(formula, values, length_unit)
        elif formula in math_tools_server.ELECTRICITY_FORMULAS:
            result = math_tools_server.solve_electricity(formula, values)
        else:
            return {"ok": False, "error": "Unknown formula '" + formula + "'. Use a name from the formula list."}
    except Exception as error:  # the tools catch their own errors; this guards an unexpected input type
        return {"ok": False, "error": "The solver could not run (" + type(error).__name__ + ")."}
    # [K4] a result must be a dict; a copy, so later changes can't reach the solver's own data.
    if not isinstance(result, dict):
        return {"ok": False, "error": "The solver gave no result."}
    return dict(result)


def format_number(value: float) -> str:
    """A number as a short key: 6 significant digits, so float noise goes (-59.999999999999986 -> "-60")."""
    return format(value, ".6g")


def format_answer_key(result: dict[str, Any]) -> str:
    """[F1]-[F3] The solver's result as an answer key the grader can read: "-60 cm", "2.4 ohm", "-2"."""
    value: Any = result.get("value")
    unit: Any = result.get("unit")
    # [F1] a text result (the image's nature) is the key itself.
    if isinstance(value, str):
        return value.strip()
    # [F2] a number with no unit (magnification, refractive index) is the bare number.
    number: str = format_number(float(value))
    if not isinstance(unit, str) or unit.strip() == "" or unit == "no unit":
        return number
    # [F3] otherwise the number, a space and the unit.
    return number + " " + unit.strip()


def solve_answer_key(question_text: str, calculation: Any) -> dict[str, Any]:
    """[K1]-[K6] The answer key for one question, computed by the solver from the model's calculation.

    Returns {"ok": True, "gold_answer", "formula", "solved_for"} or {"ok": False, "error"}. Never raises.
    """
    # Flowchart (each [box] matches a comment below):
    #
    #   [K1] READ   read_calculation: formula, values, find, length_unit         problem -> [E]
    #   [K2] WHICH  the formula is in the optics or the electricity catalogue?   no -> [E]
    #   [K3] TEXT   every given number is written in the question?               no -> [E]
    #        SIGN   "concave"/"convex" agree with the sign of f / R / P?          no -> [E]
    #   [K4] SOLVE  solve_optics / solve_electricity (their own checks inside)   ok False -> [E], its message
    #   [K5] ASKED  find == the quantity the solver solved for (ignoring case)?  no -> [E]
    #   [K6] KEY    "value unit"; the grader can read it (answer_key_problem)?   no -> [E]
    #   [R]  {"ok": True, "gold_answer", "formula", "solved_for"}
    #   [E]  {"ok": False, "error": what was wrong}

    # The question text must be there: the checks below read it.
    if not isinstance(question_text, str) or question_text.strip() == "":
        return {"ok": False, "error": "The draft has no question text."}

    # [K1] read the calculation.
    calc, problem = read_calculation(calculation)
    if calc is None:
        return {"ok": False, "error": "The calculation can't be used: " + str(problem)}
    formula: str = calc["formula"]

    # [K2] the formula must be in one of the two catalogues.
    known: bool = formula in math_tools_server.OPTICS_FORMULAS or formula in math_tools_server.ELECTRICITY_FORMULAS
    if not known:
        return {"ok": False, "error": "Unknown formula '" + formula + "'. Use a name from the formula list."}

    # [K3] every given number must be in the question text (P2-5).
    text_problem: str | None = given_values_problem(question_text, calc["values"])
    if text_problem is not None:
        return {"ok": False, "error": text_problem}
    # [K3] the sign of f, the radius or the power must agree with "concave"/"convex" (P2-13).
    signs: str | None = sign_problem(question_text, formula, calc["values"])
    if signs is not None:
        return {"ok": False, "error": signs}

    # [K4] the solver computes the answer.
    result: dict[str, Any] = run_solver(formula, calc["values"], calc["length_unit"])
    if result.get("ok") is not True:
        return {"ok": False, "error": "The solver refused this calculation: " + str(result.get("error", ""))}

    # [K5] it must have solved for what the question asks (e.g. not v for a magnification question).
    solved_for: str = str(result.get("solved_for", ""))
    if calc["find"].lower() != solved_for.lower():
        return {"ok": False, "error": ("The question asks for " + calc["find"] + ", but with these values the "
                                       + formula + " solver works out " + solved_for + ".")}

    # [K6] the key, written so the grader's code can read it. A refusal names only the unit, never the key.
    key: str = format_answer_key(result)
    key_problem: str | None = answer_key_problem(key)
    if key_problem is not None:
        return {"ok": False, "error": ("The solver's answer is in '" + str(result.get("unit", "")) + "', which "
                                       "the grader can't read, so this question can't be set.")}

    # [R] the solver's key.
    return {"ok": True, "gold_answer": key, "formula": formula, "solved_for": solved_for}


# ---------------------------------------------------------------------------
# From the model's reply to a draft for the approval gate
# ---------------------------------------------------------------------------


def draft_from_model_reply(chosen_concept: str, chosen_difficulty: str, model_reply: Any) -> dict[str, Any]:
    """[D1]-[D5] One model reply -> one draft for approval_gate.propose_set, with the solver's key.

    Returns {"ok": True, "draft": {concept_id, difficulty, prompt, gold_answer}, "formula"} or {"ok": False, "error"}.
    The concept and difficulty come from the REQUEST; the model's own key, concept and difficulty are never read.
    """
    # Flowchart:
    #
    #   [D1] a JSON object without an "error" key?                  no -> [E]
    #   [D2] question_text: non-empty text?                         no -> [E]
    #   [D3] a calculation?                                         no -> [E] (P2-4: numeric questions only)
    #   [D4] solve_answer_key(question_text, calculation)           error -> [E]
    #   [D5] the draft, built by CODE (concept and difficulty from the request; the key from the solver)

    # [D1] the reply must be a JSON object, and not llm.chat_json's error result.
    if not isinstance(model_reply, dict):
        return {"ok": False, "error": "The model's reply was not a JSON object."}
    if "error" in model_reply:
        return {"ok": False, "error": "The model call failed: " + str(model_reply.get("error"))[:MAX_ERROR_TEXT]}

    # [D2] the question itself.
    question_text: Any = model_reply.get("question_text")
    if not isinstance(question_text, str) or question_text.strip() == "":
        return {"ok": False, "error": "The model's reply has no question_text."}

    # [D3] the calculation; without one the solver can't compute a key, so the draft is refused (P2-4).
    calculation: Any = model_reply.get("calculation")
    if calculation is None:
        return {"ok": False, "error": "The solver can't compute a key without a calculation (numeric questions only)."}

    # [D4] the solver's key.
    solved: dict[str, Any] = solve_answer_key(question_text.strip(), calculation)
    if solved.get("ok") is not True:
        return {"ok": False, "error": str(solved.get("error", ""))}

    # [D5] the draft, with exactly approval_gate.DRAFT_FIELDS.
    draft: dict[str, Any] = {
        "concept_id": chosen_concept,
        "difficulty": chosen_difficulty,
        "prompt": question_text.strip(),
        "gold_answer": solved["gold_answer"],
    }
    return {"ok": True, "draft": draft, "formula": solved["formula"]}


def difficulty_plan(count: int) -> list[str]:
    """[N1] The difficulty of each draft: easy, medium, hard, then round again. [] if count isn't 1-MAX_DRAFTS."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > MAX_DRAFTS:
        return []
    plan: list[str] = []
    for position in range(count):
        plan.append(DIFFICULTY_ORDER[position % len(DIFFICULTY_ORDER)])
    return plan


def drafts_for_concept(
    chosen_concept: str,
    count: int,
    ask_model: Callable[[str, str], Any],
) -> dict[str, Any]:
    """[N1]-[N2] Ask the model once per draft, and key each draft with the solver.

    ask_model(concept_id, difficulty) is passed in by the graph node (question_setter.select_question), so this
    module never imports the agent module (no import cycle), and tests can pass a fake.
    Returns {"drafts": [draft, ...], "refused": [{"draft": n, "difficulty", "error"}, ...]}.
    """
    # Flowchart:
    #
    #   [N1] the difficulties: easy, medium, hard, then round again        count not 1-5 -> no drafts
    #   [N2] for each one: ONE model call -> draft_from_model_reply
    #        ok -> drafts; not ok -> refused, with its difficulty and why
    #   [R]  {"drafts", "refused"}

    drafts: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    # [N1] which difficulties to ask for.
    plan: list[str] = difficulty_plan(count)
    if len(plan) == 0:
        refused.append({"draft": 0, "difficulty": "", "error": "Ask for 1 to " + str(MAX_DRAFTS) + " questions."})
        return {"drafts": drafts, "refused": refused}
    # [N2] one model call per draft; one bad reply fails alone.
    for position, chosen_difficulty in enumerate(plan):
        try:
            model_reply: Any = ask_model(chosen_concept, chosen_difficulty)
        except Exception as error:  # a model or network failure is a refused draft, not a crash
            model_reply = {"error": type(error).__name__}
        made: dict[str, Any] = draft_from_model_reply(chosen_concept, chosen_difficulty, model_reply)
        if made.get("ok") is True:
            drafts.append(made["draft"])
        else:
            refused.append({"draft": position, "difficulty": chosen_difficulty, "error": str(made.get("error", ""))})
    return {"drafts": drafts, "refused": refused}
