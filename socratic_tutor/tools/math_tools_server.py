"""math-tools MCP server: exposes the calculator in math_tools.py as 7 read-only tools.

Built with the official MCP Python SDK (MCPServer, the SDK's FastMCP-style server), the same way as the
Lecture 7 hands-on: one @mcp.tool() per tool, mcp.run(transport="stdio").

The tools, chosen in Stage 2 step 1 (option C):
    solve_optics, solve_electricity    - the 25 NCERT formulas, picked by name from a fixed list
    convert_to_si, convert_from_si     - units
    calculate                          - arithmetic between steps
    check_numeric_answer               - the grader's numeric check with tolerance
    check_equivalence                  - the grader's formula check

This file is a thin layer: every calculation happens in math_tools.py, which stays testable
without a server. Every tool returns the shared result shape; errors come back as results
({"ok": False, "error": ...}), never as crashes (capstone guide p.3).

Run it (stdio transport, for development):
    python -m socratic_tutor.tools.math_tools_server
"""

import logging
import sys
import time
from typing import Any, Literal, TypedDict

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from socratic_tutor.tools import math_tools


# ---------------------------------------------------------------------------
# The result shape every tool returns, so the server can publish an output schema.
# total=False: a success has ok/solved_for/value/unit/formula (+ detail for checks);
# an error has ok/error.
# ---------------------------------------------------------------------------
class ToolResult(TypedDict, total=False):
    ok: bool
    solved_for: str
    value: float | str | bool
    unit: str
    formula: str
    detail: str
    error: str


