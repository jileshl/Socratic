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


# ---------------------------------------------------------------------------
# Unit conversion. Every solver works in SI units only, so a value given in other units
# (mm, cm, minutes, mA, kWh, ...) is converted here first, by code, not by the model.
# ---------------------------------------------------------------------------

# Unit symbols, matched EXACTLY as written, because capital letters change the meaning:
# "mA" is milliampere, while "MA" would be megaampere (not accepted).
# Each entry: symbol -> (kind of quantity, its SI unit, how many SI units one of this unit is).
UNIT_SYMBOLS: dict[str, tuple[str, str, float]] = {
    # length
    "m": ("length", "m", 1.0),
    "cm": ("length", "m", 0.01),
    "mm": ("length", "m", 0.001),
    "km": ("length", "m", 1000.0),
    # area
    "m^2": ("area", "m^2", 1.0),
    "cm^2": ("area", "m^2", 0.0001),
    "mm^2": ("area", "m^2", 0.000001),
    # time
    "s": ("time", "s", 1.0),
    "min": ("time", "s", 60.0),
    "h": ("time", "s", 3600.0),
    # current ("µA" with the micro sign and "μA" with the Greek letter mu look alike, so both are listed)
    "A": ("current", "A", 1.0),
    "mA": ("current", "A", 0.001),
    "uA": ("current", "A", 0.000001),
    "µA": ("current", "A", 0.000001),
    "μA": ("current", "A", 0.000001),
    # potential difference
    "V": ("potential difference", "V", 1.0),
    "kV": ("potential difference", "V", 1000.0),
    "mV": ("potential difference", "V", 0.001),
    # resistance
    "ohm": ("resistance", "ohm", 1.0),
    "Ω": ("resistance", "ohm", 1.0),
    "kohm": ("resistance", "ohm", 1000.0),
    "kΩ": ("resistance", "ohm", 1000.0),
    # charge
    "C": ("charge", "C", 1.0),
    # energy (NCERT Ch 11, section 11.8: 1 kW h = 3.6 x 10^6 J)
    "J": ("energy", "J", 1.0),
    "kJ": ("energy", "J", 1000.0),
    "kWh": ("energy", "J", 3600000.0),
    "kW h": ("energy", "J", 3600000.0),
    # power
    "W": ("power", "W", 1.0),
    "kW": ("power", "W", 1000.0),
}

# The same units written as WORDS. Words have no capital-letter meaning ("Minutes" = "minutes"),
# so they are matched in lower case. Each word points to its symbol in UNIT_SYMBOLS.
UNIT_WORDS: dict[str, str] = {
    "metre": "m", "metres": "m", "meter": "m", "meters": "m",
    "centimetre": "cm", "centimetres": "cm", "centimeter": "cm", "centimeters": "cm",
    "millimetre": "mm", "millimetres": "mm", "millimeter": "mm", "millimeters": "mm",
    "kilometre": "km", "kilometres": "km", "kilometer": "km", "kilometers": "km",
    "square metre": "m^2", "square metres": "m^2", "square meter": "m^2", "square meters": "m^2",
    "square centimetre": "cm^2", "square centimetres": "cm^2",
    "square centimeter": "cm^2", "square centimeters": "cm^2",
    "square millimetre": "mm^2", "square millimetres": "mm^2",
    "square millimeter": "mm^2", "square millimeters": "mm^2",
    "second": "s", "seconds": "s", "sec": "s", "secs": "s",
    "minute": "min", "minutes": "min", "min": "min", "mins": "min",
    "hour": "h", "hours": "h", "hr": "h", "hrs": "h",
    "ampere": "A", "amperes": "A", "amp": "A", "amps": "A",
    "milliampere": "mA", "milliamperes": "mA", "milliamp": "mA", "milliamps": "mA",
    "microampere": "uA", "microamperes": "uA",
    "volt": "V", "volts": "V",
    "kilovolt": "kV", "kilovolts": "kV",
    "millivolt": "mV", "millivolts": "mV",
    "ohm": "ohm", "ohms": "ohm",
    "kilohm": "kohm", "kilohms": "kohm",
    "coulomb": "C", "coulombs": "C",
    "joule": "J", "joules": "J",
    "kilojoule": "kJ", "kilojoules": "kJ",
    "kilowatt hour": "kWh", "kilowatt hours": "kWh", "kilowatt-hour": "kWh", "kilowatt-hours": "kWh",
    "watt": "W", "watts": "W",
    "kilowatt": "kW", "kilowatts": "kW",
}


