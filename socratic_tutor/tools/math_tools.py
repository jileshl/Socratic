"""FastMCP Tool Server: math-tools (solve, check equivalence, numeric check with tolerance)."""

import math
from typing import Any


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


# TODO (Milestone 3.3 / L7): Solve Ohm's Law and Resistor Combinations
def solve_ohms_law(v: float | None = None, i: float | None = None, r: float | None = None) -> dict[str, Any]:
    """Solve V = I * R given any two parameters."""
    if v is None and i is not None and r is not None:
        return {"v": round(i * r, 2)}
    if i is None and v is not None and r is not None:
        if r == 0:
            return {"error": "Resistance cannot be zero"}
        return {"i": round(v / r, 2)}
    if r is None and v is not None and i is not None:
        if i == 0:
            return {"error": "Current cannot be zero"}
        return {"r": round(v / i, 2)}
    return {"error": "Must provide exactly two of V, I, R"}


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

