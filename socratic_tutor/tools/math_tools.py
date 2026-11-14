"""Calculator functions for the math-tools MCP server (served by math_tools_server.py): solve, check equivalence, numeric check with tolerance."""

import ast
import math
import re
import string
from typing import Any

# SymPy reads formulas for check_equivalence. It is listed in requirements.txt, so it is imported here at the top.
from sympy import Eq, Float, Integer, Rational, Symbol, simplify, solve, sqrt
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication,
    parse_expr,
    split_symbols_custom,
    standard_transformations,
)


# ---------------------------------------------------------------------------
# Shared helpers, used by every calculator function.
# Every function returns one of two shapes, so callers can treat all answers
# the same way:
#   success: {"ok": True, "solved_for": ..., "value": ..., "unit": ..., "formula": ...}
#   error:   {"ok": False, "error": "<what was wrong, in plain words>"}
# ---------------------------------------------------------------------------


def make_result(quantity_name: str, exact_value: float | str | bool, result_unit: str, formula_used: str) -> dict[str, Any]:
    """Build the success shape: the quantity found, its exact value, its unit and the formula used.

    The value is a number, except for describe_image, whose value is a description such as "real and inverted, enlarged",
    and for the answer checks, whose value is True or False.
    The unit is SI, except in the optics functions, which answer in the length unit the caller chose (for example cm).
    """
    # "ok" lets the caller check for success with one True/False test.
    result: dict[str, Any] = {"ok": True}
    # Which quantity was calculated, for example "I".
    result["solved_for"] = quantity_name
    # The exact value. It is never rounded here: rounding is only for display.
    result["value"] = exact_value
    # The unit, so nobody has to guess, for example "A".
    result["unit"] = result_unit
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

    In Class 10 electricity numericals every given quantity is a positive size. A 0 would make the formula
    meaningless or force a division by zero, so 0 is rejected together with negative values.
    (Optics distances carry signs, so the optics functions use find_zero instead.)
    """
    # names[k] describes values[k], so walk both lists by position.
    for position in range(len(values)):
        value = values[position]
        # A missing value (None) is skipped: only given values are checked.
        if value is not None and value <= 0:
            return names[position]
    # Every given value is greater than 0.
    return None


def find_zero(names: list[str], values: list[float | None]) -> str | None:
    """Return the name of the first given value that is exactly 0, or None if no given value is 0.

    Used by the optics functions, where negative values are normal (u = -25 cm) but 0 would
    force a division by zero.
    """
    # names[k] describes values[k], so walk both lists by position.
    for position in range(len(values)):
        value = values[position]
        # A missing value (None) is skipped: only given values are checked.
        if value is not None and value == 0:
            return names[position]
    # No given value is 0.
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
    # speed (NCERT Ch 9 writes the speed of light as 3 x 10^8 m s^-1)
    "m/s": ("speed", "m/s", 1.0),
    "m s^-1": ("speed", "m/s", 1.0),
    "km/s": ("speed", "m/s", 1000.0),
    "cm/s": ("speed", "m/s", 0.01),
    "km/h": ("speed", "m/s", 1000.0 / 3600.0),
    # power of a lens (NCERT Ch 9, section 9.3.8: 1 D = 1 m^-1, already the SI unit)
    "D": ("lens power", "D", 1.0),
    # money (NCERT Ch 11, Example 11.13: Rs 3.00 per kW h). Not an SI quantity; listed so answers such as
    # "Rs 288" can be read by read_quantity.
    "Rs": ("money", "Rs", 1.0),
    "₹": ("money", "Rs", 1.0),
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
    "metre per second": "m/s", "metres per second": "m/s", "meter per second": "m/s", "meters per second": "m/s",
    "kilometre per second": "km/s", "kilometres per second": "km/s",
    "kilometer per second": "km/s", "kilometers per second": "km/s",
    "kilometre per hour": "km/h", "kilometres per hour": "km/h",
    "kilometer per hour": "km/h", "kilometers per hour": "km/h",
    "dioptre": "D", "dioptres": "D", "diopter": "D", "diopters": "D",
    "rupee": "Rs", "rupees": "Rs",
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


def find_unit_symbol(unit: str) -> str | None:
    """Return the table symbol for a unit written as a symbol ("cm") or a word ("centimetres"), or None if unknown.

    The same matching rules as convert_to_si: a symbol must match exactly, a word matches in any capitals.
    """
    # Remove spaces around the unit, for example " cm " -> "cm".
    cleaned_unit = unit.strip()
    # A symbol must match exactly, capital letters included.
    if cleaned_unit in UNIT_SYMBOLS:
        return cleaned_unit
    # A word is compared in lower case, then turned into its symbol.
    lower_unit = cleaned_unit.lower()
    if lower_unit in UNIT_WORDS:
        return UNIT_WORDS[lower_unit]
    # Not a known unit.
    return None


def convert_from_si(si_value: float, unit: str) -> dict[str, Any]:
    """Convert a value in SI units back into another unit: 3.456 x 10^8 J -> 96 kWh, or -0.3 m -> -30 cm.

    The reverse of convert_to_si. si_value must already be in the SI unit of its kind (m, s, A, V, ohm, C, J, W, m/s).
    unit is the unit wanted, written as a symbol ("kWh", "cm") or a word ("kilowatt hours").
    Use it to show an SI answer in the unit a question asks for, for example energy on a bill in kW h.
    Returns the shared result shape (solved_for is the kind of quantity), or the error shape.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] is the unit a known symbol or word?    no -> [E] error
    #          | yes
    #          v
    #   [B-C] look up kind, SI unit and factor; value = si_value / factor
    #          |
    #          v
    #   [R] make_result(kind, value, symbol, "1 <symbol> = <factor> <SI unit>")

    # [S1] find the unit in the table.
    symbol = find_unit_symbol(unit)
    if symbol is None:
        return make_error("Unknown unit '" + unit + "'. Known unit symbols: " + known_units_text() + ".")

    # [B-C] divide by the factor: the reverse of convert_to_si's multiply.
    kind, si_unit, factor = UNIT_SYMBOLS[symbol]
    value = si_value / factor

    # [R]
    return make_result(kind, value, symbol, "1 " + symbol + " = " + str(factor) + " " + si_unit)


def find_length_unit(length_unit: str) -> str | None:
    """Return the symbol of a length unit, such as "cm" or "m", or None if the text is not a length unit.

    The same matching rules as convert_to_si: a symbol must match exactly (capital letters matter),
    and a word such as "centimetres" matches in any capitals.
    """
    # Remove spaces around the unit, for example " cm " -> "cm".
    cleaned_unit = length_unit.strip()
    symbol: str | None = None

    # A symbol must match exactly, capital letters included.
    if cleaned_unit in UNIT_SYMBOLS:
        symbol = cleaned_unit
    else:
        # A word is compared in lower case, then turned into its symbol.
        lower_unit = cleaned_unit.lower()
        if lower_unit in UNIT_WORDS:
            symbol = UNIT_WORDS[lower_unit]

    # Not a known unit at all.
    if symbol is None:
        return None

    # A known unit, but it must measure a length (cm is fine, s or kg is not).
    kind = UNIT_SYMBOLS[symbol][0]
    if kind != "length":
        return None
    return symbol


# ---------------------------------------------------------------------------
# Optics (NCERT Ch 9): mirrors and lenses.
# Distances carry signs (New Cartesian sign convention), so these functions do NOT use
# find_zero_or_negative. Their checks are: u must be negative (the object is on the left),
# and no value may be 0 (the formulas divide by every value).
# They take a length_unit ("cm", "m", ...) because NCERT works optics in cm. All distances
# are in that one unit, and so is the answer; the formulas give the same image in any length unit.
# ---------------------------------------------------------------------------