def known_units_text() -> str:
    """List every accepted unit symbol in one line, for error messages."""
    # Collect the symbols one by one so the message shows exactly what is accepted.
    symbols: list[str] = []
    for symbol in UNIT_SYMBOLS:
        symbols.append(symbol)
    return ", ".join(symbols)


def convert_to_si(value: float, unit: str) -> dict[str, Any]:
    """Convert a value to its SI unit, for example 0.3 mm -> 0.0003 m, or 10 min -> 600 s.

    Call this before any solver whenever a value is not already in SI units.
    unit is a symbol such as "mm", "cm", "min", "mA", "kWh" (capital letters matter: "mA" is
    milliampere), or a word such as "millimetre", "minutes" or "ohms" (any capitals).
    Negative values are converted too, because optics uses signed distances (u = -30 cm).
    Returns the shared result shape (solved_for is the kind of quantity, e.g. "length"), or the error shape.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] is the unit a known SYMBOL, written exactly?    yes -> [B-C]
    #          | no
    #          v
    #   [S2] is it a known WORD (compared in lower case)?    no -> [E] error
    #          | yes: turn the word into its symbol
    #          v
    #   [B-C] look up kind, SI unit and factor; si_value = value x factor
    #          |
    #          v
    #   [R] make_result(kind, si_value, si_unit, "1 <symbol> = <factor> <SI unit>")
    #
    # There is no "greater than 0" check: negative values must convert too.

    # Remove spaces around the unit, for example " mm " -> "mm".
    cleaned_unit = unit.strip()
    symbol: str | None = None

    # [S1] a symbol must match exactly, capital letters included.
    if cleaned_unit in UNIT_SYMBOLS:
        symbol = cleaned_unit
    else:
        # [S2] a word is compared in lower case, then turned into its symbol.
        lower_unit = cleaned_unit.lower()
        if lower_unit in UNIT_WORDS:
            symbol = UNIT_WORDS[lower_unit]

    # [E] not a known symbol or word.
    if symbol is None:
        return make_error("Unknown unit '" + unit + "'. Known unit symbols: " + known_units_text() + ".")

    # [B-C] look up what this unit is, then multiply by its factor.
    kind, si_unit, factor = UNIT_SYMBOLS[symbol]
    si_value = value * factor

    # [R]
    return make_result(kind, si_value, si_unit, "1 " + symbol + " = " + str(factor) + " " + si_unit)


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
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly two of q, i, t given?     no -> [E] error
    #          | yes
    #          v
    #   [S2] every given value greater than 0? no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |                  |                  |
    #          | q missing        | i missing        | t missing
    #          v                  v                  v
    #   [B-Q] q = i * t    [B-I] i = q / t    [B-t] t = q / i
    #          |                  |                  |
    #          v                  v                  v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S1] exactly two of the three values must be given.
    if count_given([q, i, t]) != 2:
        return make_error("Give exactly two of Q (coulomb), I (ampere) and t (second), and leave the third empty.")

    # [S2] every given value must be greater than 0.
    # This one check also rules out dividing by zero, so the branches below need no checks of their own.
    bad_name = find_zero_or_negative(["Charge Q", "Current I", "Time t"], [q, i, t])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if q is None:
        # [B-Q] Q is missing.
        charge = i * t
        return make_result("Q", charge, "C", "Q = I x t")

    if i is None:
        # [B-I] I is missing.
        current = q / t
        return make_result("I", current, "A", "I = Q / t")

    # [B-t] The only case left is that t is missing.
    time_taken = q / i
    return make_result("t", time_taken, "s", "t = Q / I")


def solve_voltage_work_charge(v: float | None = None, w: float | None = None, q: float | None = None) -> dict[str, Any]:
    """Potential difference: V = W / Q (NCERT Class 10 Science, Ch 11, Eq. 11.2).

    Give exactly two of the three values and leave the third as None; the missing one is calculated.
    Units are SI: v in volt (V), w (work done) in joule (J), q (charge) in coulomb (C).
    1 volt means 1 joule of work done to move 1 coulomb of charge.
    Every given value must be greater than 0.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly two of v, w, q given?     no -> [E] error
    #          | yes
    #          v
    #   [S2] every given value greater than 0? no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |                  |                  |
    #          | v missing        | w missing        | q missing
    #          v                  v                  v
    #   [B-V] v = w / q    [B-W] w = v * q    [B-Q] q = w / v
    #          |                  |                  |
    #          v                  v                  v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S1] exactly two of the three values must be given.
    if count_given([v, w, q]) != 2:
        return make_error("Give exactly two of V (volt), W (joule) and Q (coulomb), and leave the third empty.")

    # [S2] every given value must be greater than 0.
    # This one check also rules out dividing by zero, so the branches below need no checks of their own.
    bad_name = find_zero_or_negative(["Potential difference V", "Work done W", "Charge Q"], [v, w, q])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if v is None:
        # [B-V] V is missing.
        voltage = w / q
        return make_result("V", voltage, "V", "V = W / Q")

    if w is None:
        # [B-W] W is missing.
        work_done = v * q
        return make_result("W", work_done, "J", "W = V x Q")

    # [B-Q] The only case left is that Q is missing.
    charge = w / v
    return make_result("Q", charge, "C", "Q = W / V")


