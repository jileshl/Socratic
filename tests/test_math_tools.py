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


# ---------------------------------------------------------------------------
# A1 and A2: mirrors and lenses (NCERT Ch 9). Distances are signed and in the caller's length unit.
# ---------------------------------------------------------------------------


def test_find_length_unit_accepts_symbols_and_words() -> None:
    """Length symbols match exactly; words match in any capitals, the same rules as convert_to_si."""
    assert math_tools.find_length_unit("cm") == "cm"
    assert math_tools.find_length_unit(" m ") == "m"
    assert math_tools.find_length_unit("centimetres") == "cm"
    assert math_tools.find_length_unit("Millimetre") == "mm"


def test_find_length_unit_refuses_other_units() -> None:
    """A time, an unknown unit, or a symbol with the wrong capitals is not a length unit."""
    assert math_tools.find_length_unit("s") is None
    assert math_tools.find_length_unit("kg") is None
    assert math_tools.find_length_unit("CM") is None


def test_find_zero_allows_negative_values() -> None:
    """Negative distances are normal in optics; only an exact 0 is reported, by its name."""
    assert math_tools.find_zero(["u", "f"], [-25, -15]) is None
    assert math_tools.find_zero(["u", "v", "f"], [-25, None, 0]) == "f"


def test_mirror_ncert_example_9_2() -> None:
    """NCERT Example 9.2: concave mirror, u = -25.0 cm, f = -15.0 cm, so v = -37.5 cm (in front: real)."""
    result = math_tools.solve_mirror_formula("cm", u=-25, f=-15)
    assert result["ok"] is True
    assert result["solved_for"] == "v"
    assert result["value"] == pytest.approx(-37.5)
    assert result["unit"] == "cm"
    assert result["formula"] == "v = 1 / (1/f - 1/u)"


def test_mirror_ncert_example_9_2_chain() -> None:
    """NCERT Example 9.2 in full: v = -37.5 cm, m = -1.5, image height -6.0 cm (from 4.0 cm), real, inverted, enlarged.

    This runs the calls in the order the agent would make them.
    """
    image = math_tools.solve_mirror_formula("cm", u=-25, f=-15)
    magnification = math_tools.solve_mirror_magnification("cm", v=image["value"], u=-25)
    height = math_tools.solve_image_height("cm", m=magnification["value"], h_object=4.0)
    nature = math_tools.describe_image(magnification["value"])
    assert magnification["value"] == pytest.approx(-1.5)
    assert magnification["unit"] == "no unit"
    assert magnification["formula"] == "m = -v / u"
    assert height["solved_for"] == "h_image"
    assert height["value"] == pytest.approx(-6.0)
    assert height["formula"] == "h' = m x h"
    assert nature["value"] == "real and inverted, enlarged"


def test_mirror_ncert_example_9_1_chain_in_metres() -> None:
    """NCERT Example 9.1: convex mirror, R = +3.00 m, bus at u = -5.00 m. f = 1.50 m, v = +1.15 m, m = +0.23.

    The image is behind the mirror: virtual, erect and diminished. The whole chain works in metres.
    """
    focal = math_tools.focal_length_from_radius("m", 3.00)
    image = math_tools.solve_mirror_formula("m", u=-5.00, f=focal["value"])
    magnification = math_tools.solve_mirror_magnification("m", v=image["value"], u=-5.00)
    nature = math_tools.describe_image(magnification["value"])
    assert focal["value"] == pytest.approx(1.50)
    assert image["value"] == pytest.approx(1.15, rel=0.01)
    assert image["unit"] == "m"
    assert magnification["value"] == pytest.approx(0.23, rel=0.01)
    assert nature["value"] == "virtual and erect, diminished"


def test_mirror_ncert_exercise_12_convex() -> None:
    """NCERT Exercise 12: object 10 cm from a convex mirror of focal length 15 cm, so v = +6 cm (behind: virtual)."""
    result = math_tools.solve_mirror_formula("cm", u=-10, f=15)
    assert result["value"] == pytest.approx(6.0)


def test_mirror_finds_u_and_f() -> None:
    """Exercise 12 and Example 9.2 the other way round: v = +6, f = +15 gives u = -10; u = -25, v = -37.5 gives f = -15."""
    object_distance = math_tools.solve_mirror_formula("cm", v=6, f=15)
    focal = math_tools.solve_mirror_formula("cm", u=-25, v=-37.5)
    assert object_distance["solved_for"] == "u"
    assert object_distance["value"] == pytest.approx(-10.0)
    assert object_distance["formula"] == "u = 1 / (1/f - 1/v)"
    assert focal["solved_for"] == "f"
    assert focal["value"] == pytest.approx(-15.0)
    assert focal["formula"] == "f = 1 / (1/v + 1/u)"


def test_mirror_gives_the_same_image_in_cm_and_in_m() -> None:
    """Example 9.2 in metres (u = -0.25 m, f = -0.15 m) gives -0.375 m, which is the same -37.5 cm."""
    in_cm = math_tools.solve_mirror_formula("cm", u=-25, f=-15)
    in_m = math_tools.solve_mirror_formula("m", u=-0.25, f=-0.15)
    assert in_m["value"] == pytest.approx(-0.375)
    assert in_m["value"] * 100 == pytest.approx(in_cm["value"])


def test_mirror_refuses_a_positive_u() -> None:
    """Example 9.2 with the sign forgotten (u = +25) would quietly give v = -9.375 cm. It is refused instead."""
    result = math_tools.solve_mirror_formula("cm", u=25, f=-15)
    assert result["ok"] is False
    assert "must be negative" in result["error"]
    assert "u = -25" in result["error"]