def solve_mirror_formula(
    length_unit: str,
    u: float | None = None,
    v: float | None = None,
    f: float | None = None,
) -> dict[str, Any]:
    """Mirror formula: 1/v + 1/u = 1/f (NCERT Class 10 Science, Ch 9, Eq. 9.1).

    Give exactly two of u, v, f and leave the third as None; the missing one is calculated.
    length_unit is the unit of u, v and f, for example "cm" or "m"; the answer is in the same unit.
    Use the New Cartesian sign convention (section 9.2.3): distances are measured from the pole;
    in front of the mirror (to the left) is negative, behind it (to the right) is positive.
    The object is always in front, so u is negative. A concave mirror has f negative; a convex mirror has f positive.
    The answer v is negative for an image in front of the mirror (real) and positive for one behind it (virtual).
    If only the radius of curvature R is known, get f from focal_length_from_radius first.
    For the magnification and the image's nature, use solve_mirror_magnification and describe_image.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S0] length_unit is a length unit (cm, m, mm, km)?   no -> [E] error
    #          | yes
    #          v
    #   [S1] exactly two of u, v, f given?                   no -> [E] error
    #          | yes
    #          v
    #   [S2] no given value is 0, and u (if given) < 0?      no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |
    #          +-- v missing -> [B-V] bracket = 1/f - 1/u
    #          |                [Z] bracket == 0?  yes -> [INF] object at the focus: image at infinity
    #          |                v = 1 / bracket
    #          |
    #          +-- u missing -> [B-U] bracket = 1/f - 1/v
    #          |                [Z] bracket == 0?  yes -> [INF] image at the focus: object at infinity
    #          |                u = 1 / bracket
    #          |                [C-U] u < 0?       no  -> [E] no real object gives this image
    #          |
    #          +-- f missing -> [B-F] bracket = 1/v + 1/u
    #          |                [Z] bracket == 0?  yes -> [INF] v = -u: a plane mirror, no focal length
    #          |                f = 1 / bracket
    #          v
    #   [R] make_result(quantity, exact value, length unit, formula)

    # [S0] the unit must be a length unit from the unit table.
    unit_symbol = find_length_unit(length_unit)
    if unit_symbol is None:
        return make_error("length_unit must be a length unit such as cm, m or mm, not '" + length_unit + "'.")

    # [S1] exactly two of the three values must be given.
    if count_given([u, v, f]) != 2:
        return make_error("Give exactly two of u, v and f (in " + unit_symbol + "), and leave the third empty.")

    # [S2] no given value may be 0, because the formula divides by u, v and f.
    zero_name = find_zero(["Object distance u", "Image distance v", "Focal length f"], [u, v, f])
    if zero_name is not None:
        return make_error(zero_name + " cannot be 0.")

    # [S2] u must be negative: the object is always in front of the mirror (NCERT sign convention).
    # A positive u is refused, not quietly flipped, so the caller notices the slip and fixes its call.
    if u is not None and u > 0:
        return make_error(
            "Object distance u must be negative: the object is always in front of (to the left of) the mirror "
            "(NCERT sign convention). Did you mean u = " + str(-u) + "?"
        )

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if v is None:
        # [B-V] v is missing: 1/v = 1/f - 1/u.
        bracket = 1 / f - 1 / u
        # [Z] a bracket of 0 means 1/v = 0: the object is at the focus.
        if bracket == 0:
            # [INF] a real physical case, so the message says what happens.
            return make_error("The object is at the focus (u = f), so the image forms at infinity: there is no finite v.")
        image_distance = 1 / bracket
        return make_result("v", image_distance, unit_symbol, "v = 1 / (1/f - 1/u)")

    if u is None:
        # [B-U] u is missing: 1/u = 1/f - 1/v.
        bracket = 1 / f - 1 / v
        # [Z] a bracket of 0 means 1/u = 0: the image is at the focus.
        if bracket == 0:
            # [INF]
            return make_error("The image is at the focus (v = f), so the object is at infinity: there is no finite u.")
        object_distance = 1 / bracket
        # [C-U] a calculated u must be negative too, or no real object can give this image.
        if object_distance > 0:
            return make_error(
                "No real object gives this image with this mirror: the calculated u = " + str(object_distance)
                + " is positive, but a real object has u < 0. Check the signs of v and f."
            )
        return make_result("u", object_distance, unit_symbol, "u = 1 / (1/f - 1/v)")

    # [B-F] The only case left is that f is missing: 1/f = 1/v + 1/u.
    bracket = 1 / v + 1 / u
    # [Z] a bracket of 0 means v = -u: the image is as far behind the mirror as the object is in front.
    if bracket == 0:
        # [INF]
        return make_error("v = -u, so 1/f = 0: that is a plane mirror, which has no focal length.")
    focal_length = 1 / bracket
    return make_result("f", focal_length, unit_symbol, "f = 1 / (1/v + 1/u)")


def solve_lens_formula(
    length_unit: str,
    u: float | None = None,
    v: float | None = None,
    f: float | None = None,
) -> dict[str, Any]:
    """Lens formula: 1/v - 1/u = 1/f (NCERT Class 10 Science, Ch 9, Eq. 9.8).

    Give exactly two of u, v, f and leave the third as None; the missing one is calculated.
    length_unit is the unit of u, v and f, for example "cm" or "m"; the answer is in the same unit.
    Use the New Cartesian sign convention: distances are measured from the optical centre;
    to the left is negative, to the right is positive. The object is always on the left, so u is negative.
    A convex (converging) lens has f positive; a concave (diverging) lens has f negative (section 9.3.6).
    The answer v is positive for an image on the other side of the lens (real) and negative for one on the
    same side as the object (virtual). This is the opposite of a mirror, so never use the mirror formula here.
    For the magnification and the image's nature, use solve_lens_magnification and describe_image.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S0] length_unit is a length unit (cm, m, mm, km)?   no -> [E] error
    #          | yes
    #          v
    #   [S1] exactly two of u, v, f given?                   no -> [E] error
    #          | yes
    #          v
    #   [S2] no given value is 0, and u (if given) < 0?      no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |
    #          +-- v missing -> [B-V] bracket = 1/f + 1/u
    #          |                [Z] bracket == 0?  yes -> [INF] object at the focus: image at infinity
    #          |                v = 1 / bracket
    #          |
    #          +-- u missing -> [B-U] bracket = 1/v - 1/f
    #          |                [Z] bracket == 0?  yes -> [INF] image at the focus: object at infinity
    #          |                u = 1 / bracket
    #          |                [C-U] u < 0?       no  -> [E] no real object gives this image
    #          |
    #          +-- f missing -> [B-F] bracket = 1/v - 1/u
    #          |                [Z] bracket == 0?  yes -> [INF] v = u: no lens, no focal length
    #          |                f = 1 / bracket
    #          v
    #   [R] make_result(quantity, exact value, length unit, formula)

    # [S0] the unit must be a length unit from the unit table.
    unit_symbol = find_length_unit(length_unit)
    if unit_symbol is None:
        return make_error("length_unit must be a length unit such as cm, m or mm, not '" + length_unit + "'.")

    # [S1] exactly two of the three values must be given.
    if count_given([u, v, f]) != 2:
        return make_error("Give exactly two of u, v and f (in " + unit_symbol + "), and leave the third empty.")

    # [S2] no given value may be 0, because the formula divides by u, v and f.
    zero_name = find_zero(["Object distance u", "Image distance v", "Focal length f"], [u, v, f])
    if zero_name is not None:
        return make_error(zero_name + " cannot be 0.")

    # [S2] u must be negative: the object is always on the left of the lens (NCERT sign convention).
    # A positive u is refused, not quietly flipped, so the caller notices the slip and fixes its call.
    if u is not None and u > 0:
        return make_error(
            "Object distance u must be negative: the object is always on the left of the lens "
            "(NCERT sign convention). Did you mean u = " + str(-u) + "?"
        )

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if v is None:
        # [B-V] v is missing: 1/v = 1/f + 1/u.
        bracket = 1 / f + 1 / u
        # [Z] a bracket of 0 means 1/v = 0: the object is at the focus.
        if bracket == 0:
            # [INF] a real physical case, so the message says what happens.
            return make_error("The object is at the focus (u = -f), so the image forms at infinity: there is no finite v.")
        image_distance = 1 / bracket
        return make_result("v", image_distance, unit_symbol, "v = 1 / (1/f + 1/u)")

    if u is None:
        # [B-U] u is missing: 1/u = 1/v - 1/f.
        bracket = 1 / v - 1 / f
        # [Z] a bracket of 0 means 1/u = 0: the image is at the focus.
        if bracket == 0:
            # [INF]
            return make_error("The image is at the focus (v = f), so the object is at infinity: there is no finite u.")
        object_distance = 1 / bracket
        # [C-U] a calculated u must be negative too, or no real object can give this image.
        if object_distance > 0:
            return make_error(
                "No real object gives this image with this lens: the calculated u = " + str(object_distance)
                + " is positive, but a real object has u < 0. Check the signs of v and f."
            )
        return make_result("u", object_distance, unit_symbol, "u = 1 / (1/v - 1/f)")

    # [B-F] The only case left is that f is missing: 1/f = 1/v - 1/u.
    bracket = 1 / v - 1 / u
    # [Z] a bracket of 0 means v = u: the image is exactly where the object is.
    if bracket == 0:
        # [INF]
        return make_error("v = u, so 1/f = 0: the image is where the object is, so there is no lens (no focal length).")
    focal_length = 1 / bracket
    return make_result("f", focal_length, unit_symbol, "f = 1 / (1/v - 1/u)")


def focal_length_from_radius(length_unit: str, radius_of_curvature: float) -> dict[str, Any]:
    """Focal length of a spherical mirror from its radius of curvature: f = R / 2 (NCERT Class 10 Science, Ch 9, section 9.2).

    radius_of_curvature (R) is in length_unit, for example "cm" or "m"; the answer f is in the same unit.
    R is the radius of the sphere the mirror is a part of (from the pole to the centre of curvature).
    It is NOT half the mirror's width: the mirror's diameter is its aperture, which does not give R or f.
    Keep the sign: a concave mirror has R (and f) negative; a convex mirror has R (and f) positive.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S0] length_unit is a length unit?   no -> [E] error
    #          | yes
    #          v
    #   [S2] R is not 0?                     no -> [E] error
    #          | yes
    #          v
    #   [B-F] f = R / 2, keeping the sign of R
    #          |
    #          v
    #   [R] make_result("f", f, length unit, "f = R / 2")

    # [S0] the unit must be a length unit from the unit table.
    unit_symbol = find_length_unit(length_unit)
    if unit_symbol is None:
        return make_error("length_unit must be a length unit such as cm, m or mm, not '" + length_unit + "'.")

    # [S2] a radius of 0 is not a mirror.
    if radius_of_curvature == 0:
        return make_error("Radius of curvature R cannot be 0.")

    # [B-F] halve R; the sign stays, so a concave mirror's f stays negative.
    focal_length = radius_of_curvature / 2

    # [R]
    return make_result("f", focal_length, unit_symbol, "f = R / 2")


def solve_mirror_magnification(
    length_unit: str,
    m: float | None = None,
    v: float | None = None,
    u: float | None = None,
) -> dict[str, Any]:
    """Magnification of a mirror from the distances: m = -v / u (NCERT Class 10 Science, Ch 9, Eq. 9.3).

    Give exactly two of m, v, u and leave the third as None; the missing one is calculated.
    length_unit is the unit of v and u (and of the answer when v or u is found); m has no unit.
    Signs follow the New Cartesian sign convention, so u is negative.
    m is negative for a real, inverted image and positive for a virtual, erect image.
    So "a real image three times the size of the object" means m = -3.
    For the image's height use solve_image_height; for its nature use describe_image.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S0] length_unit is a length unit?                   no -> [E] error
    #          | yes
    #          v
    #   [S1] exactly two of m, v, u given?                   no -> [E] error
    #          | yes
    #          v
    #   [S2] no given value is 0, and u (if given) < 0?      no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |
    #          +-- m missing -> [B-M] m = -v / u
    #          +-- v missing -> [B-V] v = -m * u
    #          +-- u missing -> [B-U] u = -v / m,  then [C-U] u < 0?  no -> [E] no real object fits
    #          |
    #          v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S0] the unit must be a length unit from the unit table.
    unit_symbol = find_length_unit(length_unit)
    if unit_symbol is None:
        return make_error("length_unit must be a length unit such as cm, m or mm, not '" + length_unit + "'.")

    # [S1] exactly two of the three values must be given.
    if count_given([m, v, u]) != 2:
        return make_error("Give exactly two of m, v and u (v and u in " + unit_symbol + "), and leave the third empty.")

    # [S2] no given value may be 0 (m = 0 or v = 0 means no image; u = 0 would divide by zero).
    zero_name = find_zero(["Magnification m", "Image distance v", "Object distance u"], [m, v, u])
    if zero_name is not None:
        return make_error(zero_name + " cannot be 0.")

    # [S2] u must be negative: the object is always in front of the mirror (NCERT sign convention).
    if u is not None and u > 0:
        return make_error(
            "Object distance u must be negative: the object is always in front of (to the left of) the mirror "
            "(NCERT sign convention). Did you mean u = " + str(-u) + "?"
        )

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if m is None:
        # [B-M] m is missing.
        magnification = -v / u
        return make_result("m", magnification, "no unit", "m = -v / u")

    if v is None:
        # [B-V] v is missing.
        image_distance = -m * u
        return make_result("v", image_distance, unit_symbol, "v = -m x u")

    # [B-U] The only case left is that u is missing.
    object_distance = -v / m
    # [C-U] a calculated u must be negative too, or no real object fits these values.
    if object_distance > 0:
        return make_error(
            "No real object fits: the calculated u = " + str(object_distance)
            + " is positive, but a real object has u < 0. Check the sign of m (a real image has m < 0) and of v."
        )
    return make_result("u", object_distance, unit_symbol, "u = -v / m")


