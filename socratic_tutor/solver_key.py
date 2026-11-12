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
from socratic_tutor.tools import math_tools, math_tools_server
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
# The optics inputs that are distances, given in the calculation's length_unit (for the formulas that take one).
DISTANCE_INPUTS: list[str] = ["u", "v", "f", "radius_of_curvature", "h_object", "h_image"]
# The SI unit (as math_tools.read_quantity writes it) of each optics input that isn't a distance; "none" = no unit.
OPTICS_INPUT_UNITS: dict[str, str] = {
    "p": "D", "powers": "D", "v1": "m/s", "v2": "m/s",
    "m": "none", "n": "none", "n21": "none", "n1": "none", "n2": "none",
}
# In these formulas "v" is the speed of light in the medium (m/s), not an image distance.
SPEED_INPUT_FORMULAS: list[str] = ["absolute_refractive_index"]
# The SI unit of each electricity input (every electricity value is given in SI units). Inputs whose unit the
# reader doesn't know ("ohm m", "Rs per kW h") are left out, so only their size is compared.
ELECTRICITY_INPUT_UNITS: dict[str, str] = {
    "q": "C", "i": "A", "t": "s", "v": "V", "w": "J", "r": "ohm", "length": "m", "area": "m^2",
    "diameter": "m", "radius": "m", "resistors": "ohm", "h": "J", "p": "W", "energy": "J", "cost": "Rs",
}
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
    # NaN and infinity can't be a given value of a school question. A JSON integer too big for a float
    # (e.g. 10**400) makes isfinite raise OverflowError: that isn't a plain number either.
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def catalogue_name(raw_formula: str) -> str:
    """The catalogue name for a formula the model wrote: lowercase, no surrounding spaces, aliases mapped."""
    # Lowercase, without surrounding spaces ("Mirror " -> "mirror").
    name: str = raw_formula.strip().lower()
    # A short name maps to its catalogue name; any other name is returned as it is (and checked at [K2]).
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
    # Anything else (text, a bool, an empty list, an object) can't be given to the solver.
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
        # The flat shape: every key that isn't formula / find / length_unit is a given value.
        for key in calculation:
            if key not in NOT_VALUE_KEYS:
                raw_values[key] = calculation[key]
    # A calculation must give at least one value.
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


def needs_length_unit(formula: str) -> bool:
    """True for the optics formulas whose distances are given in a length_unit (mirror, lens, heights, power)."""
    if formula not in math_tools_server.OPTICS_FORMULAS:
        return False
    return bool(math_tools_server.OPTICS_FORMULAS[formula].get("needs_length_unit", False))


def expected_unit(formula: str, name: str) -> str | None:
    """The SI unit a given input's number has ("m", "A", "D", "none" for no unit), as read_quantity writes it;
    None when the reader doesn't know that unit (then only the size is compared)."""
    # Electricity: every value is given in SI units.
    if formula in math_tools_server.ELECTRICITY_FORMULAS:
        if name in ELECTRICITY_INPUT_UNITS:
            return ELECTRICITY_INPUT_UNITS[name]
        return None
    # Optics: "v" is a speed in the refractive-index formulas, and a distance where a length_unit is given.
    if formula in SPEED_INPUT_FORMULAS and name == "v":
        return "m/s"
    if name in DISTANCE_INPUTS and needs_length_unit(formula):
        return "m"
    if name in OPTICS_INPUT_UNITS:
        return OPTICS_INPUT_UNITS[name]
    return None


def length_factor(length_unit: Any) -> float | None:
    """How many metres one length_unit is (cm -> 0.01, m -> 1), or None if it isn't a known length unit."""
    if not isinstance(length_unit, str):
        return None
    converted: dict[str, Any] = math_tools.convert_to_si(1.0, length_unit)
    if converted.get("ok") is not True or converted.get("unit") != "m":
        return None
    return float(converted["value"])


def given_numbers(
    formula: str, values: dict[str, Any], length_unit: str | None,
) -> tuple[list[tuple[str, float, float, str | None]], str | None]:
    """[V2] Every given number as (input name, the number as given, its SI value, its SI unit), or a problem.

    An optics distance is converted with length_unit (u = -30 in "cm" is -0.3 m); every other value is already
    in SI units. Each item of a list (resistors, powers) counts on its own.
    """
    numbers: list[tuple[str, float, float, str | None]] = []
    # The metres in one length_unit, worked out once (only distances need it).
    factor: float | None = None
    for name in values:
        unit: str | None = expected_unit(formula, name)
        scale: float = 1.0
        if unit == "m" and needs_length_unit(formula):
            if factor is None:
                factor = length_factor(length_unit)
            if factor is None:
                return [], "The calculation needs length_unit, the unit of the distances (for example \"cm\")."
            scale = factor
        # A list value gives one number per item.
        items: list[Any] = []
        if isinstance(values[name], list):
            items = values[name]
        else:
            items = [values[name]]
        for item in items:
            numbers.append((name, float(item), float(item) * scale, unit))
    return numbers, None