def test_mirror_infinity_cases_get_a_clear_message() -> None:
    """Object at the focus: image at infinity. Image at the focus: object at infinity. v = -u: a plane mirror."""
    object_at_focus = math_tools.solve_mirror_formula("cm", u=-15, f=-15)
    image_at_focus = math_tools.solve_mirror_formula("cm", v=-15, f=-15)
    plane_mirror = math_tools.solve_mirror_formula("cm", u=-20, v=20)
    assert object_at_focus["ok"] is False
    assert "image forms at infinity" in object_at_focus["error"]
    assert image_at_focus["ok"] is False
    assert "object is at infinity" in image_at_focus["error"]
    assert plane_mirror["ok"] is False
    assert "plane mirror" in plane_mirror["error"]


def test_mirror_refuses_an_image_no_real_object_gives() -> None:
    """A convex mirror (f = +15 cm) cannot give a real image in front of it (v = -10 cm): the calculated u is +6."""
    result = math_tools.solve_mirror_formula("cm", v=-10, f=15)
    assert result["ok"] is False
    assert "No real object" in result["error"]


def test_mirror_needs_exactly_two_values_and_no_zero() -> None:
    """One value cannot be solved, and a focal length of 0 is refused by name."""
    only_one = math_tools.solve_mirror_formula("cm", u=-25)
    zero_focal = math_tools.solve_mirror_formula("cm", u=-25, f=0)
    assert only_one["ok"] is False
    assert "exactly two" in only_one["error"]
    assert zero_focal["ok"] is False
    assert "Focal length f" in zero_focal["error"]


def test_optics_refuses_a_unit_that_is_not_a_length() -> None:
    """length_unit must be a length: a time ("s") or an unknown unit ("kg") is refused."""
    time_unit = math_tools.solve_mirror_formula("s", u=-25, f=-15)
    unknown_unit = math_tools.solve_lens_formula("kg", u=-15, f=10)
    assert time_unit["ok"] is False
    assert "length unit" in time_unit["error"]
    assert unknown_unit["ok"] is False


def test_lens_ncert_example_9_4_chain() -> None:
    """NCERT Example 9.4: convex lens, f = +10 cm, u = -15 cm, h = 2.0 cm. v = +30 cm, m = -2, h' = -4.0 cm.

    The image is on the other side of the lens: real, inverted and enlarged.
    """
    image = math_tools.solve_lens_formula("cm", u=-15, f=10)
    magnification = math_tools.solve_lens_magnification("cm", v=image["value"], u=-15)
    height = math_tools.solve_image_height("cm", m=magnification["value"], h_object=2.0)
    nature = math_tools.describe_image(magnification["value"])
    assert image["solved_for"] == "v"
    assert image["value"] == pytest.approx(30.0)
    assert image["formula"] == "v = 1 / (1/f + 1/u)"
    assert magnification["value"] == pytest.approx(-2.0)
    assert magnification["formula"] == "m = v / u"
    assert height["value"] == pytest.approx(-4.0)
    assert nature["value"] == "real and inverted, enlarged"


def test_lens_ncert_example_9_3_finds_u() -> None:
    """NCERT Example 9.3: concave lens, f = -15 cm, image at v = -10 cm. u = -30 cm and m = +0.33: virtual, erect, diminished."""
    object_distance = math_tools.solve_lens_formula("cm", v=-10, f=-15)
    magnification = math_tools.solve_lens_magnification("cm", v=-10, u=object_distance["value"])
    nature = math_tools.describe_image(magnification["value"])
    assert object_distance["solved_for"] == "u"
    assert object_distance["value"] == pytest.approx(-30.0)
    assert object_distance["formula"] == "u = 1 / (1/v - 1/f)"
    assert magnification["value"] == pytest.approx(1 / 3)
    assert nature["value"] == "virtual and erect, diminished"


def test_lens_ncert_exercise_10() -> None:
    """NCERT Exercise 10: a 5 cm object 25 cm from a converging lens of f = 10 cm. v = +16.7 cm, m = -0.67, h' = -3.3 cm."""
    image = math_tools.solve_lens_formula("cm", u=-25, f=10)
    magnification = math_tools.solve_lens_magnification("cm", v=image["value"], u=-25)
    height = math_tools.solve_image_height("cm", m=magnification["value"], h_object=5)
    assert image["value"] == pytest.approx(50 / 3)
    assert magnification["value"] == pytest.approx(-2 / 3)
    assert height["value"] == pytest.approx(-10 / 3)


def test_lens_finds_f_ncert_section_9_3_8_question_2() -> None:
    """NCERT section 9.3.8, Question 2: a same-size real image 50 cm away means u = -50 cm, v = +50 cm, so f = +25 cm."""
    result = math_tools.solve_lens_formula("cm", u=-50, v=50)
    assert result["solved_for"] == "f"
    assert result["value"] == pytest.approx(25.0)
    assert result["formula"] == "f = 1 / (1/v - 1/u)"


def test_lens_refuses_a_positive_u_and_explains_infinity() -> None:
    """A positive u is refused; object at the focus, image at the focus and v = u each get a clear message."""
    positive_u = math_tools.solve_lens_formula("cm", u=15, f=10)
    object_at_focus = math_tools.solve_lens_formula("cm", u=-10, f=10)
    image_at_focus = math_tools.solve_lens_formula("cm", v=10, f=10)
    no_lens = math_tools.solve_lens_formula("cm", u=-20, v=-20)
    assert positive_u["ok"] is False
    assert "u = -15" in positive_u["error"]
    assert "image forms at infinity" in object_at_focus["error"]
    assert "object is at infinity" in image_at_focus["error"]
    assert "no lens" in no_lens["error"]


def test_lens_refuses_an_image_no_real_object_gives() -> None:
    """A convex lens (f = +10 cm) cannot form a real image at v = +5 cm, closer than f: the calculated u is +10."""
    result = math_tools.solve_lens_formula("cm", v=5, f=10)
    assert result["ok"] is False
    assert "No real object" in result["error"]


