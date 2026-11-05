"""Tests for the math-tools calculator: shared helpers, unit conversion, I = Q / t, V = W / Q, Ohm's law and resistivity.

Worked examples and exercises come from NCERT Class 10 Science, Chapter 11 "Electricity" (2026-27 reprint).
"""

import math

import pytest

from socratic_tutor.tools import math_tools


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def test_make_result_builds_the_success_shape() -> None:
    """A success result carries ok=True, the quantity, its exact value, its unit and the formula."""
    result = math_tools.make_result("I", 0.002, "A", "I = V / R")
    assert result == {"ok": True, "solved_for": "I", "value": 0.002, "unit": "A", "formula": "I = V / R"}


def test_make_error_builds_the_error_shape() -> None:
    """An error result carries ok=False and a plain-words message under the key 'error'."""
    result = math_tools.make_error("Resistance R must be greater than 0.")
    assert result == {"ok": False, "error": "Resistance R must be greater than 0."}


def test_count_given_counts_values_that_are_not_none() -> None:
    """Only None means 'not given'; every other value is counted."""
    assert math_tools.count_given([2.0, None, 1000.0]) == 2
    assert math_tools.count_given([None, None, None]) == 0
    assert math_tools.count_given([10.0, 2.0, 4.0]) == 3


def test_count_given_counts_a_zero_as_given() -> None:
    """A 0 is a value the caller typed in, so it must be counted (unlike `if value:`, which would skip it)."""
    assert math_tools.count_given([0.0, None, 5.0]) == 2


def test_find_zero_or_negative_returns_the_first_bad_name() -> None:
    """The first given value that is 0 or negative is reported by its name."""
    names = ["Charge Q", "Current I", "Time t"]
    assert math_tools.find_zero_or_negative(names, [5.0, None, -3.0]) == "Time t"
    assert math_tools.find_zero_or_negative(names, [0.0, 2.0, None]) == "Charge Q"


def test_find_zero_or_negative_returns_none_when_every_given_value_is_positive() -> None:
    """Missing values (None) are skipped, and positive values pass."""
    names = ["Potential difference V", "Current I", "Resistance R"]
    assert math_tools.find_zero_or_negative(names, [2.0, None, 1000.0]) is None


# ---------------------------------------------------------------------------
# Unit conversion: convert_to_si
# ---------------------------------------------------------------------------


def test_convert_millimetres_to_metres() -> None:
    """0.3 mm (the wire in NCERT Example 11.5) is 0.0003 m."""
    result = math_tools.convert_to_si(0.3, "mm")
    assert result["ok"] is True
    assert result["solved_for"] == "length"
    assert result["value"] == pytest.approx(0.0003)
    assert result["unit"] == "m"


def test_convert_keeps_negative_values() -> None:
    """Optics uses signed distances, so -30 cm must become -0.3 m, not an error."""
    result = math_tools.convert_to_si(-30, "cm")
    assert result["ok"] is True
    assert result["value"] == pytest.approx(-0.3)


def test_convert_minutes_and_hours_to_seconds() -> None:
    """10 min is 600 s (NCERT Example 11.1) and 2 h is 7200 s."""
    assert math_tools.convert_to_si(10, "min")["value"] == pytest.approx(600.0)
    assert math_tools.convert_to_si(2, "h")["value"] == pytest.approx(7200.0)
    assert math_tools.convert_to_si(10, "min")["unit"] == "s"


def test_convert_milliamps_and_microamps_to_amperes() -> None:
    """1 mA = 0.001 A and 1 uA = 0.000001 A (NCERT section 11.1); both look-alike micro signs are accepted."""
    assert math_tools.convert_to_si(2, "mA")["value"] == pytest.approx(0.002)
    assert math_tools.convert_to_si(5, "uA")["value"] == pytest.approx(0.000005)
    # "µ" is the micro sign and "μ" is the Greek letter mu: they look the same on screen.
    assert math_tools.convert_to_si(5, "µA")["value"] == pytest.approx(0.000005)
    assert math_tools.convert_to_si(5, "μA")["value"] == pytest.approx(0.000005)


def test_convert_kilowatt_hours_to_joules() -> None:
    """1 kW h = 3.6 x 10^6 J (NCERT section 11.8), written with or without the space."""
    assert math_tools.convert_to_si(1, "kWh")["value"] == pytest.approx(3600000.0)
    assert math_tools.convert_to_si(1, "kW h")["value"] == pytest.approx(3600000.0)
    assert math_tools.convert_to_si(1, "kWh")["unit"] == "J"