def number_is_written(si_value: float, si_unit: str | None, quantities: list[dict[str, Any]]) -> bool:
    """[V3] True if some number in the text has this SI size (ignoring the sign) and, when the text gives it a
    unit, this SI unit: "500 mA" is 0.5 A, so it matches i = 0.5 and never i = 500."""
    for quantity in quantities:
        seen: Any = quantity.get("value")
        if not is_plain_number(seen):
            continue
        # The size, in SI units on both sides.
        if not math.isclose(abs(float(seen)), abs(si_value), rel_tol=SAME_NUMBER_TOLERANCE, abs_tol=1e-12):
            continue
        # A bare number in the text counts; a number with a unit must be the same kind of quantity.
        seen_unit: Any = quantity.get("unit")
        if seen_unit == "none" or si_unit is None or seen_unit == si_unit:
            return True
    return False


def given_values_problem(
    question_text: str, formula: str, values: dict[str, Any], length_unit: str | None,
) -> tuple[str | None, list[float]]:
    """[V1]-[V4] Every given number must be written in the question text, with the same unit (P2-5).

    Returns (None, the given numbers' SI sizes) when they all are, else (the problem, []). Otherwise the solver
    would compute a right key for numbers the student never sees, or for the wrong unit (500 mA read as 500 A).
    """
    # Flowchart:
    #
    #   [V1] the numbers in the text (policy.find_quantities: each with its SI value and SI unit)
    #   [V2] the given numbers in SI (distances converted with length_unit; lists item by item)
    #   [V3] each given number: a text number of the same SI size (ignoring the sign) and the same kind?
    #   [V4] the first one that isn't -> "u = -25 is not in the question"; all found -> (None, the SI sizes)

    # [V1] the numbers in the question.
    quantities: list[dict[str, Any]] = policy.find_quantities(question_text)
    # [V2] the given numbers, in SI units.
    numbers, problem = given_numbers(formula, values, length_unit)
    if problem is not None:
        return problem, []
    # [V3] + [V4] look for each given number.
    sizes: list[float] = []
    for name, as_given, si_value, si_unit in numbers:
        if not number_is_written(si_value, si_unit, quantities):
            return ("The given value " + name + " = " + format(as_given, "g") + " is not in the question text "
                    "(with that unit)."), []
        sizes.append(abs(si_value))
    return None, sizes


def answer_in_text_problem(question_text: str, key: str, given_sizes: list[float]) -> str | None:
    """[K7] The question text must not already give the answer ("Find v (it is 60 cm)"); None if it doesn't.

    A key equal to a given value is fine (an object at the centre of curvature has v = u), so it isn't checked.
    """
    # A text key (the image's nature) can't be compared as a number.
    key_quantity: dict[str, Any] = math_tools.read_quantity(key)
    if key_quantity.get("ok") is not True:
        return None
    key_size: float = abs(float(key_quantity["value"]))
    # The answer may equal a given number: then its number in the text is the given one, not a give-away.
    for size in given_sizes:
        if math.isclose(size, key_size, rel_tol=SAME_NUMBER_TOLERANCE, abs_tol=1e-12):
            return None
    # Any number in the text of the same kind and size as the answer gives it away.
    for quantity in policy.find_quantities(question_text):
        if policy.same_kind_and_size(key_quantity, quantity):
            return "The question text already gives away the answer, so this question can't be set."
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
    # Not a number either: no key (answer_key_problem refuses the empty text, so nothing raises here).
    if not is_plain_number(value):
        return ""
    # [F2] a number with no unit (magnification, refractive index) is the bare number.
    number: str = format_number(float(value))
    if not isinstance(unit, str) or unit.strip() == "" or unit == "no unit":
        return number
    # [F3] otherwise the number, a space and the unit.
    return number + " " + unit.strip()