# ---------------------------------------------------------------------------
# Logging (decision S8): one line per tool call, to stderr.
# With the stdio transport, stdout is the message channel, so nothing may be printed there.
# The arguments are never logged: student text comes from minors and can contain anything.
# ---------------------------------------------------------------------------
logger = logging.getLogger("math-tools")
if not logger.handlers:
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter("%(asctime)s math-tools %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(stderr_handler)
    logger.setLevel(logging.INFO)
    # Keep these lines out of other loggers (for example the app's root logger).
    logger.propagate = False


def log_line(tool_name: str, formula: str | None, result: dict[str, Any], milliseconds: float) -> str:
    """Build the one-line log for a tool call: the tool, the formula, ok, correct and the time. No arguments."""
    line = "tool=" + tool_name
    if formula is not None:
        line = line + " formula=" + formula
    line = line + " ok=" + str(result.get("ok"))
    # For the two checks, also say whether the answer was correct (True/False), but never the answer itself.
    if result.get("solved_for") in ("correct", "equivalent"):
        line = line + " correct=" + str(result.get("value"))
    if result.get("ok") is False:
        short_error = str(result.get("error", ""))[:80]
        line = line + ' error="' + short_error + '"'
    line = line + " ms=" + str(round(milliseconds, 1))
    return line


def run_and_log(tool_name: str, formula: str | None, function: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call a math_tools function, turn any unexpected exception into an error result, and log one line.

    [T4] in the flowchart: whatever happens inside, the caller gets a result dict, never a crash.
    """
    started = time.perf_counter()
    try:
        result = function(**arguments)
    except Exception as error:  # any unexpected problem becomes a structured error (capstone guide p.3)
        result = math_tools.make_error("Unexpected problem in " + tool_name + ": " + type(error).__name__ + ": " + str(error))
    milliseconds = (time.perf_counter() - started) * 1000
    logger.info(log_line(tool_name, formula, result, milliseconds))
    return result


# ---------------------------------------------------------------------------
# The formula catalogues (decision S1, option C): formula name -> the math_tools function,
# its input names, whether it needs a length_unit, and a one-line summary for the model.
# ---------------------------------------------------------------------------
OPTICS_FORMULAS: dict[str, dict[str, Any]] = {
    "mirror_formula": {
        "function": math_tools.solve_mirror_formula, "inputs": ["u", "v", "f"], "needs_length_unit": True,
        "summary": "1/v + 1/u = 1/f (Eq. 9.1). Give 2 of u, v, f. u is negative; concave f negative, convex f positive",
    },
    "lens_formula": {
        "function": math_tools.solve_lens_formula, "inputs": ["u", "v", "f"], "needs_length_unit": True,
        "summary": "1/v - 1/u = 1/f (Eq. 9.8). Give 2 of u, v, f. u is negative; convex f positive, concave f negative",
    },
    "focal_length_from_radius": {
        "function": math_tools.focal_length_from_radius, "inputs": ["radius_of_curvature"], "needs_length_unit": True,
        "summary": "f = R / 2 for a mirror, keeping the sign of R",
    },
    "mirror_magnification": {
        "function": math_tools.solve_mirror_magnification, "inputs": ["m", "v", "u"], "needs_length_unit": True,
        "summary": "m = -v / u (Eq. 9.3). Give 2 of m, v, u. A real image has m < 0",
    },
    "lens_magnification": {
        "function": math_tools.solve_lens_magnification, "inputs": ["m", "v", "u"], "needs_length_unit": True,
        "summary": "m = v / u (Eq. 9.10). Give 2 of m, v, u. A real image has m < 0",
    },
    "image_height": {
        "function": math_tools.solve_image_height, "inputs": ["m", "h_object", "h_image"], "needs_length_unit": True,
        "summary": "m = h' / h (Eq. 9.2, 9.9). Give 2 of m, h_object, h_image. h_object is positive",
    },
    "image_nature": {
        "function": math_tools.describe_image, "inputs": ["m"], "needs_length_unit": False,
        "summary": "the image's nature from m: real/virtual, inverted/erect, enlarged/same size/diminished",
    },
    "lens_power": {
        "function": math_tools.solve_lens_power, "inputs": ["p", "f"], "needs_length_unit": True,
        "summary": "P = 1 / f in dioptres (Eq. 9.11). Give 1 of p (D), f (in length_unit; converted to metres inside)",
    },
    "combine_lens_powers": {
        "function": math_tools.combine_lens_powers, "inputs": ["powers"], "needs_length_unit": False,
        "summary": "P = P1 + P2 + ... for lenses in contact. powers is a list of at least 2 values in D",
    },
    "absolute_refractive_index": {
        "function": math_tools.solve_absolute_refractive_index, "inputs": ["n", "v"], "needs_length_unit": False,
        "summary": "n = c / v, c = 3 x 10^8 m/s (Eq. 9.7). Give 1 of n, v (m/s)",
    },
    "relative_refractive_index": {
        "function": math_tools.solve_relative_refractive_index, "inputs": ["n21", "v1", "v2"], "needs_length_unit": False,
        "summary": "n21 = v1 / v2 (Eq. 9.5). Give 2 of n21, v1, v2 (m/s); light goes from medium 1 into 2",
    },
    "relative_index_from_absolute": {
        "function": math_tools.solve_relative_index_from_absolute, "inputs": ["n21", "n1", "n2"], "needs_length_unit": False,
        "summary": "n21 = n2 / n1 from two absolute indices (e.g. Table 9.3). Give 2 of n21, n1, n2",
    },
}

ELECTRICITY_FORMULAS: dict[str, dict[str, Any]] = {
    "charge_current": {
        "function": math_tools.solve_charge_current, "inputs": ["q", "i", "t"],
        "summary": "Q = I x t (Eq. 11.1). Give 2 of q (C), i (A), t (s)",
    },
    "voltage_work_charge": {
        "function": math_tools.solve_voltage_work_charge, "inputs": ["v", "w", "q"],
        "summary": "V = W / Q (Eq. 11.2). Give 2 of v (V), w (work, J), q (C). In a resistor, heat = V x Q",
    },
    "ohms_law": {
        "function": math_tools.solve_ohms_law, "inputs": ["v", "i", "r"],
        "summary": "V = I x R (Eq. 11.5). Give 2 of v (V), i (A), r (ohm)",
    },
    "resistivity": {
        "function": math_tools.solve_resistivity, "inputs": ["r", "rho", "length", "area"],
        "summary": "R = rho x length / area (Eq. 11.10). Give 3 of r (ohm), rho (ohm m), length (m), area (m^2)",
    },
    "wire_area": {
        "function": math_tools.wire_area, "inputs": ["diameter", "radius"],
        "summary": "A = pi d^2 / 4 or pi r^2. Give 1 of diameter, radius (m)",
    },
    "series_resistance": {
        "function": math_tools.solve_series_resistance, "inputs": ["resistors"],
        "summary": "Rs = R1 + R2 + ... (section 11.6.1). resistors is a list of at least 2 values in ohm",
    },
    "parallel_resistance": {
        "function": math_tools.solve_parallel_resistance, "inputs": ["resistors"],
        "summary": "1/Rp = 1/R1 + 1/R2 + ... (section 11.6.2). resistors is a list of at least 2 values in ohm",
    },
    "joule_heating": {
        "function": math_tools.solve_joule_heating, "inputs": ["h", "i", "r", "t"],
        "summary": "H = I^2 x R x t (Eq. 11.21). Give 3 of h (J), i (A), r (ohm), t (s)",
    },
    "power_voltage_current": {
        "function": math_tools.solve_power_voltage_current, "inputs": ["p", "v", "i"],
        "summary": "P = V x I (Eq. 11.22). Give 2 of p (W), v (V), i (A)",
    },
    "power_current_resistance": {
        "function": math_tools.solve_power_current_resistance, "inputs": ["p", "i", "r"],
        "summary": "P = I^2 x R (Eq. 11.22). Give 2 of p (W), i (A), r (ohm)",
    },
    "power_voltage_resistance": {
        "function": math_tools.solve_power_voltage_resistance, "inputs": ["p", "v", "r"],
        "summary": "P = V^2 / R (Eq. 11.22). Give 2 of p (W), v (V), r (ohm). A rating like 220 V, 100 W gives R",
    },
    "energy_power_time": {
        "function": math_tools.solve_energy_power_time, "inputs": ["energy", "p", "t"],
        "summary": "energy = P x t (section 11.8). Give 2 of energy (J), p (W), t (s)",
    },
    "energy_cost": {
        "function": math_tools.solve_energy_cost, "inputs": ["energy", "rate", "cost"],
        "summary": "cost = energy in kW h x rate. Give 2 of energy (J), rate (Rs per kW h), cost (Rs)",
    },
}

# The formula names as fixed lists, so the JSON schema only accepts these names (an "enum").
OpticsFormula = Literal[
    "mirror_formula", "lens_formula", "focal_length_from_radius", "mirror_magnification",
    "lens_magnification", "image_height", "image_nature", "lens_power", "combine_lens_powers",
    "absolute_refractive_index", "relative_refractive_index", "relative_index_from_absolute",
]
ElectricityFormula = Literal[
    "charge_current", "voltage_work_charge", "ohms_law", "resistivity", "wire_area",
    "series_resistance", "parallel_resistance", "joule_heating", "power_voltage_current",
    "power_current_resistance", "power_voltage_resistance", "energy_power_time", "energy_cost",
]


def catalogue_text(catalogue: dict[str, dict[str, Any]]) -> str:
    """One line per formula, "name: summary (inputs: a, b, c)", for a tool's description."""
    lines: list[str] = []
    for name in catalogue:
        entry = catalogue[name]
        lines.append("- " + name + ": " + entry["summary"] + " (inputs: " + ", ".join(entry["inputs"]) + ")")
    return "\n".join(lines)


SOLVE_OPTICS_DESCRIPTION = (
    "Solve one NCERT Class 10 optics formula (Ch 9; lens power also for Ch 10 spectacles) exactly, in code.\n"
    "Pick the formula by name, give the KNOWN values in `values` (leave the unknown one out), and the\n"
    "length unit of all distances in `length_unit` (for example \"cm\" or \"m\"); the answer is in that unit.\n"
    "Use the New Cartesian sign convention: the object is on the left, so u is negative.\n"
    "Formulas:\n" + catalogue_text(OPTICS_FORMULAS)
)

SOLVE_ELECTRICITY_DESCRIPTION = (
    "Solve one NCERT Class 10 electricity formula (Ch 11) exactly, in code.\n"
    "Pick the formula by name and give the KNOWN values in `values` (leave the unknown one out).\n"
    "All values in SI units (V, A, ohm, s, C, J, W, m); convert other units first with convert_to_si.\n"
    "For a mixed circuit, combine each group first, then the groups.\n"
    "Formulas:\n" + catalogue_text(ELECTRICITY_FORMULAS)
)


def solve_from_catalogue(
    tool_name: str,
    catalogue: dict[str, dict[str, Any]],
    formula: str,
    values: dict[str, Any],
    length_unit: str | None,
) -> dict[str, Any]:
    """The `solve` flowchart ([T0]-[T4], [R]): check the formula and value names, then call the Stage 1 function."""
    # [T0] the formula must be in the catalogue. (Through MCP the schema already enforces this;
    # the check also protects direct Python calls.)
    if formula not in catalogue:
        known = ", ".join(catalogue)
        return math_tools.make_error("Unknown formula '" + formula + "'. Known formulas: " + known + ".")
    entry = catalogue[formula]

    # [T1] every given value must be one of this formula's inputs.
    for name in values:
        if name not in entry["inputs"]:
            allowed = ", ".join(entry["inputs"])
            return math_tools.make_error(formula + " takes " + allowed + "; '" + name + "' is not one of them.")

    # Build the call's arguments from the given values.
    arguments: dict[str, Any] = {}
    for name in values:
        arguments[name] = values[name]

    # [T2] distance-based optics formulas need the length unit; the others must not get one.
    if entry.get("needs_length_unit", False):
        if length_unit is None:
            return math_tools.make_error(formula + " needs length_unit (the unit of the distances, for example \"cm\").")
        arguments["length_unit"] = length_unit

    # [T3] + [T4] call the Stage 1 function; its own checks still run inside it.
    # [R] its result comes back unchanged.
    return run_and_log(tool_name, formula, entry["function"], arguments)


# ---------------------------------------------------------------------------
# The server and its 7 tools. All are read-only (decision S2): they calculate and change nothing.
# ---------------------------------------------------------------------------
mcp = MCPServer(
    "math-tools",
    instructions=(
        "Exact calculations and answer checks for NCERT Class 10 physics (Ch 9-11). "
        "Never do arithmetic yourself: call these tools."
    ),
)

# The guide's read/write mark (capstone guide p.3): these tools only read; they change nothing.
READ_ONLY = ToolAnnotations(readOnlyHint=True)


@mcp.tool(description=SOLVE_OPTICS_DESCRIPTION, annotations=READ_ONLY)
def solve_optics(
    formula: OpticsFormula,
    values: dict[str, float | list[float]],
    length_unit: str | None = None,
) -> ToolResult:
    return solve_from_catalogue("solve_optics", OPTICS_FORMULAS, formula, values, length_unit)


@mcp.tool(description=SOLVE_ELECTRICITY_DESCRIPTION, annotations=READ_ONLY)
def solve_electricity(formula: ElectricityFormula, values: dict[str, float | list[float]]) -> ToolResult:
    return solve_from_catalogue("solve_electricity", ELECTRICITY_FORMULAS, formula, values, None)


@mcp.tool(description=math_tools.convert_to_si.__doc__, annotations=READ_ONLY)
def convert_to_si(value: float, unit: str) -> ToolResult:
    return run_and_log("convert_to_si", None, math_tools.convert_to_si, {"value": value, "unit": unit})


@mcp.tool(description=math_tools.convert_from_si.__doc__, annotations=READ_ONLY)
def convert_from_si(si_value: float, unit: str) -> ToolResult:
    return run_and_log("convert_from_si", None, math_tools.convert_from_si, {"si_value": si_value, "unit": unit})


@mcp.tool(description=math_tools.calculate.__doc__, annotations=READ_ONLY)
def calculate(expression: str) -> ToolResult:
    return run_and_log("calculate", None, math_tools.calculate, {"expression": expression})


@mcp.tool(description=math_tools.check_numeric_answer.__doc__, annotations=READ_ONLY)
def check_numeric_answer(student_text: str, gold_text: str, tolerance: float = 0.02) -> ToolResult:
    arguments = {"student_text": student_text, "gold_text": gold_text, "tolerance": tolerance}
    return run_and_log("check_numeric_answer", None, math_tools.check_numeric_answer, arguments)


@mcp.tool(description=math_tools.check_equivalence.__doc__, annotations=READ_ONLY)
def check_equivalence(student_text: str, gold_text: str) -> ToolResult:
    arguments = {"student_text": student_text, "gold_text": gold_text}
    return run_and_log("check_equivalence", None, math_tools.check_equivalence, arguments)


if __name__ == "__main__":
    # stdio transport (development, capstone guide p.5). HTTP for Docker comes later.
    mcp.run(transport="stdio")