def solve_ohms_law(v: float | None = None, i: float | None = None, r: float | None = None) -> dict[str, Any]:
    """Ohm's law: V = I x R (NCERT Class 10 Science, Ch 11, Eq. 11.5-11.7).

    Give exactly two of the three values and leave the third as None; the missing one is calculated.
    Units are SI: v in volt (V), i in ampere (A), r in ohm.
    Ohm's law holds while the temperature of the conductor stays the same.
    Every given value must be greater than 0.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly two of v, i, r given?     no -> [E] error
    #          | yes
    #          v
    #   [S2] every given value greater than 0? no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |                  |                  |
    #          | v missing        | i missing        | r missing
    #          v                  v                  v
    #   [B-V] v = i * r    [B-I] i = v / r    [B-R] r = v / i
    #          |                  |                  |
    #          v                  v                  v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S1] exactly two of the three values must be given.
    if count_given([v, i, r]) != 2:
        return make_error("Give exactly two of V (volt), I (ampere) and R (ohm), and leave the third empty.")

    # [S2] every given value must be greater than 0.
    # This one check also rules out dividing by zero, so the branches below need no checks of their own.
    bad_name = find_zero_or_negative(["Potential difference V", "Current I", "Resistance R"], [v, i, r])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if v is None:
        # [B-V] V is missing.
        voltage = i * r
        return make_result("V", voltage, "V", "V = I x R")

    if i is None:
        # [B-I] I is missing.
        current = v / r
        return make_result("I", current, "A", "I = V / R")

    # [B-R] The only case left is that R is missing.
    resistance = v / i
    return make_result("R", resistance, "ohm", "R = V / I")


def solve_resistivity(
    r: float | None = None,
    rho: float | None = None,
    length: float | None = None,
    area: float | None = None,
) -> dict[str, Any]:
    """Resistance of a wire: R = rho x length / area (NCERT Class 10 Science, Ch 11, Eq. 11.10).

    Give exactly three of the four values and leave the fourth as None; the missing one is calculated.
    Units are SI: r in ohm, rho (resistivity of the material) in ohm metre, length in metre (m),
    area (cross-sectional area) in square metre (m^2). Convert mm to m first.
    If the wire's diameter or radius is given, get its area from wire_area first.
    Every given value must be greater than 0.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly three of r, rho, length, area given?   no -> [E] error
    #          | yes
    #          v
    #   [S2] every given value greater than 0?              no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |                |                 |                  |
    #          | r missing      | rho missing     | length missing   | area missing
    #          v                v                 v                  v
    #   [B-R] r = rho x    [B-RHO] rho = r x  [B-L] length = r x [B-A] area = rho x
    #         length/area        area/length        area/rho           length/r
    #          |                |                 |                  |
    #          v                v                 v                  v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S1] exactly three of the four values must be given.
    if count_given([r, rho, length, area]) != 3:
        return make_error(
            "Give exactly three of R (ohm), rho (ohm metre), length (metre) and area (square metre), "
            "and leave the fourth empty."
        )

    # [S2] every given value must be greater than 0.
    # This one check also rules out dividing by zero, so the branches below need no checks of their own.
    bad_name = find_zero_or_negative(["Resistance R", "Resistivity rho", "Length", "Area"], [r, rho, length, area])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if r is None:
        # [B-R] R is missing.
        resistance = rho * length / area
        return make_result("R", resistance, "ohm", "R = rho x length / area")

    if rho is None:
        # [B-RHO] rho is missing.
        resistivity = r * area / length
        return make_result("rho", resistivity, "ohm m", "rho = R x area / length")

    if length is None:
        # [B-L] length is missing.
        wire_length = r * area / rho
        return make_result("length", wire_length, "m", "length = R x area / rho")

    # [B-A] The only case left is that area is missing.
    wire_area = rho * length / r
    return make_result("area", wire_area, "m^2", "area = rho x length / R")