def solve_answer_key(question_text: str, calculation: Any) -> dict[str, Any]:
    """[K1]-[K7] The answer key for one question, computed by the solver from the model's calculation.

    Returns {"ok": True, "gold_answer", "formula", "solved_for"} or {"ok": False, "error"}. Never raises.
    """
    # Flowchart (each [box] matches a comment below):
    #
    #   [K1] READ   read_calculation: formula, values, find, length_unit         problem -> [E]
    #   [K2] WHICH  the formula is in the optics or the electricity catalogue?   no -> [E]
    #   [K3] TEXT   every given number is written in the question, same unit?    no -> [E]
    #        SIGN   "concave"/"convex" agree with the sign of f / R / P?          no -> [E]
    #   [K4] SOLVE  solve_optics / solve_electricity (their own checks inside)   ok False -> [E], its message
    #   [K5] ASKED  find == the quantity the solver solved for (ignoring case)?  no -> [E]
    #   [K6] KEY    "value unit"; the grader can read it (answer_key_problem)?   no -> [E]
    #   [K7] SECRET the question text doesn't already give the answer?          no -> [E]
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

    # [K3] every given number must be in the question text, with the same unit (P2-5).
    text_problem, given_sizes = given_values_problem(question_text, formula, calc["values"], calc["length_unit"])
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

    # [K7] the question must not give the answer away (the prompt asks the model not to; code checks it).
    give_away: str | None = answer_in_text_problem(question_text, key, given_sizes)
    if give_away is not None:
        return {"ok": False, "error": give_away}

    # [R] the solver's key.
    return {"ok": True, "gold_answer": key, "formula": formula, "solved_for": solved_for}


# ---------------------------------------------------------------------------
# From the model's reply to a draft for the approval gate
# ---------------------------------------------------------------------------


def draft_from_model_reply(chosen_concept: str, chosen_difficulty: str, model_reply: Any) -> dict[str, Any]:
    """[D1]-[D5] One model reply -> one draft for approval_gate.propose_set, with the solver's key.

    Returns {"ok": True, "draft": {concept_id, difficulty, prompt, gold_answer}, "formula", "fallback"} or
    {"ok": False, "error"}. "fallback" is True when the reply is one of the agent's fixed fallback questions
    (question_setter.select_question marks them with source "fallback"), so the teacher can be told.
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
    # Whether this was a fixed fallback question rather than the model's own.
    is_fallback: bool = model_reply.get("source") == "fallback"
    return {"ok": True, "draft": draft, "formula": solved["formula"], "fallback": is_fallback}


def difficulty_plan(count: int) -> list[str]:
    """[N1] The difficulty of each draft: easy, medium, hard, then round again. [] if count isn't 1-MAX_DRAFTS."""
    # Only a whole number from 1 to MAX_DRAFTS (a bool is an int in Python, so it is refused first).
    if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > MAX_DRAFTS:
        return []
    # Position 0 -> easy, 1 -> medium, 2 -> hard, 3 -> easy again, ...
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
    Returns {"drafts": [draft, ...], "refused": [{"draft": n, "difficulty", "error"}, ...], "fallback_count": n}
    (fallback_count: how many drafts are the agent's fixed fallback questions, not the model's own).
    """
    # Flowchart:
    #
    #   [N1] the difficulties: easy, medium, hard, then round again        count not 1-5 -> no drafts
    #   [N2] for each one: ONE model call -> draft_from_model_reply (any crash = that draft refused)
    #        ok -> drafts; not ok -> refused, with its difficulty and why
    #   [R]  {"drafts", "refused", "fallback_count"}

    # The keyed drafts, the refusals, and how many drafts are fixed fallback questions.
    drafts: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    fallback_count: int = 0
    # [N1] which difficulties to ask for.
    plan: list[str] = difficulty_plan(count)
    if len(plan) == 0:
        refused.append({"draft": 0, "difficulty": "", "error": "Ask for 1 to " + str(MAX_DRAFTS) + " questions."})
        return {"drafts": drafts, "refused": refused, "fallback_count": fallback_count}
    # [N2] one model call per draft; one bad reply fails alone.
    for position, chosen_difficulty in enumerate(plan):
        try:
            model_reply: Any = ask_model(chosen_concept, chosen_difficulty)
            made: dict[str, Any] = draft_from_model_reply(chosen_concept, chosen_difficulty, model_reply)
        except Exception as error:  # a model, network or unexpected-input failure is a refused draft, not a crash
            made = {"ok": False, "error": "The draft could not be made (" + type(error).__name__ + ")."}
        if made.get("ok") is True:
            drafts.append(made["draft"])
            if made.get("fallback") is True:
                fallback_count = fallback_count + 1
        else:
            refused.append({"draft": position, "difficulty": chosen_difficulty, "error": str(made.get("error", ""))})
    # [R] what was made.
    return {"drafts": drafts, "refused": refused, "fallback_count": fallback_count}