def solve_lens_magnification(
    length_unit: str,
    m: float | None = None,
    v: float | None = None,
    u: float | None = None,
) -> dict[str, Any]:
    """Magnification of a lens from the distances: m = v / u (NCERT Class 10 Science, Ch 9, Eq. 9.10).

    Give exactly two of m, v, u and leave the third as None; the missing one is calculated.
    length_unit is the unit of v and u (and of the answer when v or u is found); m has no unit.
    Signs follow the New Cartesian sign convention, so u is negative. There is no minus sign here,
    unlike the mirror's m = -v / u.
    m is negative for a real, inverted image and positive for a virtual, erect image.
    For the image's height use solve_image_height; for its nature use describe_image.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S0] length_unit is a length unit?                   no -> [E] error
    #          | yes
    #          v
    #   [S1] exactly two of m, v, u given?                   no -> [E] error
    #          | yes
    #          v
    #   [S2] no given value is 0, and u (if given) < 0?      no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |
    #          +-- m missing -> [B-M] m = v / u
    #          +-- v missing -> [B-V] v = m * u
    #          +-- u missing -> [B-U] u = v / m,  then [C-U] u < 0?  no -> [E] no real object fits
    #          |
    #          v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S0] the unit must be a length unit from the unit table.
    unit_symbol = find_length_unit(length_unit)
    if unit_symbol is None:
        return make_error("length_unit must be a length unit such as cm, m or mm, not '" + length_unit + "'.")

    # [S1] exactly two of the three values must be given.
    if count_given([m, v, u]) != 2:
        return make_error("Give exactly two of m, v and u (v and u in " + unit_symbol + "), and leave the third empty.")

    # [S2] no given value may be 0 (m = 0 or v = 0 means no image; u = 0 would divide by zero).
    zero_name = find_zero(["Magnification m", "Image distance v", "Object distance u"], [m, v, u])
    if zero_name is not None:
        return make_error(zero_name + " cannot be 0.")

    # [S2] u must be negative: the object is always on the left of the lens (NCERT sign convention).
    if u is not None and u > 0:
        return make_error(
            "Object distance u must be negative: the object is always on the left of the lens "
            "(NCERT sign convention). Did you mean u = " + str(-u) + "?"
        )

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if m is None:
        # [B-M] m is missing.
        magnification = v / u
        return make_result("m", magnification, "no unit", "m = v / u")

    if v is None:
        # [B-V] v is missing.
        image_distance = m * u
        return make_result("v", image_distance, unit_symbol, "v = m x u")

    # [B-U] The only case left is that u is missing.
    object_distance = v / m
    # [C-U] a calculated u must be negative too, or no real object fits these values.
    if object_distance > 0:
        return make_error(
            "No real object fits: the calculated u = " + str(object_distance)
            + " is positive, but a real object has u < 0. Check the signs: for a lens a real image has v > 0 and m < 0."
        )
    return make_result("u", object_distance, unit_symbol, "u = v / m")


def solve_image_height(
    length_unit: str,
    m: float | None = None,
    h_object: float | None = None,
    h_image: float | None = None,
) -> dict[str, Any]:
    """Magnification from the heights: m = h' / h (NCERT Class 10 Science, Ch 9, Eq. 9.2 for mirrors, Eq. 9.9 for lenses).

    The same formula works for mirrors and lenses. Give exactly two of m, h_object (h) and h_image (h'),
    and leave the third as None; the missing one is calculated.
    length_unit is the unit of the heights (and of the answer when a height is found); m has no unit.
    The object's height is taken as positive (section 9.2.4). The image's height is negative for a real,
    inverted image (below the axis) and positive for a virtual, erect image.
    Get m first from solve_mirror_magnification or solve_lens_magnification.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S0] length_unit is a length unit?                        no -> [E] error
    #          | yes
    #          v
    #   [S1] exactly two of m, h_object, h_image given?           no -> [E] error
    #          | yes
    #          v
    #   [S2] no given value is 0, and h_object (if given) > 0?    no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |
    #          +-- m missing        -> [B-M]  m = h_image / h_object
    #          +-- h_image missing  -> [B-HI] h_image = m * h_object
    #          +-- h_object missing -> [B-HO] h_object = h_image / m,  then [C-HO] h_object > 0?  no -> [E] error
    #          |
    #          v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S0] the unit must be a length unit from the unit table.
    unit_symbol = find_length_unit(length_unit)
    if unit_symbol is None:
        return make_error("length_unit must be a length unit such as cm, m or mm, not '" + length_unit + "'.")

    # [S1] exactly two of the three values must be given.
    if count_given([m, h_object, h_image]) != 2:
        return make_error(
            "Give exactly two of m, h_object and h_image (heights in " + unit_symbol + "), and leave the third empty."
        )

    # [S2] no given value may be 0 (a height of 0 is no object or no image).
    zero_name = find_zero(["Magnification m", "Object height h", "Image height h'"], [m, h_object, h_image])
    if zero_name is not None:
        return make_error(zero_name + " cannot be 0.")

    # [S2] the object's height is taken as positive (NCERT section 9.2.4).
    if h_object is not None and h_object < 0:
        return make_error("Object height h must be positive: the object stands above the principal axis (NCERT sign convention).")

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if m is None:
        # [B-M] m is missing.
        magnification = h_image / h_object
        return make_result("m", magnification, "no unit", "m = h' / h")

    if h_image is None:
        # [B-HI] the image height is missing.
        image_height = m * h_object
        return make_result("h_image", image_height, unit_symbol, "h' = m x h")

    # [B-HO] The only case left is that the object height is missing.
    object_height = h_image / m
    # [C-HO] a calculated object height must be positive too.
    if object_height < 0:
        return make_error(
            "The calculated object height h = " + str(object_height) + " is negative, but an object stands above "
            "the axis (h > 0). Check the signs: a real image has m < 0 and h' < 0."
        )
    return make_result("h_object", object_height, unit_symbol, "h = h' / m")


def describe_image(m: float) -> dict[str, Any]:
    """The nature of the image from the magnification m, for mirrors and lenses alike (NCERT Class 10 Science, Ch 9, section 9.2.4).

    m negative: real and inverted. m positive: virtual and erect.
    Size from the value of m, ignoring its sign: more than 1 is enlarged, 1 is the same size, less than 1 is diminished.
    Get m first from solve_mirror_magnification, solve_lens_magnification or solve_image_height.
    Returns the shared result shape with the description as text in "value", or the error shape if m is 0.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S2] m is not 0?                      no -> [E] error
    #          | yes
    #          v
    #   [N1] which sign does m have?
    #          |                         |
    #          | m < 0                   | m > 0
    #          v                         v
    #   [N-REAL] real and inverted   [N-VIRT] virtual and erect
    #          |                         |
    #          v                         v
    #   [N2] size from |m|: close to 1 -> same size; more than 1 -> enlarged; less than 1 -> diminished
    #          |
    #          v
    #   [R] make_result("nature", sign words + size word, "no unit", rule)

    # [S2] m = 0 would mean an image of no size at all.
    if m == 0:
        return make_error("Magnification m cannot be 0.")

    # [N1] the sign of m says real or virtual.
    if m < 0:
        # [N-REAL] a negative m: the image is real and upside down.
        kind_words = "real and inverted"
    else:
        # [N-VIRT] a positive m: the image is virtual and upright.
        kind_words = "virtual and erect"

    # [N2] the size of m, ignoring its sign, says bigger or smaller.
    size = abs(m)
    # "Close to 1" instead of "== 1", because a computed m can be 1.0000000000000002.
    if math.isclose(size, 1.0):
        size_word = "same size"
    elif size > 1:
        size_word = "enlarged"
    else:
        size_word = "diminished"

    # [R] the description is text, so "value" holds a string here.
    nature = kind_words + ", " + size_word
    return make_result("nature", nature, "no unit", "m < 0: real and inverted; m > 0: virtual and erect; |m| > 1: enlarged")


def solve_lens_power(length_unit: str, p: float | None = None, f: float | None = None) -> dict[str, Any]:
    """Power of a lens: P = 1 / f, with f in metres, gives P in dioptres (NCERT Class 10 Science, Ch 9, Eq. 9.11).

    Give exactly one of p (power, in dioptres D) and f (focal length, in length_unit) and leave the other as None.
    length_unit is the unit f is given in, or wanted in, for example "cm" or "m". The function converts f to
    metres itself, so pass f exactly as the problem states it: f = 25 cm gives P = +4 D (not 0.04).
    A convex (converging) lens has positive f and positive power; a concave (diverging) lens has negative f and power.
    Spectacles (Ch 10, section 10.2): myopia is corrected by a concave lens (negative power), and hypermetropia
    by a convex lens (positive power).
    If only u and v are known, get f from solve_lens_formula first. For lenses in contact use combine_lens_powers.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S0] length_unit is a length unit (cm, m, mm, km)?   no -> [E] error
    #          | yes
    #          v
    #   [S1] exactly one of p, f given?                      no -> [E] error
    #          | yes
    #          v
    #   [S2] the given value is not 0?                       no -> [E] error
    #          | yes
    #          v
    #   [K] metres in one length_unit, from the unit table (cm: 0.01)
    #          |
    #          v
    #   [S3] which one is missing?
    #          |                                  |
    #          | p missing                        | f missing
    #          v                                  v
    #   [B-P] f in metres = f * factor     [B-F] f in metres = 1 / p
    #         p = 1 / (f in metres)              f = (f in metres) / factor
    #          |                                  |
    #          v                                  v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S0] the unit of f must be a length unit from the unit table.
    unit_symbol = find_length_unit(length_unit)
    if unit_symbol is None:
        return make_error("length_unit must be a length unit such as cm, m or mm, not '" + length_unit + "'.")

    # [S1] exactly one of the two values must be given.
    if count_given([p, f]) != 1:
        return make_error("Give exactly one of p (dioptre) and f (in " + unit_symbol + "), and leave the other empty.")

    # [S2] neither may be 0: P = 1 / f divides by f, and f = 1 / P divides by P.
    zero_name = find_zero(["Power P", "Focal length f"], [p, f])
    if zero_name is not None:
        return make_error(zero_name + " cannot be 0.")

    # [K] how many metres one length_unit is (cm -> 0.01), read from the unit table.
    metres_per_unit: float = UNIT_SYMBOLS[unit_symbol][2]

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if p is None:
        # [B-P] p is missing: turn f into metres first, because a dioptre is 1 / metre.
        focal_length_in_metres = f * metres_per_unit
        power = 1 / focal_length_in_metres
        return make_result("P", power, "D", "P = 1 / f (f in metres)")

    # [B-F] The only case left is that f is missing: f = 1 / P gives metres, then turn it into length_unit.
    focal_length_in_metres = 1 / p
    focal_length = focal_length_in_metres / metres_per_unit
    return make_result("f", focal_length, unit_symbol, "f = 1 / P (in metres), then converted to " + unit_symbol)


def lens_names(count: int) -> list[str]:
    """Names for a list of lenses, "Lens 1", "Lens 2", ..., used in error messages."""
    names: list[str] = []
    for number in range(1, count + 1):
        names.append("Lens " + str(number))
    return names


