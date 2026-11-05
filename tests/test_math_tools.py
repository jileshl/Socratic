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


# ---------------------------------------------------------------------------
# A9: resistors in series and in parallel (NCERT sections 11.6.1 and 11.6.2)
# ---------------------------------------------------------------------------


def test_resistor_names_count_from_one() -> None:
    """Error messages name resistors the way people do: Resistor 1, Resistor 2, ..."""
    assert math_tools.resistor_names(3) == ["Resistor 1", "Resistor 2", "Resistor 3"]


def test_series_ncert_example_11_7() -> None:
    """NCERT Example 11.7: a 20 ohm lamp and a 4 ohm conductor in series give 24 ohm."""
    result = math_tools.solve_series_resistance([20, 4])
    assert result["ok"] is True
    assert result["solved_for"] == "Rs"
    assert result["value"] == pytest.approx(24.0)
    assert result["unit"] == "ohm"
    assert result["formula"] == "Rs = R1 + R2 + ..."


def test_series_is_bigger_than_every_resistor() -> None:
    """5, 10 and 30 ohm in series give 45 ohm, which is bigger than the biggest one (30 ohm)."""
    result = math_tools.solve_series_resistance([5, 10, 30])
    assert result["value"] == pytest.approx(45.0)
    assert result["value"] > 30


def test_parallel_ncert_example_11_8() -> None:
    """NCERT Example 11.8: 5, 10 and 30 ohm in parallel give 3 ohm, smaller than the smallest one (5 ohm).

    The computer returns 2.9999999999999996, because 1/30 cannot be stored exactly as a float,
    so the value is compared with pytest.approx, never with ==.
    """
    result = math_tools.solve_parallel_resistance([5, 10, 30])
    assert result["ok"] is True
    assert result["solved_for"] == "Rp"
    assert result["value"] == pytest.approx(3.0)
    assert result["value"] < 5
    assert result["formula"] == "1/Rp = 1/R1 + 1/R2 + ..."


def test_parallel_of_two_equal_resistors_is_half() -> None:
    """Two equal resistors in parallel give half of one: 4 and 4 give 2 ohm, 6 and 6 give 3 ohm."""
    assert math_tools.solve_parallel_resistance([4, 4])["value"] == pytest.approx(2.0)
    assert math_tools.solve_parallel_resistance([6, 6])["value"] == pytest.approx(3.0)


def test_mixed_circuit_ncert_example_11_9() -> None:
    """NCERT Example 11.9: (10 || 40) in series with (30 || 20 || 60) is 8 + 10 = 18 ohm; on 12 V, I = 0.67 A.

    This runs the calls in the order the agent would make them.
    """
    group_1 = math_tools.solve_parallel_resistance([10, 40])
    group_2 = math_tools.solve_parallel_resistance([30, 20, 60])
    total = math_tools.solve_series_resistance([group_1["value"], group_2["value"]])
    current = math_tools.solve_ohms_law(v=12, r=total["value"])
    assert group_1["value"] == pytest.approx(8.0)
    assert group_2["value"] == pytest.approx(10.0)
    assert total["value"] == pytest.approx(18.0)
    assert current["value"] == pytest.approx(0.67, rel=0.01)


def test_series_and_parallel_need_at_least_two_resistors() -> None:
    """One resistor, or an empty list, is not a combination, so it is refused."""
    assert math_tools.solve_series_resistance([5])["ok"] is False
    assert math_tools.solve_parallel_resistance([])["ok"] is False
    assert "at least 2" in math_tools.solve_series_resistance([5])["error"]


def test_series_and_parallel_name_the_bad_resistor() -> None:
    """A zero or negative resistor is refused, and the error says which one it is."""
    with_a_zero = math_tools.solve_parallel_resistance([5, 0, 10])
    with_a_negative = math_tools.solve_series_resistance([5, -2])
    assert with_a_zero["ok"] is False
    assert "Resistor 2" in with_a_zero["error"]
    assert with_a_negative["ok"] is False
    assert "Resistor 2" in with_a_negative["error"]


# ---------------------------------------------------------------------------
# A10: Joule's law of heating H = I^2 x R x t (NCERT section 11.7)
# ---------------------------------------------------------------------------


def test_joule_heating_ncert_section_11_7_question_3() -> None:
    """NCERT section 11.7, Question 3: an iron of 20 ohm takes 5 A for 30 s, so H = 5^2 x 20 x 30 = 15 000 J."""
    result = math_tools.solve_joule_heating(i=5, r=20, t=30)
    assert result["ok"] is True
    assert result["solved_for"] == "H"
    assert result["value"] == pytest.approx(15000.0)
    assert result["unit"] == "J"
    assert result["formula"] == "H = I^2 x R x t"