def test_mirror_magnification_ncert_section_9_2_question_2() -> None:
    """NCERT section 9.2, Question 2: a real image three times the size, object at 10 cm. m = -3, u = -10 cm, so v = -30 cm."""
    result = math_tools.solve_mirror_magnification("cm", m=-3, u=-10)
    assert result["solved_for"] == "v"
    assert result["value"] == pytest.approx(-30.0)
    assert result["unit"] == "cm"
    assert result["formula"] == "v = -m x u"


def test_mirror_magnification_finds_u_and_refuses_a_mismatch() -> None:
    """m = -1.5 with v = -37.5 cm gives u = -25 cm (Example 9.2). A virtual m = +2 with v in front (-10 cm) fits no real object."""
    object_distance = math_tools.solve_mirror_magnification("cm", m=-1.5, v=-37.5)
    mismatch = math_tools.solve_mirror_magnification("cm", m=2, v=-10)
    assert object_distance["value"] == pytest.approx(-25.0)
    assert object_distance["formula"] == "u = -v / m"
    assert mismatch["ok"] is False
    assert "No real object" in mismatch["error"]


def test_lens_magnification_finds_v_and_u() -> None:
    """Example 9.4 the other ways round: m = -2, u = -15 gives v = +30; m = -2, v = +30 gives u = -15; v = -30 fits no real object."""
    image_distance = math_tools.solve_lens_magnification("cm", m=-2, u=-15)
    object_distance = math_tools.solve_lens_magnification("cm", m=-2, v=30)
    mismatch = math_tools.solve_lens_magnification("cm", m=-2, v=-30)
    assert image_distance["value"] == pytest.approx(30.0)
    assert image_distance["formula"] == "v = m x u"
    assert object_distance["value"] == pytest.approx(-15.0)
    assert mismatch["ok"] is False


def test_magnification_refuses_a_positive_u_and_a_zero() -> None:
    """Both magnification functions refuse a positive u, and an m of 0."""
    mirror_positive_u = math_tools.solve_mirror_magnification("cm", v=-30, u=10)
    lens_zero_m = math_tools.solve_lens_magnification("cm", m=0, u=-15)
    assert mirror_positive_u["ok"] is False
    assert "must be negative" in mirror_positive_u["error"]
    assert lens_zero_m["ok"] is False
    assert "Magnification m" in lens_zero_m["error"]


def test_image_height_finds_m_and_the_object_height() -> None:
    """Example 9.2: h' = -6.0 cm from h = 4.0 cm gives m = -1.5. Example 9.4: m = -2 and h' = -4.0 cm give h = 2.0 cm."""
    magnification = math_tools.solve_image_height("cm", h_object=4.0, h_image=-6.0)
    object_height = math_tools.solve_image_height("cm", m=-2, h_image=-4.0)
    assert magnification["solved_for"] == "m"
    assert magnification["value"] == pytest.approx(-1.5)
    assert magnification["formula"] == "m = h' / h"
    assert object_height["solved_for"] == "h_object"
    assert object_height["value"] == pytest.approx(2.0)
    assert object_height["unit"] == "cm"


def test_image_height_refuses_a_negative_object_height() -> None:
    """The object stands above the axis (h > 0), whether h is given or calculated."""
    given_negative = math_tools.solve_image_height("cm", m=-2, h_object=-4)
    calculated_negative = math_tools.solve_image_height("cm", m=-2, h_image=4)
    assert given_negative["ok"] is False
    assert "positive" in given_negative["error"]
    assert calculated_negative["ok"] is False


def test_mirror_ncert_exercise_15_full_chain() -> None:
    """NCERT Exercise 15: a 7.0 cm object 27 cm from a concave mirror of f = 18 cm. v = -54 cm, m = -2, h' = -14 cm."""
    image = math_tools.solve_mirror_formula("cm", u=-27, f=-18)
    magnification = math_tools.solve_mirror_magnification("cm", v=image["value"], u=-27)
    height = math_tools.solve_image_height("cm", m=magnification["value"], h_object=7.0)
    nature = math_tools.describe_image(magnification["value"])
    assert image["value"] == pytest.approx(-54.0)
    assert magnification["value"] == pytest.approx(-2.0)
    assert height["value"] == pytest.approx(-14.0)
    assert nature["value"] == "real and inverted, enlarged"


def test_mirror_ncert_exercise_14_full_chain() -> None:
    """NCERT Exercise 14: a 5.0 cm object 20 cm from a convex mirror with R = 30 cm.

    f = +15 cm, v = +8.57 cm, m = +0.43, h' = +2.14 cm: virtual, erect and diminished.
    """
    focal = math_tools.focal_length_from_radius("cm", 30)
    image = math_tools.solve_mirror_formula("cm", u=-20, f=focal["value"])
    magnification = math_tools.solve_mirror_magnification("cm", v=image["value"], u=-20)
    height = math_tools.solve_image_height("cm", m=magnification["value"], h_object=5.0)
    nature = math_tools.describe_image(magnification["value"])
    assert focal["value"] == pytest.approx(15.0)
    assert image["value"] == pytest.approx(60 / 7)
    assert magnification["value"] == pytest.approx(3 / 7)
    assert height["value"] == pytest.approx(15 / 7)
    assert nature["value"] == "virtual and erect, diminished"


def test_focal_length_from_radius_keeps_the_sign() -> None:
    """NCERT section 9.2, Question 1: a convex mirror with R = +32 cm has f = +16 cm. A concave R = -30 cm gives f = -15 cm."""
    convex = math_tools.focal_length_from_radius("cm", 32)
    concave = math_tools.focal_length_from_radius("cm", -30)
    zero = math_tools.focal_length_from_radius("cm", 0)
    assert convex["solved_for"] == "f"
    assert convex["value"] == pytest.approx(16.0)
    assert convex["formula"] == "f = R / 2"
    assert concave["value"] == pytest.approx(-15.0)
    assert zero["ok"] is False