def combine_lens_powers(powers: list[float]) -> dict[str, Any]:
    """Lenses placed in contact: P = P1 + P2 + P3 + ... (NCERT Class 10 Science, Ch 9, section 9.3.8).

    powers is a list of at least 2 lens powers, each in dioptres (D). Keep the signs: a convex lens is positive,
    a concave lens is negative. The total is the "algebraic sum", so a concave lens lowers it.
    If a lens is given by its focal length, get its power from solve_lens_power first.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] at least 2 powers in the list?          no -> [E] error
    #          | yes
    #          v
    #   [S2] no power is 0 (negatives are fine)?     no -> [E] error
    #          | yes
    #          v
    #   [B-SUM] add up every power, keeping its sign
    #          |
    #          v
    #   [R] make_result("P", total, "D", "P = P1 + P2 + ...")

    # [S1] a combination needs at least 2 lenses.
    if len(powers) < 2:
        return make_error("Give at least 2 lens powers (in dioptres) to combine.")

    # [S2] a power of 0 is no lens at all; negative powers (concave lenses) are allowed.
    zero_name = find_zero(lens_names(len(powers)), powers)
    if zero_name is not None:
        return make_error(zero_name + " cannot have a power of 0.")

    # [B-SUM] add up the powers, signs included.
    total = 0.0
    for power in powers:
        total = total + power

    # [R]
    return make_result("P", total, "D", "P = P1 + P2 + ...")


# The speed of light in vacuum (or air), in m/s: NCERT's value, 3 x 10^8 m s^-1 (Ch 9, "What you have learnt").
SPEED_OF_LIGHT_IN_VACUUM: float = 3.0e8


def solve_absolute_refractive_index(n: float | None = None, v: float | None = None) -> dict[str, Any]:
    """Absolute refractive index of a medium: n = c / v (NCERT Class 10 Science, Ch 9, Eq. 9.7, section 9.3.2).

    Give exactly one of n and v (the speed of light in the medium, in m/s) and leave the other as None.
    c is the speed of light in vacuum or air, 3 x 10^8 m/s (NCERT's value).
    Convert other speed units, such as km/s, to m/s first with convert_to_si.
    An absolute refractive index is never less than 1, because nothing travels faster than light in vacuum.
    For one medium with respect to another, use solve_relative_refractive_index (from speeds) or
    solve_relative_index_from_absolute (from the two absolute indices).
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly one of n, v given?                      no -> [E] error
    #          | yes
    #          v
    #   [S2] the given value is greater than 0?              no -> [E] error
    #          | yes
    #          v
    #   [S2] n >= 1 and v <= c (nothing beats light)?        no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |                                  |
    #          | n missing                        | v missing
    #          v                                  v
    #   [B-N] n = c / v                    [B-V] v = c / n
    #          |                                  |
    #          v                                  v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S1] exactly one of the two values must be given.
    if count_given([n, v]) != 1:
        return make_error("Give exactly one of n and v (in m/s), and leave the other empty.")

    # [S2] both quantities are positive sizes.
    bad_name = find_zero_or_negative(["Refractive index n", "Speed of light in the medium v"], [n, v])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [S2] nothing is faster than light in vacuum, so n is at least 1 and v is at most c.
    if n is not None and n < 1:
        return make_error(
            "An absolute refractive index cannot be less than 1: light cannot travel faster than in vacuum. "
            "(A relative index can be less than 1: use solve_relative_refractive_index.)"
        )
    if v is not None and v > SPEED_OF_LIGHT_IN_VACUUM:
        return make_error("v = " + str(v) + " m/s is faster than light in vacuum (3 x 10^8 m/s), which is impossible.")

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if n is None:
        # [B-N] n is missing.
        refractive_index = SPEED_OF_LIGHT_IN_VACUUM / v
        return make_result("n", refractive_index, "no unit", "n = c / v, with c = 3 x 10^8 m/s")

    # [B-V] The only case left is that v is missing.
    speed = SPEED_OF_LIGHT_IN_VACUUM / n
    return make_result("v", speed, "m/s", "v = c / n, with c = 3 x 10^8 m/s")


def solve_relative_refractive_index(
    n21: float | None = None,
    v1: float | None = None,
    v2: float | None = None,
) -> dict[str, Any]:
    """Refractive index of medium 2 with respect to medium 1: n21 = v1 / v2 (NCERT Class 10 Science, Ch 9, Eq. 9.5).

    Light travels from medium 1 into medium 2; v1 and v2 are its speeds in them, in m/s.
    Give exactly two of n21, v1, v2 and leave the third as None; the missing one is calculated.
    For medium 1 with respect to medium 2 (n12 = v2 / v1, Eq. 9.6), swap the two media.
    A relative index can be less than 1: that happens when light goes from an optically denser medium into a rarer one.
    If the two absolute indices are known instead of the speeds, use solve_relative_index_from_absolute.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly two of n21, v1, v2 given?               no -> [E] error
    #          | yes
    #          v
    #   [S2] every given value greater than 0?               no -> [E] error
    #          | yes
    #          v
    #   [S2] every given speed at most c?                    no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |
    #          +-- n21 missing -> [B-N]  n21 = v1 / v2
    #          +-- v1 missing  -> [B-V1] v1 = n21 * v2,  then [C-V] v1 <= c?  no -> [E] error
    #          +-- v2 missing  -> [B-V2] v2 = v1 / n21,  then [C-V] v2 <= c?  no -> [E] error
    #          |
    #          v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S1] exactly two of the three values must be given.
    if count_given([n21, v1, v2]) != 2:
        return make_error("Give exactly two of n21, v1 and v2 (speeds in m/s), and leave the third empty.")

    # [S2] all three quantities are positive sizes.
    bad_name = find_zero_or_negative(["Relative refractive index n21", "Speed v1", "Speed v2"], [n21, v1, v2])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [S2] a given speed cannot be faster than light in vacuum.
    if v1 is not None and v1 > SPEED_OF_LIGHT_IN_VACUUM:
        return make_error("v1 = " + str(v1) + " m/s is faster than light in vacuum (3 x 10^8 m/s), which is impossible.")
    if v2 is not None and v2 > SPEED_OF_LIGHT_IN_VACUUM:
        return make_error("v2 = " + str(v2) + " m/s is faster than light in vacuum (3 x 10^8 m/s), which is impossible.")

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if n21 is None:
        # [B-N] n21 is missing.
        relative_index = v1 / v2
        return make_result("n21", relative_index, "no unit", "n21 = v1 / v2")

    if v1 is None:
        # [B-V1] v1 is missing.
        speed_in_medium_1 = n21 * v2
        # [C-V] a calculated speed cannot be faster than light either.
        if speed_in_medium_1 > SPEED_OF_LIGHT_IN_VACUUM:
            return make_error(
                "The calculated v1 = " + str(speed_in_medium_1) + " m/s is faster than light in vacuum, which is impossible. "
                "Check n21 and v2."
            )
        return make_result("v1", speed_in_medium_1, "m/s", "v1 = n21 x v2")

    # [B-V2] The only case left is that v2 is missing.
    speed_in_medium_2 = v1 / n21
    # [C-V] a calculated speed cannot be faster than light either.
    if speed_in_medium_2 > SPEED_OF_LIGHT_IN_VACUUM:
        return make_error(
            "The calculated v2 = " + str(speed_in_medium_2) + " m/s is faster than light in vacuum, which is impossible. "
            "Check n21 and v1."
        )
    return make_result("v2", speed_in_medium_2, "m/s", "v2 = v1 / n21")


def solve_relative_index_from_absolute(
    n21: float | None = None,
    n1: float | None = None,
    n2: float | None = None,
) -> dict[str, Any]:
    """Refractive index of medium 2 with respect to medium 1, from the two absolute indices: n21 = n2 / n1.

    This follows from NCERT Class 10 Science, Ch 9, Eq. 9.5 and 9.7: v1 = c / n1 and v2 = c / n2,
    so n21 = v1 / v2 = n2 / n1.
    n1 and n2 are absolute refractive indices (for example from Table 9.3: water 1.33, crown glass 1.52),
    so each is at least 1. Light travels from medium 1 into medium 2.
    Give exactly two of n21, n1, n2 and leave the third as None; the missing one is calculated.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly two of n21, n1, n2 given?               no -> [E] error
    #          | yes
    #          v
    #   [S2] every given value greater than 0?               no -> [E] error
    #          | yes
    #          v
    #   [S2] every given absolute index (n1, n2) at least 1? no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |
    #          +-- n21 missing -> [B-N21] n21 = n2 / n1
    #          +-- n1 missing  -> [B-N1]  n1 = n2 / n21,  then [C-N] n1 >= 1?  no -> [E] error
    #          +-- n2 missing  -> [B-N2]  n2 = n21 * n1,  then [C-N] n2 >= 1?  no -> [E] error
    #          |
    #          v
    #   [R] make_result(quantity, exact value, "no unit", formula)

    # [S1] exactly two of the three values must be given.
    if count_given([n21, n1, n2]) != 2:
        return make_error("Give exactly two of n21, n1 and n2, and leave the third empty.")

    # [S2] all three are positive.
    bad_name = find_zero_or_negative(["Relative refractive index n21", "Absolute index n1", "Absolute index n2"], [n21, n1, n2])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [S2] an absolute index is at least 1 (nothing beats light in vacuum).
    if n1 is not None and n1 < 1:
        return make_error("Absolute index n1 cannot be less than 1: light cannot travel faster than in vacuum.")
    if n2 is not None and n2 < 1:
        return make_error("Absolute index n2 cannot be less than 1: light cannot travel faster than in vacuum.")

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if n21 is None:
        # [B-N21] n21 is missing.
        relative_index = n2 / n1
        return make_result("n21", relative_index, "no unit", "n21 = n2 / n1")

    if n1 is None:
        # [B-N1] n1 is missing.
        index_1 = n2 / n21
        # [C-N] a calculated absolute index must be at least 1 too.
        if index_1 < 1:
            return make_error("The calculated n1 = " + str(index_1) + " is less than 1, which is impossible. Check n21 and n2.")
        return make_result("n1", index_1, "no unit", "n1 = n2 / n21")

    # [B-N2] The only case left is that n2 is missing.
    index_2 = n21 * n1
    # [C-N] a calculated absolute index must be at least 1 too.
    if index_2 < 1:
        return make_error("The calculated n2 = " + str(index_2) + " is less than 1, which is impossible. Check n21 and n1.")
    return make_result("n2", index_2, "no unit", "n2 = n21 x n1")


def numeric_check(student_val: float, gold_val: float, tolerance: float = 0.05) -> bool:
    """Verify if student value matches gold value within relative tolerance percentage."""
    if gold_val == 0:
        return abs(student_val) < 1e-6
    return abs(student_val - gold_val) / abs(gold_val) <= tolerance


# ---------------------------------------------------------------------------
# Answer checks, for the grader (capstone guide p.11, step 6; p.12: "check equivalence,
# numeric check with tolerance"). Student answers arrive as text, such as "-30 cm", so they are
# read by code here; the model never judges the arithmetic.
# ---------------------------------------------------------------------------

# Superscript characters, as in "10⁸" or "m s⁻¹", and the plain characters they stand for.
SUPERSCRIPT_CHARACTERS: dict[str, str] = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "⁻": "-", "⁺": "+",
}

# A number at the start of a text: an optional sign, digits with an optional decimal point, and an
# optional power of ten in e-notation. For example "-30", "+1.25", ".5", "3e8", "2.0E-3".
NUMBER_AT_START = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")