def test_convert_accepts_unit_words_with_any_capitals() -> None:
    """Words have no capital-letter meaning, so 'Minutes', 'Ohms' and 'millimetre' are all accepted."""
    assert math_tools.convert_to_si(10, "Minutes")["value"] == pytest.approx(600.0)
    assert math_tools.convert_to_si(26, "Ohms")["value"] == pytest.approx(26.0)
    assert math_tools.convert_to_si(0.3, "millimetre")["value"] == pytest.approx(0.0003)


def test_convert_ignores_spaces_around_the_unit() -> None:
    """' mA ' is read as 'mA'."""
    assert math_tools.convert_to_si(2, " mA ")["value"] == pytest.approx(0.002)


def test_convert_capital_letters_matter_for_symbols() -> None:
    """'MA' (mega-ampere) and 'MV' are not silently read as 'mA' and 'mV': they are refused."""
    mega_amp = math_tools.convert_to_si(2, "MA")
    mega_volt = math_tools.convert_to_si(2, "MV")
    assert mega_amp["ok"] is False
    assert mega_volt["ok"] is False


def test_convert_rejects_an_unknown_unit_and_lists_the_known_ones() -> None:
    """An unknown unit is refused, and the message lists the accepted symbols so the caller can retry."""
    result = math_tools.convert_to_si(3, "furlong")
    assert result["ok"] is False
    assert "furlong" in result["error"]
    assert "mm" in result["error"]


# ---------------------------------------------------------------------------
# A5: current and charge, I = Q / t (NCERT Eq. 11.1)
# ---------------------------------------------------------------------------


def test_charge_from_current_and_time_ncert_example_11_1() -> None:
    """NCERT Example 11.1: 0.5 A for 10 minutes (600 s) carries 300 C."""
    result = math_tools.solve_charge_current(i=0.5, t=600)
    assert result["ok"] is True
    assert result["solved_for"] == "Q"
    assert result["value"] == pytest.approx(300.0)
    assert result["unit"] == "C"
    assert result["formula"] == "Q = I x t"


def test_current_from_charge_and_time() -> None:
    """300 C in 600 s is a current of 0.5 A."""
    result = math_tools.solve_charge_current(q=300, t=600)
    assert result["ok"] is True
    assert result["solved_for"] == "I"
    assert result["value"] == pytest.approx(0.5)
    assert result["unit"] == "A"


def test_time_from_charge_and_current() -> None:
    """300 C at 0.5 A takes 600 s."""
    result = math_tools.solve_charge_current(q=300, i=0.5)
    assert result["ok"] is True
    assert result["solved_for"] == "t"
    assert result["value"] == pytest.approx(600.0)
    assert result["unit"] == "s"


def test_charge_current_rejects_zero_time() -> None:
    """A time of 0 is refused with a clear message instead of a crash."""
    result = math_tools.solve_charge_current(q=10, t=0)
    assert result["ok"] is False
    assert "Time t" in result["error"]


def test_charge_current_rejects_zero_current_when_finding_time() -> None:
    """Finding t = Q / I with I = 0 would divide by zero, so it is refused."""
    result = math_tools.solve_charge_current(q=10, i=0)
    assert result["ok"] is False
    assert "Current I" in result["error"]


def test_charge_current_rejects_negative_time() -> None:
    """A negative time makes no sense, so it is refused."""
    result = math_tools.solve_charge_current(i=2, t=-5)
    assert result["ok"] is False
    assert "Time t" in result["error"]


def test_charge_current_needs_exactly_two_values() -> None:
    """Three values, or only one, is refused."""
    three_given = math_tools.solve_charge_current(q=1, i=1, t=1)
    one_given = math_tools.solve_charge_current(q=1)
    assert three_given["ok"] is False
    assert one_given["ok"] is False
    assert "exactly two" in three_given["error"]


# ---------------------------------------------------------------------------
# A6: potential difference, V = W / Q (NCERT Eq. 11.2)
# ---------------------------------------------------------------------------


def test_work_from_voltage_and_charge_ncert_example_11_2() -> None:
    """NCERT Example 11.2: moving 2 C across 12 V takes 24 J of work."""
    result = math_tools.solve_voltage_work_charge(v=12, q=2)
    assert result["ok"] is True
    assert result["solved_for"] == "W"
    assert result["value"] == pytest.approx(24.0)
    assert result["unit"] == "J"
    assert result["formula"] == "W = V x Q"


def test_voltage_from_work_and_charge() -> None:
    """24 J of work to move 2 C means a potential difference of 12 V."""
    result = math_tools.solve_voltage_work_charge(w=24, q=2)
    assert result["ok"] is True
    assert result["solved_for"] == "V"
    assert result["value"] == pytest.approx(12.0)
    assert result["unit"] == "V"
    assert result["formula"] == "V = W / Q"