def test_describe_image_same_size_despite_float_noise() -> None:
    """|m| = 1 is "same size" even when the computer gives 1.0000000000000002 (an object at 2F)."""
    real = math_tools.describe_image(-1.0000000000000002)
    virtual = math_tools.describe_image(1.0)
    assert real["ok"] is True
    assert real["solved_for"] == "nature"
    assert real["value"] == "real and inverted, same size"
    assert virtual["value"] == "virtual and erect, same size"


def test_describe_image_refuses_zero() -> None:
    """A magnification of 0 describes no image, so it is refused."""
    result = math_tools.describe_image(0)
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# A3 and A4: power of a lens, and refractive index (NCERT Ch 9, sections 9.3.8 and 9.3.2; Ch 10)
# ---------------------------------------------------------------------------


def test_convert_speeds_and_dioptres_to_si() -> None:
    """The unit table now knows speeds and the dioptre: 72 km/h = 20 m/s, 3 km/s = 3000 m/s, 1.5 dioptres = 1.5 D."""
    kmh = math_tools.convert_to_si(72, "km/h")
    kms = math_tools.convert_to_si(3, "km/s")
    word = math_tools.convert_to_si(3e8, "metres per second")
    ncert_style = math_tools.convert_to_si(3e8, "m s^-1")
    dioptre = math_tools.convert_to_si(1.5, "dioptres")
    assert kmh["solved_for"] == "speed"
    assert kmh["value"] == pytest.approx(20.0)
    assert kmh["unit"] == "m/s"
    assert kms["value"] == pytest.approx(3000.0)
    assert word["value"] == pytest.approx(3e8)
    assert ncert_style["value"] == pytest.approx(3e8)
    assert dioptre["value"] == pytest.approx(1.5)
    assert dioptre["unit"] == "D"


def test_lens_power_ncert_section_9_3_8_question_2_chain() -> None:
    """NCERT section 9.3.8, Question 2: a same-size real image 50 cm away gives f = +25 cm, so P = +4 D."""
    focal = math_tools.solve_lens_formula("cm", u=-50, v=50)
    power = math_tools.solve_lens_power("cm", f=focal["value"])
    assert focal["value"] == pytest.approx(25.0)
    assert power["ok"] is True
    assert power["solved_for"] == "P"
    assert power["value"] == pytest.approx(4.0)
    assert power["unit"] == "D"
    assert power["formula"] == "P = 1 / f (f in metres)"


def test_lens_power_avoids_the_unit_trap() -> None:
    """f = 25 cm and f = 0.25 m are the same lens: both give +4 D. The wrong answer 1/25 = 0.04 never appears."""
    in_cm = math_tools.solve_lens_power("cm", f=25)
    in_m = math_tools.solve_lens_power("m", f=0.25)
    assert in_cm["value"] == pytest.approx(4.0)
    assert in_m["value"] == pytest.approx(4.0)
    assert in_cm["value"] != pytest.approx(0.04)


def test_focal_length_from_power_ncert_examples() -> None:
    """Section 9.3.8: +2.0 D means f = +0.50 m and -2.5 D means f = -0.40 m. Exercise 16: -2.0 D is f = -50 cm (concave)."""
    convex = math_tools.solve_lens_power("m", p=2.0)
    concave = math_tools.solve_lens_power("m", p=-2.5)
    exercise_16 = math_tools.solve_lens_power("cm", p=-2.0)
    assert convex["solved_for"] == "f"
    assert convex["value"] == pytest.approx(0.50)
    assert convex["unit"] == "m"
    assert concave["value"] == pytest.approx(-0.40)
    assert exercise_16["value"] == pytest.approx(-50.0)
    assert exercise_16["unit"] == "cm"


def test_lens_power_ncert_section_9_3_8_question_3_and_exercise_17() -> None:
    """Question 3: a concave lens of f = 2 m has P = -0.5 D. Exercise 17: +1.5 D gives f = +0.67 m (converging)."""
    concave = math_tools.solve_lens_power("m", f=-2)
    exercise_17 = math_tools.solve_lens_power("m", p=1.5)
    assert concave["value"] == pytest.approx(-0.5)
    assert exercise_17["value"] == pytest.approx(2 / 3)


def test_lens_power_ncert_chapter_10_exercise_7_chain() -> None:
    """Ch 10, Exercise 7: a hypermetropic near point of 1 m, normal near point 25 cm.

    The lens must form the image of an object at 25 cm at the near point: u = -25 cm, v = -100 cm,
    so f = +33.3 cm and P = +3.0 D (a convex lens).
    """
    focal = math_tools.solve_lens_formula("cm", u=-25, v=-100)
    power = math_tools.solve_lens_power("cm", f=focal["value"])
    assert focal["value"] == pytest.approx(100 / 3)
    assert power["value"] == pytest.approx(3.0)


def test_lens_power_ncert_chapter_10_exercise_5() -> None:
    """Ch 10, Exercise 5: -5.5 D for distant vision is f = -18.2 cm; +1.5 D for near vision is f = +66.7 cm."""
    distant = math_tools.solve_lens_power("cm", p=-5.5)
    near = math_tools.solve_lens_power("cm", p=1.5)
    assert distant["value"] == pytest.approx(-100 / 5.5)
    assert near["value"] == pytest.approx(100 / 1.5)


def test_lens_power_refuses_bad_input() -> None:
    """Both values or neither, a zero, or a unit that is not a length are all refused."""
    both = math_tools.solve_lens_power("cm", p=4, f=25)
    neither = math_tools.solve_lens_power("cm")
    zero = math_tools.solve_lens_power("cm", f=0)
    time_unit = math_tools.solve_lens_power("s", f=25)
    assert both["ok"] is False
    assert "exactly one" in both["error"]
    assert neither["ok"] is False
    assert zero["ok"] is False
    assert "Focal length f" in zero["error"]
    assert time_unit["ok"] is False