def tidy_answer_text(text: str) -> str:
    """Tidy typed answer text so a number can be read from it: "−30 cm" -> "-30 cm", "3 × 10⁸ m/s" -> "3e8 m/s"."""
    # [P0a] remove spaces at both ends.
    tidy = text.strip()
    # [P0b] the Unicode minus (−) and the en dash (–), common in text copied from a PDF, become a plain "-".
    tidy = tidy.replace("−", "-")
    tidy = tidy.replace("–", "-")
    # [P0c] thousands commas go: "96,000" -> "96000".
    tidy = tidy.replace(",", "")
    # [P0d] superscripts become "^" plus plain characters: "10⁸" -> "10^8", "s⁻¹" -> "s^-1".
    rebuilt = ""
    previous_was_superscript = False
    for character in tidy:
        if character in SUPERSCRIPT_CHARACTERS:
            # Only the first superscript of a run needs a "^" in front of it.
            if not previous_was_superscript:
                rebuilt = rebuilt + "^"
            rebuilt = rebuilt + SUPERSCRIPT_CHARACTERS[character]
            previous_was_superscript = True
        else:
            rebuilt = rebuilt + character
            previous_was_superscript = False
    tidy = rebuilt
    # [P0e] "× 10^8", "x10^8" or "*10^8" become e-notation: "3 × 10^8" -> "3e8".
    tidy = re.sub(r"\s*[x×*]\s*10\s*\^\s*([+-]?\d+)", r"e\1", tidy)
    # [P0e2] square roots: "√4", "sqrt 4", "sqrt(4)", "SQRT 4", "square root of 4", "squareroot of 4"
    def _calc_sqrt(m: re.Match[str]) -> str:
        val = float(m.group(1))
        res = math.sqrt(val)
        return f"{int(res)}" if res.is_integer() else f"{res}"
    tidy = tidy.replace("√", "sqrt ")
    tidy = re.sub(r"\b(?:sqrt|squareroot\s*(?:of)?|square\s*root\s*(?:of)?)\s*\(?\s*([0-9.]+)\s*\)?", _calc_sqrt, tidy, flags=re.IGNORECASE)
    # [P0e3] simple fractions: "1/2 A" -> "0.5 A", "3/4" -> "0.75"
    def _calc_frac(m: re.Match[str]) -> str:
        denom = float(m.group(2))
        if denom == 0:
            return m.group(0)
        return str(round(float(m.group(1)) / denom, 6))
    tidy = re.sub(r"\b(\d+)\s*/\s*(\d+)\b", _calc_frac, tidy)
    # [P0e4] word signs before numbers or expressions: "minus 0.6" -> "-0.6", "plus 2" -> "+2"
    tidy = re.sub(r"\b(?:minus|negative)\s*(?=[0-9.])", "-", tidy, flags=re.IGNORECASE)
    tidy = re.sub(r"\b(?:plus|positive)\s*(?=[0-9.])", "+", tidy, flags=re.IGNORECASE)
    # [P0e5] collapse spaces between unary signs and numbers: "- 60" -> "-60", "+ 5" -> "+5"
    tidy = re.sub(r"(?:(?<=^)|(?<=[=;,(\[:/*+-]))(\s*)([+-])\s+(?=[0-9.])", r"\1\2", tidy)
    # [P0f] a currency written first moves behind the number: "Rs 288" -> "288 Rs", "₹288" -> "288 ₹".
    currency_match = re.match(r"^(Rs\.?|₹)\s*(.+)$", tidy)
    if currency_match is not None:
        currency = currency_match.group(1).replace(".", "")
        tidy = currency_match.group(2) + " " + currency
    # [P0g] a full stop or semicolon left at the very end ("30 cm.") is dropped.
    tidy = tidy.rstrip(".;").strip()
    return tidy


NUMBER_WORDS: dict[str, float] = {
    "zero": 0.0, "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0,
    "six": 6.0, "seven": 7.0, "eight": 8.0, "nine": 9.0, "ten": 10.0,
    "eleven": 11.0, "twelve": 12.0, "thirteen": 13.0, "fourteen": 14.0, "fifteen": 15.0,
    "sixteen": 16.0, "seventeen": 17.0, "eighteen": 18.0, "nineteen": 19.0,
    "twenty": 20.0, "thirty": 30.0, "forty": 40.0, "fifty": 50.0,
    "sixty": 60.0, "seventy": 70.0, "eighty": 80.0, "ninety": 90.0,
    "hundred": 100.0, "thousand": 1000.0,
    "half": 0.5, "quarter": 0.25,
}
CORE_NUMBER_WORDS: set[str] = set(NUMBER_WORDS.keys()) | {"point", "dot"}

WORD_NUMBER_PATTERN: re.Pattern[str] = re.compile(
    r"\b(?:(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|half|quarter|point|dot|and)\b[- ]?)+",
    re.IGNORECASE,
)


def parse_word_tokens(tokens: list[str]) -> float | None:
    """Convert a sequence of number word tokens (e.g. ['sixty'], ['zero', 'point', 'six']) to a number."""
    if not any(t in CORE_NUMBER_WORDS for t in tokens):
        return None
    if "point" in tokens or "dot" in tokens:
        idx = tokens.index("point") if "point" in tokens else tokens.index("dot")
        left = tokens[:idx]
        right = tokens[idx + 1:]
        left_val = parse_word_tokens(left) if left else 0.0
        if left_val is None:
            left_val = 0.0
        dec_str = ""
        for t in right:
            if t in NUMBER_WORDS and NUMBER_WORDS[t] < 10:
                dec_str += str(int(NUMBER_WORDS[t]))
            elif t.isdigit():
                dec_str += t
            else:
                return None
        if dec_str:
            return float(f"{int(left_val)}.{dec_str}")
        return float(left_val)

    total = 0.0
    current = 0.0
    matched = False
    for t in tokens:
        if t == "and":
            continue
        if t in ("hundred", "thousand"):
            scale = NUMBER_WORDS[t]
            current = (current if current else 1.0) * scale
            total += current
            current = 0.0
            matched = True
        elif t in NUMBER_WORDS:
            current += NUMBER_WORDS[t]
            matched = True
        else:
            return None
    return (total + current) if matched else None


def tidy_student_text(text: str) -> str:
    """Normalize student answer text so natural phrasing (number words, signs) can be checked."""
    if not text:
        return ""
    cleaned = text.strip()
    # Normalize phrases like "half an ampere" -> "half ampere"
    cleaned = re.sub(r"\bhalf\s+(?:an?)\s+", "half ", cleaned, flags=re.IGNORECASE)

    def repl(m: re.Match[str]) -> str:
        match_str = m.group(0).strip()
        tokens = [t.lower() for t in re.split(r"[- ]+", match_str) if t]
        if not any(t in CORE_NUMBER_WORDS for t in tokens):
            return m.group(0)
        val = parse_word_tokens(tokens)
        if val is not None:
            num_str = f"{int(val)}" if val == int(val) else f"{val}"
            trailing = " " if m.group(0).endswith(" ") else ""
            return num_str + trailing
        return m.group(0)

    cleaned = WORD_NUMBER_PATTERN.sub(repl, cleaned)
    return tidy_answer_text(cleaned)


def read_quantity(text: str) -> dict[str, Any]:
    """Read an answer written as text, such as "-30 cm", "+1.25 D" or "3 x 10^8 m/s", into its SI value.

    The number comes first, then its unit; a currency may come first ("Rs 288").
    It understands the Unicode minus (−), thousands commas, "× 10^8", superscripts (10⁸), and every unit
    that convert_to_si knows, as a symbol ("cm") or a word ("centimetres").
    Returns the shared result shape with the SI value and SI unit, plus "read_number" and "read_unit"
    (the number and unit symbol as written). With no unit, solved_for is "number" and the unit is "none".
    Returns the error shape if there is no number at the start, or the unit is unknown.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [P0] tidy the text (tidy_answer_text)
    #          |
    #          v
    #   [P1] a number at the start?                  no -> [E] error
    #          | yes: number = it, rest = what follows
    #          v
    #   [P2] is anything left after the number?
    #          |                                   |
    #          | no                                | yes
    #          v                                   v
    #   [B-NONE] value = number, unit "none"   [B-UNIT] convert_to_si(number, rest)
    #                                               unknown unit -> [E] error
    #          |                                   |
    #          v                                   v
    #   [R] make_result(kind, SI value, SI unit, formula) + read_number, read_unit

    # [P0] tidy the text first.
    tidy = tidy_answer_text(text)

    # [P1] the number must come first.
    number_match = NUMBER_AT_START.match(tidy)
    if number_match is None:
        return make_error("Could not find a number at the start of '" + text + "'.")
    number = float(number_match.group(0))
    rest = tidy[number_match.end():].strip()

    # [P2] is there a unit after the number?
    if rest == "":
        # [B-NONE] a bare number: nothing to convert.
        result = make_result("number", number, "none", "a number with no unit")
        result["read_number"] = number
        result["read_unit"] = "none"
        return result

    # [B-UNIT] convert the number with its unit to SI; an unknown unit gives the converter's error.
    converted = convert_to_si(number, rest)
    if not converted["ok"]:
        return converted

    # [R] the SI value, plus what was written.
    result = make_result(converted["solved_for"], converted["value"], converted["unit"], converted["formula"])
    result["read_number"] = number
    result["read_unit"] = find_unit_symbol(rest)
    return result


def make_check_result(check_name: str, passed: bool, rule: str, detail: str) -> dict[str, Any]:
    """The shared result shape for a check: "value" is True or False, and "detail" says why, in plain words.

    The detail is written by this code, never by the model, so the tutor can give the right hint.
    """
    result = make_result(check_name, passed, "no unit", rule)
    result["detail"] = detail
    return result


def percent_text(fraction: float) -> str:
    """Show a fraction as a percentage for a message, for example 0.0423 -> "4.2%". Rounded for display only."""
    return str(round(fraction * 100, 1)) + "%"


def check_numeric_answer(student_text: str, gold_text: str, tolerance: float = 0.02) -> dict[str, Any]:
    """Check a student's numerical answer against the answer key, both written as text with units, such as "-30 cm".

    Both are read with read_quantity and compared in SI units, so "-0.3 m" matches "-30 cm".
    The answer is correct when the sign matches and |student - key| / |key| <= tolerance (default 0.02, that is 2%).
    The default allows for rounding: NCERT's own printed answers differ from the exact values by up to 1%.
    A different kind of unit (s instead of cm) is wrong. A missing unit is read in the key's unit and still counts as
    correct, but "detail" says the unit is missing, so the tutor can remind the student.
    Returns the shared shape with value True or False and a "detail" saying why. Returns the error shape only if
    the answer key itself cannot be read, or the tolerance is not between 0 and 1.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [T]  tolerance between 0 and 1?                       no  -> [E] error
    #   [C1] can the KEY be read?                             no  -> [E] error (our bug, not the student's)
    #   [C2] can the STUDENT's answer be read?                no  -> [W] False, "could not read"
    #   [C3] units: different kinds (cm vs s)?                yes -> [W] False, "wrong kind of unit"
    #        key has a unit, the answer has none?             -> read the answer in the key's unit, note it
    #        the key has no unit?                             -> compare the written numbers, note it
    #   [C4] key is 0?                                        yes -> True if the answer is 0 too
    #   [C5] signs differ?                                    yes -> [W] False, "wrong sign"
    #   [C6] |student - key| / |key| <= tolerance?            yes -> [OK] True; no -> [W] False, "off by X%"
    #   [R]  make_check_result("correct", True/False, rule, detail)

    # [T] the tolerance must make sense.
    if tolerance < 0 or tolerance >= 1:
        return make_error("tolerance must be at least 0 and less than 1, for example 0.02 for 2%.")
    rule = "same sign, and |student - key| / |key| <= " + percent_text(tolerance)

    # [C1] the key comes from our side, so if it can't be read that is an error, not a wrong answer.
    gold = read_quantity(gold_text)
    if not gold["ok"]:
        return make_error("The answer key '" + gold_text + "' could not be read: " + gold["error"])

    # [C2] the student's answer (tidied for number words, square roots, fractions and signs).
    student = read_quantity(tidy_student_text(student_text))
    if not student["ok"]:
        return make_check_result("correct", False, rule, "Could not read a number and unit from the answer. " + student["error"])

    # [C3] decide which two numbers to compare.
    unit_note = ""
    key_has_unit = gold["unit"] != "none"
    answer_has_unit = student["unit"] != "none"
    if key_has_unit and answer_has_unit:
        # Both have units: they must measure the same kind of quantity.
        if student["solved_for"] != gold["solved_for"]:
            return make_check_result(
                "correct", False, rule,
                "Wrong kind of unit: the answer is a " + student["solved_for"] + " (" + student["read_unit"]
                + "), but the key is a " + gold["solved_for"] + " (" + gold["read_unit"] + ").",
            )
        answer_value = student["value"]
        key_value = gold["value"]
    elif key_has_unit:
        # The answer has no unit: read its number in the key's unit, and say the unit is missing.
        answer_value = convert_to_si(student["read_number"], gold["read_unit"])["value"]
        key_value = gold["value"]
        unit_note = " The unit is missing: write it (" + gold["read_unit"] + ")."
    elif answer_has_unit:
        # The key has no unit, so only the written numbers can be compared.
        answer_value = student["read_number"]
        key_value = gold["read_number"]
        unit_note = " (The key has no unit, so only the numbers were compared.)"
    else:
        # Neither has a unit: compare the numbers.
        answer_value = student["read_number"]
        key_value = gold["read_number"]

    # [C4] a key of 0 cannot be divided by, so check it directly.
    if key_value == 0:
        if answer_value == 0:
            return make_check_result("correct", True, rule, "Matches the key (0)." + unit_note)
        return make_check_result("correct", False, rule, "The key is 0, but the answer is not." + unit_note)

    # [C5] the signs must match: -30 cm is not +30 cm.
    if answer_value * key_value < 0:
        if key_value < 0:
            sign_words = "the key is negative, but the answer is positive"
        else:
            sign_words = "the key is positive, but the answer is negative"
        return make_check_result("correct", False, rule, "Wrong sign: " + sign_words + ". Check the sign convention." + unit_note)

    # [C6] close enough?
    relative_difference = abs(answer_value - key_value) / abs(key_value)
    if relative_difference <= tolerance:
        return make_check_result("correct", True, rule, "Matches the key (within " + percent_text(tolerance) + ")." + unit_note)
    return make_check_result(
        "correct", False, rule,
        "Off by " + percent_text(relative_difference) + " (allowed: " + percent_text(tolerance) + ")." + unit_note,
    )


