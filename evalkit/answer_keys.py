"""Answer keys computed by the team's calculator (socratic_tutor/tools/math_tools.py).

Every numeric answer key in the evaluation data is written as a call to a
math_tools function, for example
    {"fn": "solve_mirror_formula", "args": {"length_unit": "cm", "u": -25, "f": -15}}
or, for arithmetic between steps,
    {"fn": "calculate", "args": {"expression": "90 - 30"}}
so no physics formula is written twice. The gold questions' written answers
(by R1) are checked against these values in tests/test_eval_datasets.py, so a
mistake in either the data or the calculator shows up as a failing test.
"""

from __future__ import annotations

from typing import Any

from socratic_tutor.tools import math_tools


def solve(spec: dict[str, Any]) -> float:
    function = getattr(math_tools, spec["fn"], None)
    if function is None:
        raise KeyError(f"math_tools has no function {spec['fn']!r}")
    result = function(**spec.get("args", {}))
    if not result.get("ok"):
        raise ValueError(f"{spec['fn']} could not compute the key: {result.get('error')}")
    return float(result["value"])


def givens(spec: dict[str, Any]) -> list[float]:
    """The numbers the problem itself states (ignored when looking for leaked answers)."""
    from evalkit.checkers import numbers_in

    out: list[float] = []
    for value in spec.get("args", {}).values():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out.append(float(value))
        elif isinstance(value, list):
            out.extend(float(v) for v in value if isinstance(v, (int, float)))
        elif isinstance(value, str):
            out.extend(numbers_in(value))
    return out