def test_charge_from_work_and_voltage() -> None:
    """24 J of work across 12 V moves 2 C of charge."""
    result = math_tools.solve_voltage_work_charge(w=24, v=12)
    assert result["ok"] is True
    assert result["solved_for"] == "Q"
    assert result["value"] == pytest.approx(2.0)
    assert result["unit"] == "C"
    assert result["formula"] == "Q = W / V"


def test_voltage_work_charge_rejects_zero_charge() -> None:
    """Finding V = W / Q with Q = 0 would divide by zero, so it is refused."""
    result = math_tools.solve_voltage_work_charge(w=24, q=0)
    assert result["ok"] is False
    assert "Charge Q" in result["error"]


def test_voltage_work_charge_rejects_zero_voltage_when_finding_charge() -> None:
    """Finding Q = W / V with V = 0 would divide by zero, so it is refused."""
    result = math_tools.solve_voltage_work_charge(w=24, v=0)
    assert result["ok"] is False
    assert "Potential difference V" in result["error"]


def test_voltage_work_charge_rejects_negative_work() -> None:
    """A negative amount of work done is refused."""
    result = math_tools.solve_voltage_work_charge(w=-5, q=1)
    assert result["ok"] is False
    assert "Work done W" in result["error"]


def test_voltage_work_charge_needs_exactly_two_values() -> None:
    """Three values, or only one, is refused."""
    three_given = math_tools.solve_voltage_work_charge(v=1, w=1, q=1)
    one_given = math_tools.solve_voltage_work_charge(v=1)
    assert three_given["ok"] is False
    assert one_given["ok"] is False
    assert "exactly two" in three_given["error"]


# ---------------------------------------------------------------------------
# A7: Ohm's law, V = I x R (NCERT Eq. 11.5-11.7)
# ---------------------------------------------------------------------------


def test_ohms_law_current_ncert_example_11_3() -> None:
    """NCERT Example 11.3(a): 220 V across 1200 ohm gives 0.1833... A (NCERT rounds it to 0.18 A)."""
    result = math_tools.solve_ohms_law(v=220, r=1200)
    assert result["ok"] is True
    assert result["solved_for"] == "I"
    assert result["value"] == pytest.approx(220 / 1200)
    assert result["unit"] == "A"
    assert result["formula"] == "I = V / R"


def test_ohms_law_resistance_ncert_example_11_4() -> None:
    """NCERT Example 11.4: 60 V and 4 A give 15 ohm."""
    result = math_tools.solve_ohms_law(v=60, i=4)
    assert result["ok"] is True
    assert result["solved_for"] == "R"
    assert result["value"] == pytest.approx(15.0)
    assert result["unit"] == "ohm"


def test_ohms_law_voltage_from_current_and_resistance() -> None:
    """0.5 A through 12 ohm needs 6 V."""
    result = math_tools.solve_ohms_law(i=0.5, r=12)
    assert result["ok"] is True
    assert result["solved_for"] == "V"
    assert result["value"] == pytest.approx(6.0)
    assert result["unit"] == "V"


def test_ohms_law_keeps_a_small_current_exact() -> None:
    """2 V across 1000 ohm is 0.002 A (2 mA). The old draft rounded this to 0.0."""
    result = math_tools.solve_ohms_law(v=2, r=1000)
    assert result["ok"] is True
    assert result["value"] == pytest.approx(0.002)
    assert result["value"] != 0.0


def test_ohms_law_rejects_zero_resistance() -> None:
    """R = 0 is refused with a clear message instead of a ZeroDivisionError."""
    result = math_tools.solve_ohms_law(v=5, r=0)
    assert result["ok"] is False
    assert "Resistance R" in result["error"]


def test_ohms_law_rejects_zero_current_when_finding_resistance() -> None:
    """Finding R = V / I with I = 0 would divide by zero, so it is refused."""
    result = math_tools.solve_ohms_law(v=5, i=0)
    assert result["ok"] is False
    assert "Current I" in result["error"]


def test_ohms_law_rejects_a_negative_value() -> None:
    """A negative potential difference is refused."""
    result = math_tools.solve_ohms_law(v=-5, r=10)
    assert result["ok"] is False
    assert "Potential difference V" in result["error"]


def test_ohms_law_needs_exactly_two_values() -> None:
    """Three values (which may even contradict each other), or only one, is refused."""
    three_given = math_tools.solve_ohms_law(v=10, i=2, r=4)
    one_given = math_tools.solve_ohms_law(v=10)
    assert three_given["ok"] is False
    assert one_given["ok"] is False
    assert "exactly two" in three_given["error"]


# ---------------------------------------------------------------------------
# A8: wire area and resistivity, R = rho x length / area (NCERT Eq. 11.10)
# ---------------------------------------------------------------------------


