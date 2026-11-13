"""Which syllabus topic a student's message clearly names, if any (code only, no model).

    topic_of("what is the power of a lens?")  -> "concept_lens_power"
    topic_of("huh")                           -> None

Used by the supervisor so that a clear question about another topic moves the tutor there, even in the middle
of a "Learn from the start" lesson (team testing, 12 Nov: there was no way to change topic from the chat).
Only distinctive phrases are listed: when the longest phrases found point at two different topics, or nothing
matches, the answer is None and the tutor stays where it is.
"""

from __future__ import annotations

import re

TOPIC_PHRASES: dict[str, tuple[str, ...]] = {
    "concept_reflection_laws": ("laws of reflection", "law of reflection", "angle of incidence", "angle of reflection", "plane mirror"),
    "concept_spherical_mirrors": ("centre of curvature", "center of curvature", "radius of curvature", "principal axis", "spherical mirror"),
    "concept_concave_ray_diagrams": ("concave mirror",),
    "concept_convex_ray_diagrams": ("convex mirror", "rear view mirror", "rear-view mirror"),
    "concept_sign_convention": ("sign convention",),
    "concept_mirror_formula": ("mirror formula",),
    "concept_refraction_laws": ("snell", "laws of refraction", "law of refraction", "glass slab", "bent in water", "pencil look bent", "pencil appears bent"),
    "concept_refractive_index": ("refractive index", "speed of light"),
    "concept_lens_image_formation": ("convex lens", "concave lens"),
    "concept_lens_formula": ("lens formula",),
    "concept_lens_power": ("power of a lens", "power of the lens", "power of lens", "dioptre", "diopter"),
    "concept_human_eye_structure": ("human eye", "retina", "cornea", "ciliary muscle", "eye lens"),
    "concept_accommodation": ("accommodation", "near point", "far point"),
    "concept_myopia": ("myopia", "short-sighted", "short sighted", "short-sightedness", "near-sighted", "nearsighted"),
    "concept_hypermetropia": ("hypermetropia", "long-sighted", "long sighted", "far-sighted", "farsighted"),
    "concept_presbyopia": ("presbyopia", "bifocal"),
    "concept_prism_refraction": ("glass prism", "triangular prism", "angle of deviation"),
    "concept_dispersion": ("dispersion", "spectrum", "vibgyor", "white light"),
    "concept_rainbow_formation": ("rainbow",),
    "concept_atmospheric_refraction": ("twinkle", "twinkling", "atmospheric refraction", "advance sunrise", "delayed sunset"),
    "concept_scattering": ("scattering", "scatter", "sky blue", "sky is blue", "sky appear blue", "tyndall", "danger signal"),
    "concept_electric_current": ("electric current", "ammeter", "ampere", "coulomb"),
    "concept_potential_difference": ("potential difference", "voltmeter", "electric potential"),
    "concept_ohms_law": ("ohm's law", "ohms law", "ohm law"),
    "concept_factors_resistance": ("resistivity", "length of the wire", "thickness of the wire", "area of cross"),
    "concept_series_combination": ("in series", "series combination"),
    "concept_parallel_combination": ("in parallel", "parallel combination"),
    "concept_joules_heating": ("heating effect", "joule's law", "joules law", "electric fuse", "electric heater", "electric iron", "heater wire", "wire get hot"),
    "concept_electric_power": ("electric power", "kilowatt", "kwh", "commercial unit"),
}

_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (concept, phrase, re.compile(r"\b" + re.escape(phrase).replace(r"\ ", r"\s+") + r"\w*", re.IGNORECASE))
    for concept, phrases in TOPIC_PHRASES.items()
    for phrase in phrases
]


def topic_of(text: str) -> str | None:
    """The topic the message clearly names (the longest phrase wins), or None."""
    best_len, best = 0, set()
    for concept, phrase, pattern in _PATTERNS:
        if pattern.search(text or ""):
            if len(phrase) > best_len:
                best_len, best = len(phrase), {concept}
            elif len(phrase) == best_len:
                best.add(concept)
    return next(iter(best)) if len(best) == 1 else None
