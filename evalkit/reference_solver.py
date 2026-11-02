"""Independent reference solver for evaluation answer keys.

The guide asks for answer keys computed by code, never typed by hand or by a
model. This module is deliberately separate from socratic_tutor/tools/math_tools.py
(the tutor's own calculator): if the two ever disagree, the test
tests/test_eval_datasets.py fails and shows which question is affected.

Units: distances in cm, focal lengths in cm (New Cartesian signs), power in
dioptres, resistance in ohm, current in A, voltage in V, time in s, energy in J
or kWh as named.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Callable

Number = float | int


def _f(value: Number) -> Fraction:
    return Fraction(str(value))


def mirror_image_distance(u: Number, f: Number) -> float:
    """1/v + 1/u = 1/f  ->  v = 1 / (1/f - 1/u)."""
    return float(1 / (1 / _f(f) - 1 / _f(u)))


def mirror_magnification(u: Number, f: Number) -> float:
    """m = -v/u for spherical mirrors."""
    v = Fraction(str(mirror_image_distance(u, f)))
    return float(-v / _f(u))


def mirror_magnification_from_uv(u: Number, v: Number) -> float:
    """m = -v/u, given both distances."""
    return float(-_f(v) / _f(u))


def image_distance_from_magnification_mirror(m: Number, u: Number) -> float:
    """m = -v/u  ->  v = -m u."""
    return float(-_f(m) * _f(u))


def complement_angle(angle_with_surface: Number) -> float:
    """Angle from the normal, given the angle from the mirror surface (degrees)."""
    return float(90 - _f(angle_with_surface))


def mirror_focal_from_radius(r: Number) -> float:
    return float(_f(r) / 2)


def mirror_radius_from_focal(f: Number) -> float:
    return float(_f(f) * 2)


def lens_image_distance(u: Number, f: Number) -> float:
    """1/v - 1/u = 1/f  ->  v = 1 / (1/f + 1/u)."""
    return float(1 / (1 / _f(f) + 1 / _f(u)))


def lens_magnification(u: Number, f: Number) -> float:
    """m = v/u for lenses."""
    v = Fraction(str(lens_image_distance(u, f)))
    return float(v / _f(u))


def lens_image_height(u: Number, f: Number, h: Number) -> float:
    return float(Fraction(str(lens_magnification(u, f))) * _f(h))


def lens_power_dioptre(f_cm: Number) -> float:
    """P = 1/f with f in metres."""
    return float(1 / (_f(f_cm) / 100))


def net_power(powers: list[Number]) -> float:
    """Lenses in contact: P = P1 + P2 + ..."""
    return float(sum(_f(p) for p in powers))


def corrective_power_far_point(far_point_cm: Number) -> float:
    """Myopia: concave lens with f = -(far point)."""
    return lens_power_dioptre(-abs(_f(far_point_cm)))


def corrective_power_near_point(near_point_cm: Number, normal_near_cm: Number = 25) -> float:
    """Hypermetropia: object at 25 cm must form a virtual image at the near point."""
    u = -abs(_f(normal_near_cm))
    v = -abs(_f(near_point_cm))
    f = 1 / (1 / v - 1 / u)
    return float(1 / (f / 100))


def speed_in_medium(n: Number, c: Number = 3.0e8) -> float:
    return float(_f(c) / _f(n))


def refractive_index(c: Number, v: Number) -> float:
    return float(_f(c) / _f(v))


def current_from_charge(q: Number, t: Number) -> float:
    """I = Q / t."""
    return float(_f(q) / _f(t))


def work_from_voltage(v: Number, q: Number) -> float:
    """W = V Q."""
    return float(_f(v) * _f(q))


def ohm_resistance(v: Number, i: Number) -> float:
    return float(_f(v) / _f(i))


def ohm_current(v: Number, r: Number) -> float:
    return float(_f(v) / _f(r))


def ohm_voltage(i: Number, r: Number) -> float:
    return float(_f(i) * _f(r))


def series_resistance(resistors: list[Number]) -> float:
    return float(sum(_f(r) for r in resistors))


def parallel_resistance(resistors: list[Number]) -> float:
    return float(1 / sum(1 / _f(r) for r in resistors))


def series_current(resistors: list[Number], v: Number) -> float:
    return float(_f(v) / sum(_f(r) for r in resistors))


def parallel_total_current(resistors: list[Number], v: Number) -> float:
    return float(sum(_f(v) / _f(r) for r in resistors))


def branch_current(r: Number, v: Number) -> float:
    return float(_f(v) / _f(r))


def joule_heat(i: Number, r: Number, t: Number) -> float:
    """H = I^2 R t (J)."""
    return float(_f(i) ** 2 * _f(r) * _f(t))


def heat_from_voltage(v: Number, r: Number, t: Number) -> float:
    """H = V^2 t / R (J)."""
    return float(_f(v) ** 2 * _f(t) / _f(r))


def power_vi(v: Number, i: Number) -> float:
    return float(_f(v) * _f(i))


def power_i2r(i: Number, r: Number) -> float:
    return float(_f(i) ** 2 * _f(r))


def current_from_power(p: Number, v: Number) -> float:
    return float(_f(p) / _f(v))


def total_current_from_powers(powers: list[Number], v: Number) -> float:
    return float(sum(_f(p) for p in powers) / _f(v))


def energy_kwh(p_watt: Number, hours: Number, days: Number = 1) -> float:
    return float(_f(p_watt) * _f(hours) * _f(days) / 1000)


def resistance_from_rating(v: Number, p: Number) -> float:
    """R = V^2 / P."""
    return float(_f(v) ** 2 / _f(p))


def scale_resistance_by_area(r: Number, area_from: Number, area_to: Number) -> float:
    """Same material and length: R is inversely proportional to area."""
    return float(_f(r) * _f(area_from) / _f(area_to))


def resistivity_resistance(rho: Number, length: Number, area: Number) -> float:
    """R = rho l / A (SI units)."""
    return float(_f(rho) * _f(length) / _f(area))


SOLVERS: dict[str, Callable[..., float]] = {
    name: fn
    for name, fn in globals().items()
    if callable(fn) and not name.startswith("_") and name not in {"Callable", "Fraction", "Any", "solve"}
}


def solve(spec: dict[str, Any]) -> float:
    """Evaluate a dataset answer spec: {"fn": "<solver name>", "args": {...}}."""
    fn = SOLVERS.get(spec["fn"])
    if fn is None:
        raise KeyError(f"Unknown reference solver {spec['fn']!r}")
    return fn(**spec.get("args", {}))