def test_combine_lens_powers_ncert_section_9_3_8() -> None:
    """Section 9.3.8: +2.0 D and +0.25 D in contact act as +2.25 D. A concave lens lowers the sum: +2.0 and -2.5 give -0.5 D."""
    convex_pair = math_tools.combine_lens_powers([2.0, 0.25])
    mixed = math_tools.combine_lens_powers([2.0, -2.5])
    assert convex_pair["ok"] is True
    assert convex_pair["solved_for"] == "P"
    assert convex_pair["value"] == pytest.approx(2.25)
    assert convex_pair["unit"] == "D"
    assert convex_pair["formula"] == "P = P1 + P2 + ..."
    assert mixed["value"] == pytest.approx(-0.5)


def test_combine_lens_powers_refuses_bad_lists() -> None:
    """One lens is not a combination, and a lens of power 0 is refused by its position."""
    one = math_tools.combine_lens_powers([2.0])
    with_zero = math_tools.combine_lens_powers([2.0, 0])
    assert one["ok"] is False
    assert "at least 2" in one["error"]
    assert with_zero["ok"] is False
    assert "Lens 2" in with_zero["error"]


def test_absolute_refractive_index_ncert_section_9_3_2_question_2() -> None:
    """NCERT section 9.3.2, Question 2: light enters glass of refractive index 1.50, so v = 3 x 10^8 / 1.50 = 2 x 10^8 m/s."""
    result = math_tools.solve_absolute_refractive_index(n=1.50)
    assert result["ok"] is True
    assert result["solved_for"] == "v"
    assert result["value"] == pytest.approx(2.0e8)
    assert result["unit"] == "m/s"
    assert result["formula"] == "v = c / n, with c = 3 x 10^8 m/s"


def test_absolute_refractive_index_finds_n() -> None:
    """Table 9.3: water has n = 1.33, so light in water travels at about 2.26 x 10^8 m/s, and back again."""
    speed = math_tools.solve_absolute_refractive_index(n=1.33)
    index = math_tools.solve_absolute_refractive_index(v=speed["value"])
    assert speed["value"] == pytest.approx(2.26e8, rel=0.01)
    assert index["solved_for"] == "n"
    assert index["value"] == pytest.approx(1.33)
    assert index["unit"] == "no unit"


def test_absolute_refractive_index_refuses_faster_than_light() -> None:
    """n below 1 or v above 3 x 10^8 m/s would mean light faster than in vacuum, so both are refused."""
    small_n = math_tools.solve_absolute_refractive_index(n=0.9)
    fast_v = math_tools.solve_absolute_refractive_index(v=4e8)
    both = math_tools.solve_absolute_refractive_index(n=1.5, v=2e8)
    negative = math_tools.solve_absolute_refractive_index(v=-2e8)
    assert small_n["ok"] is False
    assert "less than 1" in small_n["error"]
    assert fast_v["ok"] is False
    assert "faster than light" in fast_v["error"]
    assert both["ok"] is False
    assert negative["ok"] is False


def test_relative_refractive_index_from_speeds() -> None:
    """Eq. 9.5: from air (3 x 10^8 m/s) into glass (2 x 10^8 m/s), n21 = 1.5. Each speed can also be found from the other two."""
    index = math_tools.solve_relative_refractive_index(v1=3e8, v2=2e8)
    speed_2 = math_tools.solve_relative_refractive_index(n21=1.5, v1=3e8)
    speed_1 = math_tools.solve_relative_refractive_index(n21=1.5, v2=2e8)
    assert index["solved_for"] == "n21"
    assert index["value"] == pytest.approx(1.5)
    assert index["formula"] == "n21 = v1 / v2"
    assert speed_2["value"] == pytest.approx(2e8)
    assert speed_2["unit"] == "m/s"
    assert speed_1["value"] == pytest.approx(3e8)


def test_relative_refractive_index_can_be_less_than_one() -> None:
    """From glass (n = 1.5) into water (n = 1.33), light speeds up, so the relative index is about 0.89: allowed."""
    speed_in_glass = math_tools.solve_absolute_refractive_index(n=1.5)
    speed_in_water = math_tools.solve_absolute_refractive_index(n=1.33)
    result = math_tools.solve_relative_refractive_index(v1=speed_in_glass["value"], v2=speed_in_water["value"])
    assert result["ok"] is True
    assert result["value"] == pytest.approx(1.33 / 1.5)
    assert result["value"] < 1


def test_relative_refractive_index_refuses_faster_than_light() -> None:
    """A given speed above c is refused, and so is a calculated one (n21 = 2 with v2 = 2 x 10^8 would make v1 = 4 x 10^8)."""
    given_fast = math_tools.solve_relative_refractive_index(v1=4e8, v2=2e8)
    calculated_fast = math_tools.solve_relative_refractive_index(n21=2, v2=2e8)
    only_one = math_tools.solve_relative_refractive_index(v1=3e8)
    assert given_fast["ok"] is False
    assert calculated_fast["ok"] is False
    assert "faster than light" in calculated_fast["error"]
    assert only_one["ok"] is False


def test_relative_index_from_absolute_table_9_3() -> None:
    """Table 9.3: crown glass (1.52) with respect to water (1.33) is 1.52 / 1.33 = 1.14; water with respect to glass is 0.875."""
    glass_wrt_water = math_tools.solve_relative_index_from_absolute(n1=1.33, n2=1.52)
    water_wrt_glass = math_tools.solve_relative_index_from_absolute(n1=1.52, n2=1.33)
    glass_index = math_tools.solve_relative_index_from_absolute(n21=1.52 / 1.33, n1=1.33)
    assert glass_wrt_water["solved_for"] == "n21"
    assert glass_wrt_water["value"] == pytest.approx(1.52 / 1.33)
    assert glass_wrt_water["formula"] == "n21 = n2 / n1"
    assert water_wrt_glass["value"] == pytest.approx(0.875)
    assert glass_index["solved_for"] == "n2"
    assert glass_index["value"] == pytest.approx(1.52)