def wire_area(diameter: float | None = None, radius: float | None = None) -> dict[str, Any]:
    """Cross-sectional area of a round wire, from its diameter or its radius (NCERT Class 10 Science, Ch 11, Example 11.5).

    Give exactly one of diameter or radius, in metre (m). Convert mm to m first (0.3 mm = 0.0003 m).
    From a diameter: A = pi x d^2 / 4. From a radius: A = pi x r^2.
    The value given must be greater than 0.
    Returns the shared result shape (area in square metre), or the error shape.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly one of diameter, radius given?   no -> [E] error
    #          | yes
    #          v
    #   [S2] that value greater than 0?               no -> [E] error
    #          | yes
    #          v
    #   [S3] which one was given?
    #          |                              |
    #          | diameter given               | radius given
    #          v                              v
    #   [B-D] area = pi x d x d / 4    [B-RAD] area = pi x radius x radius
    #          |                              |
    #          v                              v
    #   [R] make_result("area", area, "m^2", formula)

    # [S1] exactly one of the two must be given: a diameter or a radius, not both.
    if count_given([diameter, radius]) != 1:
        return make_error("Give exactly one of diameter (metre) or radius (metre), not both.")

    # [S2] the value given must be greater than 0.
    bad_name = find_zero_or_negative(["Diameter d", "Radius"], [diameter, radius])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [S3] use the formula that matches what was given.
    if diameter is not None:
        # [B-D] the cut face is a circle of radius d / 2, so A = pi x (d / 2)^2 = pi x d^2 / 4.
        area = math.pi * diameter * diameter / 4
        return make_result("area", area, "m^2", "A = pi x d^2 / 4")

    # [B-RAD] the only case left is that the radius was given: A = pi x r^2.
    area = math.pi * radius * radius
    return make_result("area", area, "m^2", "A = pi x r^2")


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