def test_joule_heating_ncert_example_11_11_chain() -> None:
    """NCERT Example 11.11: 100 J each second in 4 ohm. I = sqrt(100 / (4 x 1)) = 5 A, then V = I x R = 20 V.

    This runs the calls in the order NCERT's solution takes: Joule's law (square-root branch), then Ohm's law.
    """
    current = math_tools.solve_joule_heating(h=100, r=4, t=1)
    voltage = math_tools.solve_ohms_law(i=current["value"], r=4)
    assert current["ok"] is True
    assert current["solved_for"] == "I"
    assert current["value"] == pytest.approx(5.0)
    assert current["formula"] == "I = sqrt(H / (R x t))"
    assert voltage["value"] == pytest.approx(20.0)


def test_joule_heating_finds_the_resistance_and_the_time() -> None:
    """Section 11.7, Question 3 the other way round: 15 000 J at 5 A gives R = 20 ohm (in 30 s) and t = 30 s (in 20 ohm)."""
    resistance = math_tools.solve_joule_heating(h=15000, i=5, t=30)
    time_taken = math_tools.solve_joule_heating(h=15000, i=5, r=20)
    assert resistance["solved_for"] == "R"
    assert resistance["value"] == pytest.approx(20.0)
    assert resistance["unit"] == "ohm"
    assert time_taken["solved_for"] == "t"
    assert time_taken["value"] == pytest.approx(30.0)
    assert time_taken["unit"] == "s"


def test_joule_heating_needs_exactly_three_values() -> None:
    """Two values, or all four, cannot be solved."""
    only_two = math_tools.solve_joule_heating(i=5, r=20)
    all_four = math_tools.solve_joule_heating(h=15000, i=5, r=20, t=30)
    assert only_two["ok"] is False
    assert all_four["ok"] is False
    assert "exactly three" in only_two["error"]


def test_joule_heating_refuses_a_negative_or_zero_before_the_square_root() -> None:
    """A negative resistance or a zero time gets an error instead of crashing math.sqrt or dividing by zero."""
    negative = math_tools.solve_joule_heating(h=100, r=-4, t=1)
    zero_time = math_tools.solve_joule_heating(h=100, r=4, t=0)
    assert negative["ok"] is False
    assert "Resistance R" in negative["error"]
    assert zero_time["ok"] is False
    assert "Time t" in zero_time["error"]


# ---------------------------------------------------------------------------
# A11: electric power, energy and its cost (NCERT section 11.8)
# ---------------------------------------------------------------------------


def test_power_from_voltage_and_current_ncert_example_11_12() -> None:
    """NCERT Example 11.12: a bulb on 220 V takes 0.50 A, so P = 220 x 0.50 = 110 W."""
    result = math_tools.solve_power_voltage_current(v=220, i=0.5)
    assert result["ok"] is True
    assert result["solved_for"] == "P"
    assert result["value"] == pytest.approx(110.0)
    assert result["unit"] == "W"
    assert result["formula"] == "P = V x I"


def test_power_finds_the_current_ncert_example_11_10() -> None:
    """NCERT Example 11.10: an iron on 220 V uses 840 W at most and 360 W at least, so I = 3.82 A and 1.64 A."""
    most = math_tools.solve_power_voltage_current(p=840, v=220)
    least = math_tools.solve_power_voltage_current(p=360, v=220)
    assert most["solved_for"] == "I"
    assert most["unit"] == "A"
    assert most["formula"] == "I = P / V"
    assert most["value"] == pytest.approx(3.82, rel=0.01)
    assert least["value"] == pytest.approx(1.64, rel=0.01)


def test_power_finds_the_voltage() -> None:
    """NCERT Example 11.12 the other way round: 110 W at 0.50 A means V = 220 V."""
    result = math_tools.solve_power_voltage_current(p=110, i=0.5)
    assert result["solved_for"] == "V"
    assert result["value"] == pytest.approx(220.0)
    assert result["unit"] == "V"


def test_fuse_current_ncert_section_11_7_1() -> None:
    """NCERT section 11.7.1: a 1 kW iron on 220 V draws 1000 / 220 = 4.54 A (so a 5 A fuse is used).

    The agent first converts 1 kW to watts, then asks for the current.
    """
    power = math_tools.convert_to_si(1, "kW")
    current = math_tools.solve_power_voltage_current(p=power["value"], v=220)
    assert power["value"] == pytest.approx(1000.0)
    assert current["value"] == pytest.approx(4.54, rel=0.01)
    assert current["value"] < 5