def test_relative_index_from_absolute_matches_the_speeds_route() -> None:
    """Both routes give the same answer: n2 / n1 equals v1 / v2 when the speeds come from n = c / v."""
    speed_in_water = math_tools.solve_absolute_refractive_index(n=1.33)
    speed_in_glass = math_tools.solve_absolute_refractive_index(n=1.52)
    from_speeds = math_tools.solve_relative_refractive_index(v1=speed_in_water["value"], v2=speed_in_glass["value"])
    from_indices = math_tools.solve_relative_index_from_absolute(n1=1.33, n2=1.52)
    assert from_speeds["value"] == pytest.approx(from_indices["value"])


def test_relative_index_from_absolute_refuses_impossible_indices() -> None:
    """A given absolute index below 1 is refused, and so is a calculated one (n21 = 2 with n2 = 1.5 would make n1 = 0.75)."""
    given_small = math_tools.solve_relative_index_from_absolute(n1=0.9, n2=1.5)
    calculated_small = math_tools.solve_relative_index_from_absolute(n21=2, n2=1.5)
    assert given_small["ok"] is False
    assert "less than 1" in given_small["error"]
    assert calculated_small["ok"] is False


# ---------------------------------------------------------------------------
# B1, B2, C1, D4: reading answers, the numeric check, the equivalence check, calculate, convert_from_si
# ---------------------------------------------------------------------------


def test_convert_from_si_ncert_example_11_13() -> None:
    """NCERT Example 11.13: 3.456 x 10^8 J is 96 kW h ("units"), and -0.3 m is -30 cm."""
    energy = math_tools.convert_from_si(3.456e8, "kWh")
    distance = math_tools.convert_from_si(-0.3, "cm")
    unknown = math_tools.convert_from_si(1, "furlong")
    assert energy["ok"] is True
    assert energy["value"] == pytest.approx(96.0)
    assert energy["unit"] == "kWh"
    assert distance["value"] == pytest.approx(-30.0)
    assert unknown["ok"] is False


def test_read_quantity_reads_signs_and_units() -> None:
    """"-30 cm" and "−30 cm" (Unicode minus, as copied from a PDF) both read as -0.3 m, remembering -30 and cm."""
    plain = math_tools.read_quantity("-30 cm")
    unicode_minus = math_tools.read_quantity("−30 cm")
    no_space = math_tools.read_quantity("30cm.")
    assert plain["ok"] is True
    assert plain["solved_for"] == "length"
    assert plain["value"] == pytest.approx(-0.3)
    assert plain["unit"] == "m"
    assert plain["read_number"] == pytest.approx(-30.0)
    assert plain["read_unit"] == "cm"
    assert unicode_minus["value"] == pytest.approx(-0.3)
    assert no_space["value"] == pytest.approx(0.3)


def test_read_quantity_reads_powers_of_ten() -> None:
    """The speed of light written four ways: "3 × 10^8 m/s", "3x10^8 m s^-1", "3 × 10⁸ m/s" and "3e8 m/s"."""
    for text in ["3 × 10^8 m/s", "3x10^8 m s^-1", "3 × 10⁸ m/s", "3e8 m/s"]:
        result = math_tools.read_quantity(text)
        assert result["ok"] is True
        assert result["value"] == pytest.approx(3e8)
        assert result["unit"] == "m/s"


def test_read_quantity_reads_dioptres_commas_and_rupees() -> None:
    """"+1.25 D", "96,000 J", "Rs 288" and "₹288" are all read; a bare "57.6" has no unit."""
    power = math_tools.read_quantity("+1.25 D")
    energy = math_tools.read_quantity("96,000 J")
    rupees = math_tools.read_quantity("Rs 288")
    rupee_sign = math_tools.read_quantity("₹288")
    bare = math_tools.read_quantity("57.6")
    assert power["value"] == pytest.approx(1.25)
    assert power["unit"] == "D"
    assert energy["value"] == pytest.approx(96000.0)
    assert rupees["value"] == pytest.approx(288.0)
    assert rupees["unit"] == "Rs"
    assert rupee_sign["value"] == pytest.approx(288.0)
    assert bare["solved_for"] == "number"
    assert bare["unit"] == "none"


def test_read_quantity_refuses_text_it_cannot_read() -> None:
    """No number at the start, or a unit the table doesn't know, gives an error."""
    words = math_tools.read_quantity("about thirty")
    strange_unit = math_tools.read_quantity("30 furlongs")
    assert words["ok"] is False
    assert "number" in words["error"]
    assert strange_unit["ok"] is False
    assert "Unknown unit" in strange_unit["error"]


def test_numeric_answer_matches_in_any_length_unit() -> None:
    """NCERT Example 9.2: the key is -37.5 cm. "-37.5 cm" and "-0.375 m" are both correct."""
    same = math_tools.check_numeric_answer("-37.5 cm", "-37.5 cm")
    metres = math_tools.check_numeric_answer("-0.375 m", "-37.5 cm")
    assert same["ok"] is True
    assert same["solved_for"] == "correct"
    assert same["value"] is True
    assert "Matches" in same["detail"]
    assert metres["value"] is True


def test_numeric_answer_accepts_ncert_rounding() -> None:
    """NCERT's printed answers are close to, not equal to, the exact ones: 57.60 vs 57.62 ohm (Ex 11.10), 0.33 vs 1/3 (Ex 9.3)."""
    resistance = math_tools.check_numeric_answer("57.60 ohm", "57.62 ohm")
    magnification = math_tools.check_numeric_answer("0.33", "0.3333")
    assert resistance["value"] is True
    assert magnification["value"] is True


def test_numeric_answer_wrong_sign_says_so() -> None:
    """+37.5 cm against a key of -37.5 cm is wrong, and the detail points at the sign convention."""
    result = math_tools.check_numeric_answer("37.5 cm", "-37.5 cm")
    assert result["ok"] is True
    assert result["value"] is False
    assert "Wrong sign" in result["detail"]