# Formula names that stay whole when a formula is read: everything else such as "IR" is read as I * R.
FORMULA_NAMES_KEPT_WHOLE: list[str] = ["rho", "pi", "Rs", "Rp"]

# The only characters allowed in a formula: English letters, digits, spaces and + - * / ^ ( ) = .
# Anything else (including Greek or full-width letters) is refused before SymPy sees the text.
SAFE_FORMULA_PATTERN: str = r"[A-Za-z0-9 +\-*/^().=]+"

# The longest formula text accepted.
MAX_FORMULA_LENGTH: int = 100


def is_safe_formula_text(text: str) -> bool:
    """True only if formula text is safe to hand to SymPy, whose parser runs Python's eval underneath.

    Allowed: English letters, digits, spaces and + - * / ^ ( ) = . only; at most 100 characters; at most one "=".
    So no underscores, quotes, brackets [], commas or colons, which code would need, and no Greek letters
    (write "rho", not the Greek letter).
    """
    # Empty or too long text is refused.
    if len(text.strip()) == 0 or len(text) > MAX_FORMULA_LENGTH:
        return False
    # Every character must be one of the allowed ones: the whole text must match the pattern.
    if re.fullmatch(SAFE_FORMULA_PATTERN, text) is None:
        return False
    # A formula has at most one "=".
    if text.count("=") > 1:
        return False
    return True


def can_split_name(name: str) -> bool:
    """For SymPy's parser: may a run of letters such as "IR" be read as I * R? Names such as "rho" stay whole."""
    # Known names are never split.
    if name in FORMULA_NAMES_KEPT_WHOLE:
        return False
    # Names with digits, such as "R1", stay whole too.
    for character in name:
        if character.isdigit():
            return False
    # A single letter has nothing to split; longer runs are split into letters.
    return len(name) > 1


def parse_formula_side(text: str) -> Any:
    """Turn one side of a formula (already checked by is_safe_formula_text) into a SymPy expression."""
    # Every single letter (and each kept-whole name) is a plain symbol, so "I" means current here,
    # not SymPy's imaginary unit, and "E" means energy, not Euler's number.
    # This is a second layer: allowed_names below already leaves SymPy's constants out, and this loop keeps
    # every letter a plain symbol even if someone adds one there later.
    # string.ascii_letters is Python's built-in list of the 52 English letters, a-z then A-Z.
    local_names: dict[str, Any] = {}
    for letter in string.ascii_letters:
        local_names[letter] = Symbol(letter)
    for name in FORMULA_NAMES_KEPT_WHOLE:
        local_names[name] = Symbol(name)

    # Only the few SymPy names the parser needs; no Python built-ins at all.
    allowed_names: dict[str, Any] = {
        "__builtins__": {},
        "Symbol": Symbol,
        "Integer": Integer,
        "Float": Float,
        "Rational": Rational,
        "sqrt": sqrt,
    }

    # "^" means power, "IR" means I * R, and "2u" means 2 * u.
    reading_rules = standard_transformations + (convert_xor, split_symbols_custom(can_split_name), implicit_multiplication)
    return parse_expr(text, local_dict=local_names, global_dict=allowed_names, transformations=reading_rules)


def solutions_match(first: list[Any], second: list[Any]) -> bool:
    """True if two lists of SymPy solutions contain the same values (in any order)."""
    if len(first) != len(second):
        return False
    # Every solution in the first list must equal one in the second.
    for solution in first:
        found = False
        for other in second:
            if simplify(solution - other) == 0:
                found = True
        if not found:
            return False
    return True