def test_power_voltage_current_needs_exactly_two_values() -> None:
    """One value, or all three, cannot be solved."""
    only_one = math_tools.solve_power_voltage_current(v=220)
    all_three = math_tools.solve_power_voltage_current(p=110, v=220, i=0.5)
    assert only_one["ok"] is False
    assert all_three["ok"] is False
    assert "exactly two" in only_one["error"]


def test_power_voltage_current_refuses_a_zero_current() -> None:
    """A zero current is refused, because finding V would divide by it."""
    result = math_tools.solve_power_voltage_current(p=110, i=0)
    assert result["ok"] is False
    assert "Current I" in result["error"]


def test_power_from_current_and_resistance_ncert_exercise_17() -> None:
    """NCERT Exercise 17: a heater of 44 ohm draws 5 A, so heat is produced at P = 5^2 x 44 = 1100 W."""
    result = math_tools.solve_power_current_resistance(i=5, r=44)
    assert result["ok"] is True
    assert result["solved_for"] == "P"
    assert result["value"] == pytest.approx(1100.0)
    assert result["unit"] == "W"
    assert result["formula"] == "P = I^2 x R"


def test_power_finds_the_current_with_a_square_root() -> None:
    """NCERT Example 11.11: 100 J each second (100 W) in a 4 ohm resistor gives I = sqrt(100 / 4) = 5 A."""
    result = math_tools.solve_power_current_resistance(p=100, r=4)
    assert result["ok"] is True
    assert result["solved_for"] == "I"
    assert result["value"] == pytest.approx(5.0)
    assert result["unit"] == "A"
    assert result["formula"] == "I = sqrt(P / R)"


def test_power_finds_the_resistance() -> None:
    """NCERT Exercise 17 the other way round: 1100 W at 5 A means R = 1100 / 5^2 = 44 ohm."""
    result = math_tools.solve_power_current_resistance(p=1100, i=5)
    assert result["ok"] is True
    assert result["solved_for"] == "R"
    assert result["value"] == pytest.approx(44.0)
    assert result["unit"] == "ohm"
    assert result["formula"] == "R = P / I^2"


def test_power_in_one_resistor_ncert_exercise_14_chain() -> None:
    """NCERT Exercise 14(i): 6 V across 1 ohm and 2 ohm in series. The power used in the 2 ohm resistor is 8 W.

    This runs the calls in the order the agent would make them: series, then Ohm's law, then power.
    """
    total = math_tools.solve_series_resistance([1, 2])
    current = math_tools.solve_ohms_law(v=6, r=total["value"])
    power = math_tools.solve_power_current_resistance(i=current["value"], r=2)
    assert total["value"] == pytest.approx(3.0)
    assert current["value"] == pytest.approx(2.0)
    assert power["value"] == pytest.approx(8.0)


def test_power_needs_exactly_two_values() -> None:
    """One value, or all three, cannot be solved."""
    only_one = math_tools.solve_power_current_resistance(i=5)
    all_three = math_tools.solve_power_current_resistance(p=1100, i=5, r=44)
    assert only_one["ok"] is False
    assert all_three["ok"] is False
    assert "exactly two" in only_one["error"]


def test_power_refuses_a_negative_or_zero_before_the_square_root() -> None:
    """A negative or zero resistance gets an error instead of crashing math.sqrt or dividing by zero."""
    negative = math_tools.solve_power_current_resistance(p=100, r=-4)
    zero = math_tools.solve_power_current_resistance(p=100, r=0)
    assert negative["ok"] is False
    assert "Resistance R" in negative["error"]
    assert zero["ok"] is False
    assert "Resistance R" in zero["error"]


def test_power_rating_gives_the_resistance_ncert_exercise_3_chain() -> None:
    """NCERT Exercise 3: a bulb rated 220 V, 100 W has R = 220^2 / 100 = 484 ohm. On 110 V it uses 110^2 / 484 = 25 W.

    The resistance stays the same, so half the voltage gives a quarter of the power, not half (50 W).
    """
    resistance = math_tools.solve_power_voltage_resistance(p=100, v=220)
    power = math_tools.solve_power_voltage_resistance(v=110, r=resistance["value"])
    assert resistance["solved_for"] == "R"
    assert resistance["value"] == pytest.approx(484.0)
    assert resistance["unit"] == "ohm"
    assert resistance["formula"] == "R = V^2 / P"
    assert power["solved_for"] == "P"
    assert power["value"] == pytest.approx(25.0)
    assert power["unit"] == "W"
    assert power["formula"] == "P = V^2 / R"