def test_numeric_answer_too_far_off_says_by_how_much() -> None:
    """-40 cm against -37.5 cm is 6.7% off, more than the 2% allowed."""
    result = math_tools.check_numeric_answer("-40 cm", "-37.5 cm")
    assert result["value"] is False
    assert "6.7%" in result["detail"]


def test_numeric_answer_wrong_kind_of_unit() -> None:
    """30 s is a time, so it cannot answer a question whose key is 30 cm."""
    result = math_tools.check_numeric_answer("30 s", "30 cm")
    assert result["value"] is False
    assert "Wrong kind of unit" in result["detail"]


def test_numeric_answer_missing_unit_is_correct_with_a_reminder() -> None:
    """Decision Q3: "-37.5" against "-37.5 cm" counts as correct, but the detail says the unit is missing."""
    result = math_tools.check_numeric_answer("-37.5", "-37.5 cm")
    assert result["value"] is True
    assert "unit is missing" in result["detail"]


def test_numeric_answer_key_without_unit_compares_the_numbers() -> None:
    """A key of "-30" (no unit) is compared with the number the student wrote, -30, not with -0.3 m."""
    result = math_tools.check_numeric_answer("-30 cm", "-30")
    assert result["value"] is True
    assert "no unit" in result["detail"]


def test_numeric_answer_unreadable_answer_and_key() -> None:
    """An unreadable answer is simply not correct; an unreadable KEY is an error on our side."""
    bad_answer = math_tools.check_numeric_answer("thirty", "-30 cm")
    bad_key = math_tools.check_numeric_answer("-30 cm", "minus thirty")
    assert bad_answer["ok"] is True
    assert bad_answer["value"] is False
    assert bad_key["ok"] is False


def test_numeric_answer_tolerance_can_be_changed() -> None:
    """With a very tight tolerance (0.01%), NCERT's rounded 57.60 no longer matches 57.62; a bad tolerance is refused."""
    tight = math_tools.check_numeric_answer("57.60 ohm", "57.62 ohm", tolerance=0.0001)
    bad = math_tools.check_numeric_answer("57.60 ohm", "57.62 ohm", tolerance=1.5)
    assert tight["value"] is False
    assert bad["ok"] is False


def test_numeric_answer_zero_key() -> None:
    """A key of 0 is checked directly, without dividing by it."""
    zero = math_tools.check_numeric_answer("0 A", "0 A")
    not_zero = math_tools.check_numeric_answer("2 A", "0 A")
    assert zero["value"] is True
    assert not_zero["value"] is False


def test_equivalence_ohms_law_rearranged() -> None:
    """V = IR, R = V/I and I = V/R are the same law (NCERT Eq. 11.5-11.7). "I" stays a current, not SymPy's imaginary unit."""
    first = math_tools.check_equivalence("R = V/I", "V = IR")
    second = math_tools.check_equivalence("I = V/R", "V = I*R")
    assert first["ok"] is True
    assert first["solved_for"] == "equivalent"
    assert first["value"] is True
    assert "Same relation" in first["detail"]
    assert second["value"] is True


def test_equivalence_mirror_formula_rearranged() -> None:
    """The mirror formula 1/v + 1/u = 1/f (Eq. 9.1) is the same as f = uv / (u + v)."""
    result = math_tools.check_equivalence("f = uv/(u+v)", "1/v + 1/u = 1/f")
    assert result["value"] is True


def test_equivalence_lens_is_not_mirror() -> None:
    """The lens formula (Eq. 9.8) is NOT the mirror formula (Eq. 9.1): solving for f gives different results."""
    result = math_tools.check_equivalence("1/v - 1/u = 1/f", "1/v + 1/u = 1/f")
    assert result["value"] is False
    assert "Different relation" in result["detail"]


def test_equivalence_keeps_names_whole_and_letters_as_quantities() -> None:
    """R = rho l / A (Eq. 11.10) rearranged; "rho" stays one name. E = P t: "E" is energy, not Euler's number."""
    resistivity = math_tools.check_equivalence("rho = R A / l", "R = rho l / A")
    energy = math_tools.check_equivalence("E = P t", "P = E/t")
    assert resistivity["value"] is True
    assert energy["value"] is True


def test_equivalence_different_quantities_are_not_linked() -> None:
    """P = VI and P = I^2 R are only equal given Ohm's law, which this check does not assume."""
    result = math_tools.check_equivalence("P = VI", "P = I^2 R")
    assert result["value"] is False
    assert "different quantities" in result["detail"]


def test_equivalence_of_expressions_ncert_exercise_2() -> None:
    """NCERT Ch 11, Exercise 2: I^2 R is a form of power; I R^2 is not. R I I is the same as I^2 R."""
    same = math_tools.check_equivalence("R I I", "I^2 R")
    different = math_tools.check_equivalence("I R^2", "I^2 R")
    mixed = math_tools.check_equivalence("V = IR", "IR")
    assert same["value"] is True
    assert different["value"] is False
    assert mixed["value"] is False


def test_equivalence_refuses_unsafe_text_before_sympy() -> None:
    """Text that could be code is refused before SymPy (which uses eval) ever sees it: an unsafe answer is not correct."""
    code = math_tools.check_equivalence("__import__('os').system('dir')", "V = IR")
    too_long = math_tools.check_equivalence("V = " + "I*R + " * 30 + "0", "V = IR")
    unsafe_key = math_tools.check_equivalence("V = IR", "open('x')")
    assert code["ok"] is True
    assert code["value"] is False
    assert "not allowed" in code["detail"]
    assert too_long["value"] is False
    assert unsafe_key["ok"] is False