def check_equivalence(student_text: str, gold_text: str) -> dict[str, Any]:
    """Check whether a student's formula is the same as the key's formula, for example "R = V/I" and "V = IR".

    Both can be equations (with "=") or both plain expressions (such as "I^2 R"). Write powers with "^";
    letters next to each other multiply ("IR" is I x R); "rho", "pi", "Rs" and "Rp" stay whole names.
    Equations are the same when solving both for a shared quantity gives the same result; expressions are the
    same when their difference simplifies to 0. A different set of quantities ("P = VI" vs "P = I^2 R") is
    reported as different: linking them needs Ohm's law, which this check does not assume.
    The text is checked for safe characters before SymPy reads it, because SymPy's parser runs Python's eval.
    Returns the shared shape with value True or False and a "detail" saying why. Returns the error shape only if
    the answer key itself is unsafe or cannot be read.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [Q0] key text safe?        no -> [E] error;   answer text safe?   no -> [W] False, "not allowed"
    #   [Q1] both read by SymPy?   key fails -> [E] error;   answer fails -> [W] False, "could not read"
    #   [Q2] which kind?
    #          |                          |                           |
    #          | both equations           | both expressions          | one of each
    #          v                          v                           v
    #   [B-EQ] same quantities?     [B-EXPR] student - key     [B-MIX] False
    #          then solve both for       simplifies to 0?
    #          a shared one; same?
    #          |                          |                           |
    #          v                          v                           v
    #   [R] make_check_result("equivalent", True/False, method, detail)
    method = "solve both for a shared quantity (equations), or simplify the difference (expressions)"

    # [Q0] the key must be safe text; an unsafe key is our error.
    if not is_safe_formula_text(gold_text):
        return make_error("The answer key '" + gold_text + "' is not a safe formula (English letters, digits and + - * / ^ ( ) = . only).")
    # [Q0] an unsafe answer is never given to SymPy; it is simply not a formula we can check.
    if not is_safe_formula_text(student_text):
        return make_check_result(
            "equivalent", False, method,
            "The answer has characters that are not allowed in a formula, or is longer than "
            + str(MAX_FORMULA_LENGTH) + " characters. Use English letters, digits and + - * / ^ ( ) = only, and write Greek letters as words (rho).",
        )

    # [Q1] read both with SymPy. Any reading error becomes a message, never a crash.
    student_is_equation = "=" in student_text
    key_is_equation = "=" in gold_text
    try:
        if key_is_equation:
            key_left, key_right = gold_text.split("=")
            key_formula = Eq(parse_formula_side(key_left), parse_formula_side(key_right), evaluate=False)
        else:
            key_formula = parse_formula_side(gold_text)
    except Exception as error:  # SymPy raises many different error types for text it cannot read
        return make_error("The answer key '" + gold_text + "' could not be read as a formula: " + str(error))
    try:
        if student_is_equation:
            student_left, student_right = student_text.split("=")
            student_formula = Eq(parse_formula_side(student_left), parse_formula_side(student_right), evaluate=False)
        else:
            student_formula = parse_formula_side(student_text)
    except Exception as error:  # SymPy raises many different error types for text it cannot read
        return make_check_result("equivalent", False, method, "Could not read the answer as a formula: " + str(error))

    # [Q2] [B-MIX] an equation and a plain expression cannot be the same.
    if student_is_equation != key_is_equation:
        return make_check_result("equivalent", False, method, "One is an equation (with \"=\") and the other is not.")

    # [B-EXPR] two expressions: the same if their difference simplifies to 0.
    if not key_is_equation:
        if simplify(student_formula - key_formula) == 0:
            return make_check_result("equivalent", True, method, "The two expressions are equal.")
        return make_check_result("equivalent", False, method, "The two expressions are not equal.")

    # [B-EQ] two equations: they must use the same quantities...
    if student_formula.free_symbols != key_formula.free_symbols:
        # List the quantities each formula uses, so the message can show the difference.
        student_names: list[str] = []
        for symbol in student_formula.free_symbols:
            student_names.append(str(symbol))
        key_names: list[str] = []
        for symbol in key_formula.free_symbols:
            key_names.append(str(symbol))
        return make_check_result(
            "equivalent", False, method,
            "The formulas use different quantities: the answer uses " + ", ".join(sorted(student_names))
            + "; the key uses " + ", ".join(sorted(key_names)) + ".",
        )

    # ...and solving both for a shared quantity must give the same result.
    for quantity in sorted(key_formula.free_symbols, key=str):
        student_solutions = solve(student_formula, quantity)
        key_solutions = solve(key_formula, quantity)
        # Skip a quantity that cannot be solved for in one of them.
        if len(student_solutions) == 0 or len(key_solutions) == 0:
            continue
        if solutions_match(student_solutions, key_solutions):
            return make_check_result(
                "equivalent", True, method,
                "Same relation: both give " + str(quantity) + " = " + str(key_solutions[0]) + ".",
            )
        return make_check_result(
            "equivalent", False, method,
            "Different relation: solving for " + str(quantity) + " gives " + str(student_solutions[0])
            + ", but the key gives " + str(key_solutions[0]) + ".",
        )
    return make_check_result("equivalent", False, method, "Could not solve the formulas for any shared quantity.")


# ---------------------------------------------------------------------------
# Arithmetic between steps (decision D4): for numbers that sit between two solver calls,
# such as "8 h a day for 30 days" = 8 * 30 hours. Read by a small safe parser, never by eval.
# ---------------------------------------------------------------------------

# The longest arithmetic text accepted, and the largest power allowed (10^1000000 would freeze the program).
MAX_CALCULATION_LENGTH: int = 100
MAX_POWER_EXPONENT: float = 100.0

# Characters allowed in arithmetic after tidying: digits, the point, operators, brackets, spaces and the "e" of 3e8.
SAFE_CALCULATION_CHARACTERS: str = "0123456789.+-*/() eE"


def evaluate_arithmetic(node: ast.AST) -> float:
    """Work out one part of a parsed arithmetic expression. Only numbers, + - * / ** and brackets are allowed.

    Raises ValueError for anything else; calculate turns that into an error message.
    """
    # The whole expression: work out its body.
    if isinstance(node, ast.Expression):
        return evaluate_arithmetic(node.body)
    # A plain number. (True and False count as numbers in Python, so they are refused by name.)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            raise ValueError("only numbers are allowed")
        if isinstance(node.value, int) or isinstance(node.value, float):
            return float(node.value)
        raise ValueError("only numbers are allowed")
    # A sign in front: +5 or -5.
    if isinstance(node, ast.UnaryOp):
        operand = evaluate_arithmetic(node.operand)
        if isinstance(node.op, ast.UAdd):
            return operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise ValueError("only + and - may stand in front of a number")
    # Two parts joined by an operator.
    if isinstance(node, ast.BinOp):
        left = evaluate_arithmetic(node.left)
        right = evaluate_arithmetic(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ValueError("division by zero")
            return left / right
        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_POWER_EXPONENT:
                raise ValueError("the power is too large (at most " + str(MAX_POWER_EXPONENT) + ")")
            return left ** right
        raise ValueError("only + - * / and ^ are allowed")
    # Anything else (names, function calls, lists, ...) is not arithmetic.
    raise ValueError("only numbers, + - * / ^ and brackets are allowed")


def calculate(expression: str) -> dict[str, Any]:
    """Work out plain arithmetic that sits between two steps, for example "8 * 30" (8 h a day for 30 days).

    Only numbers and + - * / ^ ( ) are allowed; x or × also mean times, ÷ means divide, and 3e8 or 3 × 10^8 work.
    No letters, names or functions: this is a calculator, not a formula solver. Use the solve_... functions for
    physics formulas, and convert_to_si for units.
    The text is read by a small safe parser, never by Python's eval.
    Returns the shared result shape (solved_for "value", no unit), or the error shape.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [K0] tidy: "× 10^8" -> e8; × x -> *; ÷ -> /; ^ -> **; Unicode minus -> -
    #   [K1] at most 100 characters, and only digits . + - * / ( ) spaces e?   no -> [E] error
    #   [K2] does it parse as Python arithmetic?                                 no -> [E] error
    #   [K3] work it out with evaluate_arithmetic (numbers and operators only)   bad -> [E] error
    #   [R]  make_result("value", result, "no unit", "calculated: <expression>")

    # [K0] tidy the text the same way as answers, then turn the remaining symbols into Python's.
    tidy = tidy_answer_text(expression)
    tidy = tidy.replace("×", "*").replace("x", "*").replace("X", "*").replace("÷", "/").replace("^", "**")

    # [K1] the length and the characters.
    if len(tidy) == 0 or len(tidy) > MAX_CALCULATION_LENGTH:
        return make_error("Give an arithmetic expression of 1 to " + str(MAX_CALCULATION_LENGTH) + " characters.")
    for character in tidy:
        if character not in SAFE_CALCULATION_CHARACTERS:
            return make_error("Only numbers and + - * / ^ ( ) are allowed in a calculation, not '" + character + "'.")

    # [K2] parse the text into a tree. Parsing only reads the text; nothing is run.
    try:
        tree = ast.parse(tidy, mode="eval")
    except SyntaxError:
        return make_error("'" + expression + "' is not a complete calculation.")

    # [K3] work out the tree, allowing only numbers and the five operators.
    try:
        result = evaluate_arithmetic(tree)
    except (ValueError, OverflowError, RecursionError) as error:
        return make_error("Could not calculate '" + expression + "': " + str(error) + ".")
    # A negative number to a fractional power gives a complex number, which is not a school answer.
    if isinstance(result, complex):
        return make_error("Could not calculate '" + expression + "': the result is not a real number.")

    # [R]
    return make_result("value", result, "no unit", "calculated: " + tidy)


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


def resistor_names(count: int) -> list[str]:
    """Build the names "Resistor 1", "Resistor 2", ... so an error can say which resistor is wrong."""
    names: list[str] = []
    for number in range(1, count + 1):
        names.append("Resistor " + str(number))
    return names


def solve_series_resistance(resistors: list[float]) -> dict[str, Any]:
    """Resistors joined end to end (in series): Rs = R1 + R2 + ... (NCERT Class 10 Science, Ch 11, section 11.6.1).

    resistors is a list of at least 2 resistances, each in ohm and greater than 0.
    In series the same current flows through every resistor, and Rs is bigger than any one of them.
    For a mixed circuit, work out each group first, then pass the group results in here.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] at least 2 resistors in the list?     no -> [E] error
    #          | yes
    #          v
    #   [S2] every resistor greater than 0?        no -> [E] error
    #          | yes
    #          v
    #   [B-S] add them up one by one: total = R1 + R2 + ...
    #          |
    #          v
    #   [R] make_result("Rs", total, "ohm", "Rs = R1 + R2 + ...")

    # [S1] a combination needs at least 2 resistors.
    if len(resistors) < 2:
        return make_error("Give at least 2 resistances (in ohm) to combine in series.")

    # [S2] every resistor must be greater than 0.
    bad_name = find_zero_or_negative(resistor_names(len(resistors)), resistors)
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [B-S] add the resistances one by one.
    total = 0.0
    for resistance in resistors:
        total = total + resistance

    # [R]
    return make_result("Rs", total, "ohm", "Rs = R1 + R2 + ...")


def solve_parallel_resistance(resistors: list[float]) -> dict[str, Any]:
    """Resistors joined side by side (in parallel): 1/Rp = 1/R1 + 1/R2 + ... (NCERT Class 10 Science, Ch 11, section 11.6.2).

    resistors is a list of at least 2 resistances, each in ohm and greater than 0.
    In parallel every resistor has the same potential difference, and Rp is smaller than the smallest one.
    For a mixed circuit, work out each group first, then combine the group results.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] at least 2 resistors in the list?     no -> [E] error
    #          | yes
    #          v
    #   [S2] every resistor greater than 0?        no -> [E] error
    #          | yes
    #          v
    #   [B-P] add up 1/R for every resistor, then flip the sum: rp = 1 / sum
    #          |
    #          v
    #   [R] make_result("Rp", rp, "ohm", "1/Rp = 1/R1 + 1/R2 + ...")

    # [S1] a combination needs at least 2 resistors.
    if len(resistors) < 2:
        return make_error("Give at least 2 resistances (in ohm) to combine in parallel.")

    # [S2] every resistor must be greater than 0 (this also rules out dividing by zero below).
    bad_name = find_zero_or_negative(resistor_names(len(resistors)), resistors)
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [B-P] add up 1/R for every resistor...
    reciprocal_sum = 0.0
    for resistance in resistors:
        reciprocal_sum = reciprocal_sum + 1 / resistance
    # ...then flip the sum, because the formula gives 1/Rp, not Rp.
    rp = 1 / reciprocal_sum

    # [R]
    return make_result("Rp", rp, "ohm", "1/Rp = 1/R1 + 1/R2 + ...")


def solve_joule_heating(
    h: float | None = None,
    i: float | None = None,
    r: float | None = None,
    t: float | None = None,
) -> dict[str, Any]:
    """Joule's law of heating: H = I^2 x R x t (NCERT Class 10 Science, Ch 11, Eq. 11.21).

    Give exactly three of the four values and leave the fourth as None; the missing one is calculated.
    Units are SI: h (heat produced) in joule (J), i in ampere (A), r in ohm, t in second (s).
    Convert minutes or hours to seconds first with convert_to_si.
    All the energy becomes heat only in a purely resistive circuit (resistors only, no motor or fan).
    If V and R are known instead of I, find I first with solve_ohms_law.
    If the charge Q is given instead of I, the heat is V x Q: use solve_voltage_work_charge.
    Every given value must be greater than 0.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly three of h, i, r, t given?   no -> [E] error
    #          | yes
    #          v
    #   [S2] every given value greater than 0?    no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |                  |                   |                   |
    #          | h missing        | i missing         | r missing         | t missing
    #          v                  v                   v                   v
    #   [B-H] h = i * i    [B-I] i = sqrt(     [B-R] r = h /       [B-T] t = h /
    #         * r * t            h / (r * t))        (i * i * t)         (i * i * r)
    #          |                  |                   |                   |
    #          v                  v                   v                   v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S1] exactly three of the four values must be given.
    if count_given([h, i, r, t]) != 3:
        return make_error(
            "Give exactly three of H (joule), I (ampere), R (ohm) and t (second), and leave the fourth empty."
        )

    # [S2] every given value must be greater than 0.
    # This one check also rules out dividing by zero and taking the square root of a negative number
    # (math.sqrt of a negative number crashes), so the branches below need no checks of their own.
    bad_name = find_zero_or_negative(["Heat H", "Current I", "Resistance R", "Time t"], [h, i, r, t])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if h is None:
        # [B-H] H is missing: square the current, then multiply by the resistance and the time.
        heat = i * i * r * t
        return make_result("H", heat, "J", "H = I^2 x R x t")

    if i is None:
        # [B-I] I is missing: I^2 = H / (R x t), so I is the square root of that.
        # Only the positive root is kept, because the current here is a size (magnitude).
        current = math.sqrt(h / (r * t))
        return make_result("I", current, "A", "I = sqrt(H / (R x t))")

    if r is None:
        # [B-R] R is missing.
        resistance = h / (i * i * t)
        return make_result("R", resistance, "ohm", "R = H / (I^2 x t)")

    # [B-T] The only case left is that t is missing.
    time_taken = h / (i * i * r)
    return make_result("t", time_taken, "s", "t = H / (I^2 x R)")


def solve_power_voltage_current(p: float | None = None, v: float | None = None, i: float | None = None) -> dict[str, Any]:
    """Electric power from potential difference and current: P = V x I (NCERT Class 10 Science, Ch 11, Eq. 11.19, 11.22).

    Give exactly two of the three values and leave the third as None; the missing one is calculated.
    Units are SI: p in watt (W), v in volt (V), i in ampere (A). 1 W = 1 V x 1 A (Eq. 11.23).
    Convert kW to W first with convert_to_si.
    A rating such as "220 V, 1000 W" gives the current the device draws: I = P / V.
    Every given value must be greater than 0.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly two of p, v, i given?     no -> [E] error
    #          | yes
    #          v
    #   [S2] every given value greater than 0? no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |                  |                  |
    #          | p missing        | v missing        | i missing
    #          v                  v                  v
    #   [B-P] p = v * i    [B-V] v = p / i    [B-I] i = p / v
    #          |                  |                  |
    #          v                  v                  v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S1] exactly two of the three values must be given.
    if count_given([p, v, i]) != 2:
        return make_error("Give exactly two of P (watt), V (volt) and I (ampere), and leave the third empty.")

    # [S2] every given value must be greater than 0.
    # This one check also rules out dividing by zero, so the branches below need no checks of their own.
    bad_name = find_zero_or_negative(["Power P", "Potential difference V", "Current I"], [p, v, i])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if p is None:
        # [B-P] P is missing.
        power = v * i
        return make_result("P", power, "W", "P = V x I")

    if v is None:
        # [B-V] V is missing.
        voltage = p / i
        return make_result("V", voltage, "V", "V = P / I")

    # [B-I] The only case left is that I is missing.
    current = p / v
    return make_result("I", current, "A", "I = P / V")


