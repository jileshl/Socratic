"""FastMCP Tool Server: math-tools (solve, check equivalence, numeric check with tolerance)."""

import math
from typing import Any


# ---------------------------------------------------------------------------
# Shared helpers, used by every calculator function.
# Every function returns one of two shapes, so callers can treat all answers
# the same way:
#   success: {"ok": True, "solved_for": ..., "value": ..., "unit": ..., "formula": ...}
#   error:   {"ok": False, "error": "<what was wrong, in plain words>"}
# ---------------------------------------------------------------------------


def make_result(quantity_name: str, exact_value: float, si_unit: str, formula_used: str) -> dict[str, Any]:
    """Build the success shape: the quantity found, its exact value, its SI unit and the formula used."""
    # "ok" lets the caller check for success with one True/False test.
    result: dict[str, Any] = {"ok": True}
    # Which quantity was calculated, for example "I".
    result["solved_for"] = quantity_name
    # The exact value. It is never rounded here: rounding is only for display.
    result["value"] = exact_value
    # The SI unit, so nobody has to guess, for example "A".
    result["unit"] = si_unit
    # The rule that was used, so the model can explain the step to the student.
    result["formula"] = formula_used
    return result


def make_error(message: str) -> dict[str, Any]:
    """Build the error shape: ok is False, and 'error' says what was wrong in plain words."""
    # The key is called "error" so the existing tests that check `"error" in res` keep working.
    return {"ok": False, "error": message}


def count_given(values: list[float | None]) -> int:
    """Count how many of the values were actually provided (that is, are not None)."""
    # Start at zero and add one for every value that is present.
    count = 0
    for value in values:
        if value is not None:
            count = count + 1
    return count


def find_zero_or_negative(names: list[str], values: list[float | None]) -> str | None:
    """Return the name of the first given value that is 0 or negative, or None if every given value is positive.

    In Class 10 numericals every given quantity is a positive size. A 0 would make the formula
    meaningless or force a division by zero, so 0 is rejected together with negative values.
    """
    # names[k] describes values[k], so walk both lists by position.
    for position in range(len(values)):
        value = values[position]
        # A missing value (None) is skipped: only given values are checked.
        if value is not None and value <= 0:
            return names[position]
    # Every given value is greater than 0.
    return None


def solve_mirror_formula(u: float, f: float) -> dict[str, Any]:
    """Solve mirror formula 1/f = 1/v + 1/u -> 1/v = 1/f - 1/u.
    
    All quantities in centimeters with proper Cartesian signs.
    """
    try:
        # 1/v = (u - f) / (f * u)
        denominator = u - f
        if abs(denominator) < 1e-9:
            return {"error": "Object is at focal point; image forms at infinity."}
        v = (f * u) / denominator
        m = -v / u
        return {
            "v": round(v, 2),
            "m": round(m, 2),
            "nature": "real and inverted" if v < 0 else "virtual and erect"
        }
    except Exception as e:
        return {"error": str(e)}


def numeric_check(student_val: float, gold_val: float, tolerance: float = 0.05) -> bool:
    """Verify if student value matches gold value within relative tolerance percentage."""
    if gold_val == 0:
        return abs(student_val) < 1e-6
    return abs(student_val - gold_val) / abs(gold_val) <= tolerance


# TODO (Milestone 3.2 / L7): Solve Lens formula: 1/f = 1/v - 1/u and power P = 1/f
def solve_lens_formula(u: float, f: float) -> dict[str, Any]:
    """Solve lens formula 1/f = 1/v - 1/u -> 1/v = 1/f + 1/u.
    
    All quantities in centimeters with proper Cartesian signs.
    """
    try:
        denominator = u + f
        if abs(denominator) < 1e-9:
            return {"error": "Object is at focal point; image forms at infinity."}
        v = (f * u) / denominator
        m = v / u
        return {
            "v": round(v, 2),
            "m": round(m, 2),
            "nature": "real and inverted" if v > 0 else "virtual and erect"
        }
    except Exception as e:
        return {"error": str(e)}


def solve_charge_current(q: float | None = None, i: float | None = None, t: float | None = None) -> dict[str, Any]:
    """Electric current: I = Q / t (NCERT Class 10 Science, Ch 11, Eq. 11.1).

    Give exactly two of the three values and leave the third as None; the missing one is calculated.
    Units are SI: q in coulomb (C), i in ampere (A), t in second (s). Convert minutes to seconds first.
    Every given value must be greater than 0.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Step 1: exactly two of the three values must be given.
    if count_given([q, i, t]) != 2:
        return make_error("Give exactly two of Q (coulomb), I (ampere) and t (second), and leave the third empty.")

    # Step 2: every given value must be greater than 0.
    # This one check also rules out dividing by zero, so the branches below need no checks of their own.
    bad_name = find_zero_or_negative(["Charge Q", "Current I", "Time t"], [q, i, t])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # Step 3: calculate whichever value is missing, exactly (no rounding).
    if q is None:
        charge = i * t
        return make_result("Q", charge, "C", "Q = I x t")

    if i is None:
        current = q / t
        return make_result("I", current, "A", "I = Q / t")

    # The only case left is that t is missing.
    time_taken = q / i
    return make_result("t", time_taken, "s", "t = Q / I")


def solve_ohms_law(v: float | None = None, i: float | None = None, r: float | None = None) -> dict[str, Any]:
    """Ohm's law: V = I x R (NCERT Class 10 Science, Ch 11, Eq. 11.5-11.7).

    Give exactly two of the three values and leave the third as None; the missing one is calculated.
    Units are SI: v in volt (V), i in ampere (A), r in ohm.
    Ohm's law holds while the temperature of the conductor stays the same.
    Every given value must be greater than 0.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Step 1: exactly two of the three values must be given.
    if count_given([v, i, r]) != 2:
        return make_error("Give exactly two of V (volt), I (ampere) and R (ohm), and leave the third empty.")

    # Step 2: every given value must be greater than 0.
    # This one check also rules out dividing by zero, so the branches below need no checks of their own.
    bad_name = find_zero_or_negative(["Potential difference V", "Current I", "Resistance R"], [v, i, r])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # Step 3: calculate whichever value is missing, exactly (no rounding).
    if v is None:
        voltage = i * r
        return make_result("V", voltage, "V", "V = I x R")

    if i is None:
        current = v / r
        return make_result("I", current, "A", "I = V / R")

    # The only case left is that R is missing.
    resistance = v / i
    return make_result("R", resistance, "ohm", "R = V / I")


# TODO (Milestone 3.4 / L7): Solve Equivalent Resistance in Series and Parallel
def solve_equivalent_resistance(resistors: list[float], mode: str = "series") -> dict[str, Any]:
    """Compute equivalent resistance for resistors in 'series' or 'parallel'."""
    if not resistors:
        return {"error": "Resistor list cannot be empty"}
    if mode == "series":
        return {"req": round(sum(resistors), 2)}
    elif mode == "parallel":
        if any(r <= 0 for r in resistors):
            return {"error": "Resistances must be positive"}
        inv_sum = sum(1.0 / r for r in resistors)
        return {"req": round(1.0 / inv_sum, 2)}
    return {"error": f"Unknown mode: {mode}"}

