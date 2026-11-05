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


def make_result(quantity_name: str, exact_value: float | str, result_unit: str, formula_used: str) -> dict[str, Any]:
    """Build the success shape: the quantity found, its exact value, its unit and the formula used.

    The value is a number, except for describe_image, whose value is a description such as "real and inverted, enlarged".
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


def numeric_check(student_val: float, gold_val: float, tolerance: float = 0.05) -> bool:
    """Verify if student value matches gold value within relative tolerance percentage."""
    if gold_val == 0:
        return abs(student_val) < 1e-6
    return abs(student_val - gold_val) / abs(gold_val) <= tolerance


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