def test_power_finds_the_resistance_exactly_ncert_example_11_10() -> None:
    """NCERT Example 11.10: the iron's resistance at 840 W and 360 W on 220 V.

    NCERT rounds the current first and prints 57.60 ohm and 134.15 ohm. In one call, with no rounding,
    the exact values are 220^2 / 840 = 57.62 ohm and 220^2 / 360 = 134.44 ohm. They are within 0.1 % and
    0.5 % of NCERT's printed values, which is why the grader's numeric check needs a tolerance.
    """
    most = math_tools.solve_power_voltage_resistance(p=840, v=220)
    least = math_tools.solve_power_voltage_resistance(p=360, v=220)
    assert most["value"] == pytest.approx(48400 / 840)
    assert most["value"] == pytest.approx(57.60, rel=0.001)
    assert least["value"] == pytest.approx(48400 / 360)
    assert least["value"] == pytest.approx(134.15, rel=0.005)


def test_power_finds_the_voltage_with_a_square_root() -> None:
    """NCERT Example 11.11 in one call: 100 J each second (100 W) in 4 ohm gives V = sqrt(100 x 4) = 20 V."""
    result = math_tools.solve_power_voltage_resistance(p=100, r=4)
    assert result["ok"] is True
    assert result["solved_for"] == "V"
    assert result["value"] == pytest.approx(20.0)
    assert result["unit"] == "V"
    assert result["formula"] == "V = sqrt(P x R)"


def test_power_in_a_parallel_resistor_ncert_exercise_14_ii() -> None:
    """NCERT Exercise 14(ii): 4 V across 12 ohm and 2 ohm in parallel. The 2 ohm resistor has the full 4 V, so P = 4^2 / 2 = 8 W."""
    result = math_tools.solve_power_voltage_resistance(v=4, r=2)
    assert result["value"] == pytest.approx(8.0)


def test_power_voltage_resistance_needs_exactly_two_values() -> None:
    """One value, or all three, cannot be solved."""
    only_one = math_tools.solve_power_voltage_resistance(v=220)
    all_three = math_tools.solve_power_voltage_resistance(p=100, v=220, r=484)
    assert only_one["ok"] is False
    assert all_three["ok"] is False
    assert "exactly two" in only_one["error"]


def test_power_voltage_resistance_refuses_a_negative_before_the_square_root() -> None:
    """A negative resistance gets an error instead of crashing math.sqrt."""
    result = math_tools.solve_power_voltage_resistance(p=100, r=-4)
    assert result["ok"] is False
    assert "Resistance R" in result["error"]


def test_energy_ncert_section_11_8_question_2_chain() -> None:
    """NCERT section 11.8, Question 2: a motor takes 5 A from 220 V, so P = 1100 W; in 2 h it uses 1100 x 7200 = 7.92 x 10^6 J.

    This runs the calls in the order the agent would make them: power, convert 2 h to seconds, then energy.
    """
    power = math_tools.solve_power_voltage_current(v=220, i=5)
    time_taken = math_tools.convert_to_si(2, "h")
    energy = math_tools.solve_energy_power_time(p=power["value"], t=time_taken["value"])
    assert power["value"] == pytest.approx(1100.0)
    assert time_taken["value"] == pytest.approx(7200.0)
    assert energy["ok"] is True
    assert energy["solved_for"] == "energy"
    assert energy["value"] == pytest.approx(7.92e6)
    assert energy["unit"] == "J"
    assert energy["formula"] == "energy = P x t"


def test_energy_and_cost_ncert_example_11_13_full_chain() -> None:
    """NCERT Example 11.13: a 400 W fridge, 8 h a day for 30 days, uses 96 kW h; at Rs 3.00 per kW h that is Rs 288.

    "8 h a day for 30 days" is 8 x 30 = 240 h. That multiplication sits between calls; the test does it here
    until a general calculate tool exists (decision D4, Batch 4).
    """
    time_taken = math_tools.convert_to_si(8 * 30, "h")
    energy = math_tools.solve_energy_power_time(p=400, t=time_taken["value"])
    cost = math_tools.solve_energy_cost(energy=energy["value"], rate=3.00)
    assert time_taken["value"] == pytest.approx(864000.0)
    assert energy["value"] == pytest.approx(3.456e8)
    assert cost["value"] == pytest.approx(288.0)