def test_wire_area_from_diameter_ncert_example_11_5() -> None:
    """A wire of diameter 0.3 mm (0.0003 m) has a cross-sectional area of pi x d^2 / 4."""
    result = math_tools.wire_area(diameter=0.0003)
    assert result["ok"] is True
    assert result["solved_for"] == "area"
    assert result["value"] == pytest.approx(math.pi * 0.0003 * 0.0003 / 4)
    assert result["unit"] == "m^2"


def test_wire_area_from_radius_matches_the_diameter() -> None:
    """A radius of 0.00015 m is the same wire as a diameter of 0.0003 m, so the area is the same."""
    from_radius = math_tools.wire_area(radius=0.00015)
    from_diameter = math_tools.wire_area(diameter=0.0003)
    assert from_radius["ok"] is True
    assert from_radius["value"] == pytest.approx(from_diameter["value"])
    assert from_radius["formula"] == "A = pi x r^2"


def test_wire_area_needs_exactly_one_of_diameter_or_radius() -> None:
    """Giving both, or neither, is refused."""
    both_given = math_tools.wire_area(diameter=0.0003, radius=0.00015)
    neither_given = math_tools.wire_area()
    assert both_given["ok"] is False
    assert neither_given["ok"] is False


def test_wire_area_rejects_zero_or_negative() -> None:
    """A diameter or radius must be greater than 0."""
    assert math_tools.wire_area(radius=0)["ok"] is False
    assert math_tools.wire_area(diameter=-1)["ok"] is False


def test_resistivity_ncert_example_11_5() -> None:
    """NCERT Example 11.5: a 1 m wire of 26 ohm and diameter 0.3 mm has resistivity 1.84 x 10^-6 ohm m."""
    area = math_tools.wire_area(diameter=0.0003)["value"]
    result = math_tools.solve_resistivity(r=26, length=1, area=area)
    assert result["ok"] is True
    assert result["solved_for"] == "rho"
    # NCERT gives the answer to 3 significant figures, so allow a 1% difference.
    assert result["value"] == pytest.approx(1.84e-6, rel=0.01)
    assert result["unit"] == "ohm m"


def test_resistivity_ncert_exercise_6_full_chain() -> None:
    """NCERT Exercise 6: copper, d = 0.5 mm, rho = 1.6 x 10^-8 ohm m, R = 10 ohm -> a length of about 122.7 m.

    This runs the three calls in the order the agent would make them.
    """
    diameter = math_tools.convert_to_si(0.5, "mm")
    area = math_tools.wire_area(diameter=diameter["value"])
    result = math_tools.solve_resistivity(r=10, rho=1.6e-8, area=area["value"])
    assert result["ok"] is True
    assert result["solved_for"] == "length"
    assert result["value"] == pytest.approx(122.7, rel=0.001)
    assert result["unit"] == "m"


def test_resistivity_doubling_the_diameter_quarters_the_resistance() -> None:
    """NCERT Exercise 6, second part: doubling the diameter makes the area 4 times bigger, so R becomes 10 / 4 = 2.5 ohm."""
    thin_area = math_tools.wire_area(diameter=0.0005)["value"]
    length = math_tools.solve_resistivity(r=10, rho=1.6e-8, area=thin_area)["value"]
    thick_area = math_tools.wire_area(diameter=0.001)["value"]
    result = math_tools.solve_resistivity(rho=1.6e-8, length=length, area=thick_area)
    assert result["ok"] is True
    assert result["solved_for"] == "R"
    assert result["value"] == pytest.approx(2.5)


def test_resistivity_finds_the_area() -> None:
    """rho = 1.6 x 10^-8 ohm m, length = 1 m and R = 0.16 ohm need an area of 10^-7 m^2."""
    result = math_tools.solve_resistivity(r=0.16, rho=1.6e-8, length=1)
    assert result["ok"] is True
    assert result["solved_for"] == "area"
    assert result["value"] == pytest.approx(1e-7)
    assert result["unit"] == "m^2"


def test_resistivity_needs_exactly_three_values() -> None:
    """Two values, or all four, is refused."""
    two_given = math_tools.solve_resistivity(r=26, length=1)
    four_given = math_tools.solve_resistivity(r=26, rho=1e-6, length=1, area=1e-7)
    assert two_given["ok"] is False
    assert four_given["ok"] is False
    assert "exactly three" in two_given["error"]


def test_resistivity_rejects_a_zero_length() -> None:
    """A length of 0 is refused instead of dividing by zero."""
    result = math_tools.solve_resistivity(r=26, rho=1e-6, length=0)
    assert result["ok"] is False
    assert "Length" in result["error"]
