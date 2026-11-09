"""Tests for the math-tools MCP server: the tool list, one test per tool, and the solve flowchart.

Most tests talk to the server in-process with the official SDK's Client (the same "tools/list" and
"tools/call" messages an agent sends, without a subprocess). One test runs the server as a real
subprocess over stdio, written exactly like the Lecture 7 hands-on client (stdio_client + ClientSession).
MCP clients are asynchronous, so asyncio.run is used inside ordinary test functions (no pytest plugin).
"""

import asyncio
import inspect
import sys
import typing
from typing import Any

import pytest
from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from socratic_tutor import config
from socratic_tutor.tools import math_tools_server


def list_tools() -> list[Any]:
    """Ask the server for its tools, the way an MCP client does at start-up."""

    async def ask() -> list[Any]:
        async with Client(math_tools_server.mcp) as client:
            listing = await client.list_tools()
            return listing.tools

    return asyncio.run(ask())


def call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call one tool through the client and return its result as a plain dict."""

    async def ask() -> dict[str, Any]:
        async with Client(math_tools_server.mcp) as client:
            result = await client.call_tool(tool_name, arguments)
            return result.structured_content

    return asyncio.run(ask())


# ---------------------------------------------------------------------------
# The tool list (evidence: "a tool list with schemas", capstone guide p.3)
# ---------------------------------------------------------------------------


def test_the_server_lists_exactly_seven_tools() -> None:
    """Decision S1, option C: two topic solvers plus five utilities."""
    names: list[str] = []
    for tool in list_tools():
        names.append(tool.name)
    assert sorted(names) == sorted([
        "solve_optics", "solve_electricity", "convert_to_si", "convert_from_si",
        "calculate", "check_numeric_answer", "check_equivalence",
    ])


def test_every_tool_is_marked_read_only() -> None:
    """Decision S2: math-tools only calculates, so every tool carries readOnlyHint (the guide's read/write mark)."""
    for tool in list_tools():
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True


def test_every_tool_has_a_description_and_schemas() -> None:
    """The model reads the description to decide; the schemas say what goes in and what comes out (AAI-7.pdf p.14, p.34)."""
    for tool in list_tools():
        assert tool.description is not None and len(tool.description) > 20
        assert tool.input_schema["type"] == "object"
        assert "ok" in tool.output_schema["properties"]


def test_formula_names_are_a_fixed_list_in_the_schema() -> None:
    """The schema only accepts the catalogue's names (an "enum"), so a mistyped name never reaches our code."""
    schemas: dict[str, Any] = {}
    for tool in list_tools():
        schemas[tool.name] = tool.input_schema
    optics_names = schemas["solve_optics"]["properties"]["formula"]["enum"]
    electricity_names = schemas["solve_electricity"]["properties"]["formula"]["enum"]
    assert sorted(optics_names) == sorted(math_tools_server.OPTICS_FORMULAS)
    assert sorted(electricity_names) == sorted(math_tools_server.ELECTRICITY_FORMULAS)


def test_solve_descriptions_list_every_formula() -> None:
    """The formula catalogue is written into each solve tool's description, so the model can see what exists."""
    for name in math_tools_server.OPTICS_FORMULAS:
        assert name in math_tools_server.SOLVE_OPTICS_DESCRIPTION
    for name in math_tools_server.ELECTRICITY_FORMULAS:
        assert name in math_tools_server.SOLVE_ELECTRICITY_DESCRIPTION


def test_catalogues_match_the_math_tools_functions() -> None:
    """Every catalogue entry names real inputs of its function, and "needs_length_unit" matches the function."""
    for catalogue in [math_tools_server.OPTICS_FORMULAS, math_tools_server.ELECTRICITY_FORMULAS]:
        for name in catalogue:
            entry = catalogue[name]
            parameters = list(inspect.signature(entry["function"]).parameters)
            for input_name in entry["inputs"]:
                assert input_name in parameters, name + ": " + input_name
            assert entry.get("needs_length_unit", False) == ("length_unit" in parameters), name
    assert list(typing.get_args(math_tools_server.OpticsFormula)) == list(math_tools_server.OPTICS_FORMULAS)
    assert list(typing.get_args(math_tools_server.ElectricityFormula)) == list(math_tools_server.ELECTRICITY_FORMULAS)


# ---------------------------------------------------------------------------
# One test per tool (evidence: "one test per tool", capstone guide p.3)
# ---------------------------------------------------------------------------


def test_tool_solve_optics_ncert_example_9_2() -> None:
    """NCERT Example 9.2: concave mirror, u = -25 cm, f = -15 cm, so v = -37.5 cm."""
    result = call("solve_optics", {"formula": "mirror_formula", "values": {"u": -25, "f": -15}, "length_unit": "cm"})
    assert result["ok"] is True
    assert result["solved_for"] == "v"
    assert result["value"] == pytest.approx(-37.5)
    assert result["unit"] == "cm"


def test_tool_solve_electricity_ohms_law() -> None:
    """Ohm's law: 12 V across 4 ohm gives I = 3 A."""
    result = call("solve_electricity", {"formula": "ohms_law", "values": {"v": 12, "r": 4}})
    assert result["ok"] is True
    assert result["solved_for"] == "I"
    assert result["value"] == pytest.approx(3.0)
    assert result["unit"] == "A"


def test_tool_convert_to_si() -> None:
    """0.5 mm is 0.0005 m (NCERT Ch 11, Exercise 6)."""
    result = call("convert_to_si", {"value": 0.5, "unit": "mm"})
    assert result["ok"] is True
    assert result["value"] == pytest.approx(0.0005)
    assert result["unit"] == "m"


def test_tool_convert_from_si() -> None:
    """3.456 x 10^8 J is 96 kWh (NCERT Example 11.13)."""
    result = call("convert_from_si", {"si_value": 3.456e8, "unit": "kWh"})
    assert result["ok"] is True
    assert result["value"] == pytest.approx(96.0)


def test_tool_calculate() -> None:
    """8 h a day for 30 days, in seconds: 8 * 30 * 3600 = 864 000."""
    result = call("calculate", {"expression": "8 * 30 * 3600"})
    assert result["ok"] is True
    assert result["value"] == pytest.approx(864000.0)


def test_tool_check_numeric_answer() -> None:
    """-0.375 m matches a key of -37.5 cm; the detail says so."""
    result = call("check_numeric_answer", {"student_text": "-0.375 m", "gold_text": "-37.5 cm"})
    assert result["ok"] is True
    assert result["solved_for"] == "correct"
    assert result["value"] is True
    assert "Matches" in result["detail"]


def test_tool_check_equivalence() -> None:
    """R = V/I is the same law as V = IR."""
    result = call("check_equivalence", {"student_text": "R = V/I", "gold_text": "V = IR"})
    assert result["ok"] is True
    assert result["value"] is True


# ---------------------------------------------------------------------------
# The solve flowchart: [T0]-[T4] and every catalogue formula
# ---------------------------------------------------------------------------

# One valid NCERT-style call per formula: (tool, formula, values, length_unit).
EXAMPLE_CALLS: list[tuple[str, str, dict[str, Any], str | None]] = [
    ("solve_optics", "mirror_formula", {"u": -25, "f": -15}, "cm"),
    ("solve_optics", "lens_formula", {"u": -15, "f": 10}, "cm"),
    ("solve_optics", "focal_length_from_radius", {"radius_of_curvature": 30}, "cm"),
    ("solve_optics", "mirror_magnification", {"v": -37.5, "u": -25}, "cm"),
    ("solve_optics", "lens_magnification", {"v": 30, "u": -15}, "cm"),
    ("solve_optics", "image_height", {"m": -2, "h_object": 2}, "cm"),
    ("solve_optics", "image_nature", {"m": -2}, None),
    ("solve_optics", "lens_power", {"f": 25}, "cm"),
    ("solve_optics", "combine_lens_powers", {"powers": [2.0, 0.25]}, None),
    ("solve_optics", "absolute_refractive_index", {"n": 1.5}, None),
    ("solve_optics", "relative_refractive_index", {"v1": 3e8, "v2": 2e8}, None),
    ("solve_optics", "relative_index_from_absolute", {"n1": 1.33, "n2": 1.52}, None),
    ("solve_electricity", "charge_current", {"i": 0.5, "t": 600}, None),
    ("solve_electricity", "voltage_work_charge", {"v": 12, "q": 2}, None),
    ("solve_electricity", "ohms_law", {"v": 12, "r": 4}, None),
    ("solve_electricity", "resistivity", {"r": 10, "rho": 1.6e-8, "area": 1.963e-7}, None),
    ("solve_electricity", "wire_area", {"diameter": 0.0005}, None),
    ("solve_electricity", "series_resistance", {"resistors": [1, 2]}, None),
    ("solve_electricity", "parallel_resistance", {"resistors": [5, 10, 30]}, None),
    ("solve_electricity", "joule_heating", {"i": 5, "r": 20, "t": 30}, None),
    ("solve_electricity", "power_voltage_current", {"v": 220, "i": 0.5}, None),
    ("solve_electricity", "power_current_resistance", {"i": 5, "r": 44}, None),
    ("solve_electricity", "power_voltage_resistance", {"p": 100, "v": 220}, None),
    ("solve_electricity", "energy_power_time", {"p": 1100, "t": 7200}, None),
    ("solve_electricity", "energy_cost", {"energy": 3.456e8, "rate": 3.0}, None),
]


def test_every_catalogue_formula_can_be_called() -> None:
    """All 25 formulas, through the server, give an ok result, and the examples cover every catalogue entry."""
    covered: list[str] = []
    for tool_name, formula, values, length_unit in EXAMPLE_CALLS:
        arguments: dict[str, Any] = {"formula": formula, "values": values}
        if length_unit is not None:
            arguments["length_unit"] = length_unit
        result = call(tool_name, arguments)
        assert result["ok"] is True, formula + ": " + str(result.get("error"))
        covered.append(formula)
    all_formulas = list(math_tools_server.OPTICS_FORMULAS) + list(math_tools_server.ELECTRICITY_FORMULAS)
    assert sorted(covered) == sorted(all_formulas)


def test_unknown_formula_is_rejected_before_our_code() -> None:
    """[T0] through MCP: a name outside the fixed list fails the schema check, as an error result, not a crash."""

    async def ask() -> Any:
        async with Client(math_tools_server.mcp) as client:
            return await client.call_tool("solve_electricity", {"formula": "magic", "values": {}})

    result = asyncio.run(ask())
    assert result.is_error is True


def test_unknown_formula_in_direct_python_call() -> None:
    """[T0] for direct Python calls (no schema in between): a clear error that lists the known formulas."""
    result = math_tools_server.solve_from_catalogue("solve_electricity", math_tools_server.ELECTRICITY_FORMULAS, "magic", {}, None)
    assert result["ok"] is False
    assert "ohms_law" in result["error"]


def test_solve_refuses_a_value_name_the_formula_does_not_take() -> None:
    """[T1]: ohms_law takes v, i and r, so "x" is refused with a message that lists them."""
    result = call("solve_electricity", {"formula": "ohms_law", "values": {"v": 12, "x": 4}})
    assert result["ok"] is False
    assert "v, i, r" in result["error"]


def test_solve_optics_needs_a_length_unit_for_distances() -> None:
    """[T2]: the mirror formula needs to know the unit of u and f; image_nature does not need one."""
    missing = call("solve_optics", {"formula": "mirror_formula", "values": {"u": -25, "f": -15}})
    not_needed = call("solve_optics", {"formula": "image_nature", "values": {"m": -2}})
    assert missing["ok"] is False
    assert "needs length_unit" in missing["error"]
    assert not_needed["ok"] is True


def test_unexpected_problems_become_error_results() -> None:
    """[T4]: a list where a number belongs makes math_tools raise inside; the tool still returns an error result."""
    result = call("solve_electricity", {"formula": "ohms_law", "values": {"v": [1, 2], "r": 4}})
    assert result["ok"] is False
    assert "Unexpected problem" in result["error"]


def test_stage_1_checks_still_run_inside_the_tools() -> None:
    """[T3]: the Stage 1 function's own checks still apply, e.g. a positive u is refused."""
    result = call("solve_optics", {"formula": "mirror_formula", "values": {"u": 25, "f": -15}, "length_unit": "cm"})
    assert result["ok"] is False
    assert "must be negative" in result["error"]


# ---------------------------------------------------------------------------
# Logging (decision S8)
# ---------------------------------------------------------------------------


def test_log_line_has_no_arguments() -> None:
    """The log line names the tool and the outcome, but never the student's text (AAI-14.pdf p.13: scrub traces)."""
    result = {"ok": True, "solved_for": "correct", "value": False, "detail": "Wrong sign: ..."}
    line = math_tools_server.log_line("check_numeric_answer", None, result, 0.8)
    assert line == "tool=check_numeric_answer ok=True correct=False ms=0.8"
    assert "-30" not in line


def test_log_line_for_an_error_is_short() -> None:
    """A failed call logs a shortened error message."""
    result = {"ok": False, "error": "x" * 200}
    line = math_tools_server.log_line("solve_optics", "mirror_formula", result, 0.5)
    assert line.startswith("tool=solve_optics formula=mirror_formula ok=False")
    assert len(line) < 160


# ---------------------------------------------------------------------------
# End to end over stdio, written like the Lecture 7 hands-on client (Lesson 7)
# ---------------------------------------------------------------------------


def test_server_over_stdio_like_the_lecture_client() -> None:
    """Launch the server as a subprocess, then initialize -> discover -> invoke, exactly as in Lesson 7."""

    async def mcp_demo() -> tuple[list[str], dict[str, Any]]:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "socratic_tutor.tools.math_tools_server"],
            # Start in the repository folder (taken from config.py) so "-m socratic_tutor..." can be found.
            cwd=str(config.BASE_DIR),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()                                        # 1. handshake
                tools = await session.list_tools()                                # 2. discover
                names: list[str] = []
                for tool in tools.tools:
                    names.append(tool.name)
                out = await session.call_tool("calculate", {"expression": "8 * 30 * 3600"})  # 3. invoke
                return names, out.structured_content

    names, result = asyncio.run(mcp_demo())
    assert len(names) == 7
    assert "solve_optics" in names
    assert result["ok"] is True
    assert result["value"] == pytest.approx(864000.0)