def test_energy_ncert_exercise_16() -> None:
    """NCERT Exercise 16: a 250 W TV for 1 h uses 9.0 x 10^5 J; a 1200 W toaster for 10 min uses 7.2 x 10^5 J. The TV uses more."""
    tv_time = math_tools.convert_to_si(1, "h")
    toaster_time = math_tools.convert_to_si(10, "min")
    tv = math_tools.solve_energy_power_time(p=250, t=tv_time["value"])
    toaster = math_tools.solve_energy_power_time(p=1200, t=toaster_time["value"])
    assert tv["value"] == pytest.approx(9.0e5)
    assert toaster["value"] == pytest.approx(7.2e5)
    assert tv["value"] > toaster["value"]


def test_energy_finds_the_power_and_the_time() -> None:
    """100 J each second is 100 W (NCERT Example 11.11); 7.92 x 10^6 J at 1100 W takes 7200 s (section 11.8, Question 2)."""
    power = math_tools.solve_energy_power_time(energy=100, t=1)
    time_taken = math_tools.solve_energy_power_time(energy=7.92e6, p=1100)
    assert power["solved_for"] == "P"
    assert power["value"] == pytest.approx(100.0)
    assert power["unit"] == "W"
    assert time_taken["solved_for"] == "t"
    assert time_taken["value"] == pytest.approx(7200.0)
    assert time_taken["unit"] == "s"


def test_energy_power_time_needs_exactly_two_values() -> None:
    """One value, or all three, cannot be solved."""
    only_one = math_tools.solve_energy_power_time(p=400)
    all_three = math_tools.solve_energy_power_time(energy=100, p=100, t=1)
    assert only_one["ok"] is False
    assert all_three["ok"] is False
    assert "exactly two" in only_one["error"]


def test_energy_power_time_refuses_a_zero_time() -> None:
    """A zero time is refused, because finding P would divide by it."""
    result = math_tools.solve_energy_power_time(energy=100, t=0)
    assert result["ok"] is False
    assert "Time t" in result["error"]


def test_energy_cost_ncert_example_11_13() -> None:
    """NCERT Example 11.13: the fridge uses 96 kW h; at Rs 3.00 per kW h that costs Rs 288.

    The agent first converts 96 kW h to joules (SI), then asks for the cost.
    """
    energy = math_tools.convert_to_si(96, "kWh")
    result = math_tools.solve_energy_cost(energy=energy["value"], rate=3.00)
    assert energy["value"] == pytest.approx(3.456e8)
    assert result["ok"] is True
    assert result["solved_for"] == "cost"
    assert result["value"] == pytest.approx(288.0)
    assert result["unit"] == "Rs"
    assert result["formula"] == "cost = (energy / 3.6e6 J per kW h) x rate"


def test_energy_cost_finds_the_energy() -> None:
    """Rs 288 paid at Rs 3.00 per kW h means 96 kW h were used, which is 3.456 x 10^8 J (the SI unit)."""
    result = math_tools.solve_energy_cost(rate=3.00, cost=288)
    assert result["ok"] is True
    assert result["solved_for"] == "energy"
    assert result["value"] == pytest.approx(3.456e8)
    assert result["unit"] == "J"


def test_energy_cost_finds_the_rate() -> None:
    """Rs 288 for 3.456 x 10^8 J (96 kW h) means the rate was Rs 3.00 per kW h."""
    result = math_tools.solve_energy_cost(energy=3.456e8, cost=288)
    assert result["ok"] is True
    assert result["solved_for"] == "rate"
    assert result["value"] == pytest.approx(3.0)
    assert result["unit"] == "Rs per kW h"


def test_energy_cost_one_unit_costs_the_rate() -> None:
    """1 kW h (3.6 x 10^6 J) costs exactly the rate. This checks the joules-to-kW h factor."""
    result = math_tools.solve_energy_cost(energy=3.6e6, rate=5.0)
    assert result["value"] == pytest.approx(5.0)


def test_energy_cost_needs_exactly_two_values() -> None:
    """One value alone cannot be solved."""
    only_one = math_tools.solve_energy_cost(rate=3.00)
    assert only_one["ok"] is False
    assert "exactly two" in only_one["error"]


def test_energy_cost_refuses_a_zero_rate() -> None:
    """A zero rate is refused, because finding the energy would divide by it."""
    result = math_tools.solve_energy_cost(rate=0, cost=288)
    assert result["ok"] is False
    assert "Rate" in result["error"]