def test_is_safe_formula_text() -> None:
    """Letters, digits, spaces and + - * / ^ ( ) = . are allowed; quotes, underscores and a second "=" are not."""
    assert math_tools.is_safe_formula_text("1/v + 1/u = 1/f") is True
    assert math_tools.is_safe_formula_text("R = rho l / A") is True
    assert math_tools.is_safe_formula_text("__import__") is False
    assert math_tools.is_safe_formula_text("print('hi')") is False
    assert math_tools.is_safe_formula_text("a = b = c") is False
    assert math_tools.is_safe_formula_text("") is False


def test_every_letter_is_a_quantity_not_a_sympy_constant() -> None:
    """I is current, not the imaginary unit; E is energy, not Euler's number. The same for S, N, O and Q."""
    # If I were the imaginary unit, I^2 R would simplify to -R and this would wrongly be True.
    current_squared = math_tools.check_equivalence("I^2 R", "-R")
    assert current_squared["value"] is False
    # Each of these letters means something special to SymPy; here each must be a plain symbol.
    for letter in ["I", "E", "S", "N", "O", "Q"]:
        assert math_tools.parse_formula_side(letter).is_Symbol is True


def test_formula_gate_allows_english_letters_only() -> None:
    """Only English letters pass the gate: a Greek rho or full-width letters are refused with a clear message."""
    # "ρ" is the Greek small letter rho; NCERT writes rho this way in Eq. 11.10.
    greek_rho = "ρ = R A / l"
    # "Ｖ = ＩＲ" are full-width letters that look like "V = IR" but are not English letters.
    full_width = "Ｖ = ＩＲ"
    assert math_tools.is_safe_formula_text(greek_rho) is False
    assert math_tools.is_safe_formula_text(full_width) is False
    # The same formula written with "rho" as a word still passes.
    assert math_tools.is_safe_formula_text("rho = R A / l") is True
    # A student who types the Greek letter is told how to write it.
    result = math_tools.check_equivalence(greek_rho, "R = rho l / A")
    assert result["ok"] is True
    assert result["value"] is False
    assert "write Greek letters as words (rho)" in result["detail"]


def test_calculate_the_arithmetic_between_steps() -> None:
    """Decision D4: 8 h a day for 30 days is 8 x 30 = 240 h (NCERT Example 11.13); 100 W + 60 W = 160 W (Exercise 15)."""
    hours = math_tools.calculate("8 x 30")
    watts = math_tools.calculate("100 + 60")
    resistors = math_tools.calculate("176 / 44")
    assert hours["ok"] is True
    assert hours["solved_for"] == "value"
    assert hours["value"] == pytest.approx(240.0)
    assert hours["unit"] == "no unit"
    assert watts["value"] == pytest.approx(160.0)
    assert resistors["value"] == pytest.approx(4.0)


def test_calculate_powers_and_brackets() -> None:
    """3 × 10^8 / 1.5 = 2 x 10^8 (NCERT section 9.3.2 Q2), 2^10 = 1024, and (8 + 2) * 3 = 30."""
    assert math_tools.calculate("3 × 10^8 / 1.5")["value"] == pytest.approx(2e8)
    assert math_tools.calculate("2^10")["value"] == pytest.approx(1024.0)
    assert math_tools.calculate("(8 + 2) * 3")["value"] == pytest.approx(30.0)


def test_calculate_refuses_anything_but_arithmetic() -> None:
    """Code, names, division by zero, a huge power and empty text are all refused with an error, never run."""
    code = math_tools.calculate("__import__('os').system('dir')")
    name = math_tools.calculate("abs(-5)")
    divide_by_zero = math_tools.calculate("1/0")
    huge_power = math_tools.calculate("2^1000")
    empty = math_tools.calculate("")
    assert code["ok"] is False
    assert name["ok"] is False
    assert divide_by_zero["ok"] is False
    assert "division by zero" in divide_by_zero["error"]
    assert huge_power["ok"] is False
    assert "too large" in huge_power["error"]
    assert empty["ok"] is False


def test_energy_cost_chain_with_calculate_and_convert_from_si() -> None:
    """NCERT Example 11.13, fully in code: calculate 8 x 30 h, convert to s, energy = P t, show it in kW h, then the cost."""
    hours = math_tools.calculate("8 * 30")
    seconds = math_tools.convert_to_si(hours["value"], "h")
    energy = math_tools.solve_energy_power_time(p=400, t=seconds["value"])
    units = math_tools.convert_from_si(energy["value"], "kWh")
    cost = math_tools.solve_energy_cost(energy=energy["value"], rate=3.00)
    assert units["value"] == pytest.approx(96.0)
    assert cost["value"] == pytest.approx(288.0)


def test_student_word_answers_and_expressions() -> None:
    """Natural student phrasing: minus/plus in words, spelled numbers, square roots, and fractions."""
    # Signs in words
    res = math_tools.check_numeric_answer("minus 0.6 meters", "-60 cm")
    assert res["value"] is True
    res_plus = math_tools.check_numeric_answer("plus 2.5 D", "+2.5 D")
    assert res_plus["value"] is True

    # Spelled out number words
    res_words = math_tools.check_numeric_answer("minus sixty centimeters", "-60 cm")
    assert res_words["value"] is True
    res_two = math_tools.check_numeric_answer("two meters", "2 m")
    assert res_two["value"] is True

    # Square roots
    for expr in ("Squareroot of 4", "SQRT 4", "sqrt 4", "sqrt(4)", "√4"):
        res_sqrt = math_tools.check_numeric_answer(expr, "2")
        assert res_sqrt["value"] is True
    res_sqrt_unit = math_tools.check_numeric_answer("√4 cm", "2 cm")
    assert res_sqrt_unit["value"] is True

    # Fractions
    res_frac = math_tools.check_numeric_answer("1/2 A", "0.5 A")
    assert res_frac["value"] is True
    res_half = math_tools.check_numeric_answer("half an ampere", "0.5 A")
    assert res_half["value"] is True