def solve_power_current_resistance(p: float | None = None, i: float | None = None, r: float | None = None) -> dict[str, Any]:
    """Electric power from current and resistance: P = I^2 x R (NCERT Class 10 Science, Ch 11, Eq. 11.22).

    Give exactly two of the three values and leave the third as None; the missing one is calculated.
    Units are SI: p in watt (W), i in ampere (A), r in ohm.
    P is also the rate at which heat is produced in the resistor (joule per second).
    For one resistor inside a circuit, first find the current through that resistor (for example with solve_ohms_law).
    If V is known instead of I, use solve_power_voltage_resistance (V and R) or solve_power_voltage_current (V and I).
    Every given value must be greater than 0.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly two of p, i, r given?     no -> [E] error
    #          | yes
    #          v
    #   [S2] every given value greater than 0? no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |                    |                      |
    #          | p missing          | i missing            | r missing
    #          v                    v                      v
    #   [B-P] p = i * i * r  [B-I] i = sqrt(p / r)  [B-R] r = p / (i * i)
    #          |                    |                      |
    #          v                    v                      v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S1] exactly two of the three values must be given.
    if count_given([p, i, r]) != 2:
        return make_error("Give exactly two of P (watt), I (ampere) and R (ohm), and leave the third empty.")

    # [S2] every given value must be greater than 0.
    # This one check also rules out dividing by zero and taking the square root of a negative number
    # (math.sqrt of a negative number crashes), so the branches below need no checks of their own.
    bad_name = find_zero_or_negative(["Power P", "Current I", "Resistance R"], [p, i, r])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if p is None:
        # [B-P] P is missing: square the current, then multiply by the resistance.
        power = i * i * r
        return make_result("P", power, "W", "P = I^2 x R")

    if i is None:
        # [B-I] I is missing: I^2 = P / R, so I is the square root of P / R.
        # Only the positive root is kept, because the current here is a size (magnitude).
        current = math.sqrt(p / r)
        return make_result("I", current, "A", "I = sqrt(P / R)")

    # [B-R] The only case left is that R is missing.
    resistance = p / (i * i)
    return make_result("R", resistance, "ohm", "R = P / I^2")


def solve_power_voltage_resistance(p: float | None = None, v: float | None = None, r: float | None = None) -> dict[str, Any]:
    """Electric power from potential difference and resistance: P = V^2 / R (NCERT Class 10 Science, Ch 11, Eq. 11.22).

    Give exactly two of the three values and leave the third as None; the missing one is calculated.
    Units are SI: p in watt (W), v in volt (V), r in ohm.
    A rating such as "220 V, 100 W" gives the device's resistance: R = V^2 / P.
    The resistance stays the same at another voltage, so use that resistance to find the power at the new voltage.
    In a parallel circuit every resistor has the full voltage across it, so this needs no current.
    Every given value must be greater than 0.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly two of p, v, r given?     no -> [E] error
    #          | yes
    #          v
    #   [S2] every given value greater than 0? no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |                    |                      |
    #          | p missing          | v missing            | r missing
    #          v                    v                      v
    #   [B-P] p = v * v / r  [B-V] v = sqrt(p * r)  [B-R] r = v * v / p
    #          |                    |                      |
    #          v                    v                      v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S1] exactly two of the three values must be given.
    if count_given([p, v, r]) != 2:
        return make_error("Give exactly two of P (watt), V (volt) and R (ohm), and leave the third empty.")

    # [S2] every given value must be greater than 0.
    # This one check also rules out dividing by zero and taking the square root of a negative number
    # (math.sqrt of a negative number crashes), so the branches below need no checks of their own.
    bad_name = find_zero_or_negative(["Power P", "Potential difference V", "Resistance R"], [p, v, r])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if p is None:
        # [B-P] P is missing: square the potential difference, then divide by the resistance.
        power = v * v / r
        return make_result("P", power, "W", "P = V^2 / R")

    if v is None:
        # [B-V] V is missing: V^2 = P x R, so V is the square root of P x R.
        # Only the positive root is kept, because the potential difference here is a size (magnitude).
        voltage = math.sqrt(p * r)
        return make_result("V", voltage, "V", "V = sqrt(P x R)")

    # [B-R] The only case left is that R is missing.
    resistance = v * v / p
    return make_result("R", resistance, "ohm", "R = V^2 / P")


def solve_energy_power_time(energy: float | None = None, p: float | None = None, t: float | None = None) -> dict[str, Any]:
    """Electric energy from power and time: energy = P x t (NCERT Class 10 Science, Ch 11, section 11.8).

    Give exactly two of the three values and leave the third as None; the missing one is calculated.
    Units are SI: energy in joule (J), p in watt (W), t in second (s).
    Convert kW, hours or minutes first with convert_to_si.
    For a time such as "8 h a day for 30 days", work out 8 * 30 with calculate first, then convert the hours.
    In a purely resistive circuit (resistors only) this energy is also the heat produced.
    For the cost on an electricity bill, pass the energy to solve_energy_cost.
    Every given value must be greater than 0.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly two of energy, p, t given?   no -> [E] error
    #          | yes
    #          v
    #   [S2] every given value greater than 0?    no -> [E] error
    #          | yes
    #          v
    #   [S3] which one is missing?
    #          |                         |                       |
    #          | energy missing          | p missing             | t missing
    #          v                         v                       v
    #   [B-E] energy = p * t      [B-P] p = energy / t    [B-T] t = energy / p
    #          |                         |                       |
    #          v                         v                       v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S1] exactly two of the three values must be given.
    if count_given([energy, p, t]) != 2:
        return make_error("Give exactly two of energy (joule), P (watt) and t (second), and leave the third empty.")

    # [S2] every given value must be greater than 0.
    # This one check also rules out dividing by zero, so the branches below need no checks of their own.
    bad_name = find_zero_or_negative(["Energy", "Power P", "Time t"], [energy, p, t])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if energy is None:
        # [B-E] energy is missing.
        energy_used = p * t
        return make_result("energy", energy_used, "J", "energy = P x t")

    if p is None:
        # [B-P] P is missing.
        power = energy / t
        return make_result("P", power, "W", "P = energy / t")

    # [B-T] The only case left is that t is missing.
    time_taken = energy / p
    return make_result("t", time_taken, "s", "t = energy / P")


def solve_energy_cost(energy: float | None = None, rate: float | None = None, cost: float | None = None) -> dict[str, Any]:
    """Cost of electric energy: cost = energy in kW h x rate (NCERT Class 10 Science, Ch 11, section 11.8, Example 11.13).

    Give exactly two of the three values and leave the third as None; the missing one is calculated.
    energy is in joule (J), the SI unit. If it is given in kW h ("units" on an electricity bill),
    convert it first with convert_to_si(value, "kWh").
    If the power and the time are known instead, find the energy first with solve_energy_power_time.
    rate is the price of 1 kW h, in rupees (Rs per kW h). cost is in rupees (Rs).
    To show an energy found in joules as kW h ("units"), use convert_from_si(energy, "kWh").
    1 kW h = 3.6 x 10^6 J.
    Every given value must be greater than 0.
    Returns the shared result shape, or the error shape if the inputs cannot be used.
    """
    # Flowchart (each [box] matches a comment in the code below):
    #
    #   [S1] exactly two of energy, rate, cost given?   no -> [E] error
    #          | yes
    #          v
    #   [S2] every given value greater than 0?          no -> [E] error
    #          | yes
    #          v
    #   [K] joules_per_kwh = 3.6e6, read from the unit table
    #          |
    #          v
    #   [S3] which one is missing?
    #          |
    #          +-- cost missing   -> [B-C]    kwh = energy / joules_per_kwh, then cost = kwh * rate
    #          +-- rate missing   -> [B-RATE] kwh = energy / joules_per_kwh, then rate = cost / kwh
    #          +-- energy missing -> [B-E]    kwh = cost / rate, then energy = kwh * joules_per_kwh
    #          |
    #          v
    #   [R] make_result(quantity, exact value, unit, formula)

    # [S1] exactly two of the three values must be given.
    if count_given([energy, rate, cost]) != 2:
        return make_error("Give exactly two of energy (joule), rate (Rs per kW h) and cost (Rs), and leave the third empty.")

    # [S2] every given value must be greater than 0 (this also rules out dividing by zero below).
    bad_name = find_zero_or_negative(["Energy", "Rate", "Cost"], [energy, rate, cost])
    if bad_name is not None:
        return make_error(bad_name + " must be greater than 0.")

    # [K] how many joules make 1 kW h, read from the unit table so the number is written in one place only.
    # UNIT_SYMBOLS["kWh"] is ("energy", "J", 3600000.0); position 2 is the factor.
    joules_per_kwh: float = UNIT_SYMBOLS["kWh"][2]

    # [S3] calculate whichever value is missing, exactly (no rounding).
    if cost is None:
        # [B-C] cost is missing: turn the energy into kW h, then multiply by the price of 1 kW h.
        kwh = energy / joules_per_kwh
        total_cost = kwh * rate
        return make_result("cost", total_cost, "Rs", "cost = (energy / 3.6e6 J per kW h) x rate")

    if rate is None:
        # [B-RATE] rate is missing: turn the energy into kW h, then share the cost over those kW h.
        kwh = energy / joules_per_kwh
        price_per_kwh = cost / kwh
        return make_result("rate", price_per_kwh, "Rs per kW h", "rate = cost / (energy / 3.6e6 J per kW h)")

    # [B-E] The only case left is that energy is missing: kW h bought = cost / rate, then turn kW h into joules.
    kwh = cost / rate
    energy_used = kwh * joules_per_kwh
    return make_result("energy", energy_used, "J", "energy = (cost / rate) x 3.6e6 J per kW h")

