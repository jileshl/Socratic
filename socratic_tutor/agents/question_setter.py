"""Question Setter Agent: Selects or drafts practice questions at appropriate difficulty."""

from __future__ import annotations

from typing import Any
from socratic_tutor import llm, config, solver_key
from socratic_tutor.prompts import QUESTION_SETTER_PROMPT
from socratic_tutor.concept_graph import ConceptGraph

CONCEPT_FORMULA_HINTS: dict[str, list[str]] = {
    "concept_reflection_laws": ["focal_length_from_radius", "mirror_formula"],
    "concept_spherical_mirrors": ["focal_length_from_radius", "mirror_formula", "mirror_magnification"],
    "concept_concave_ray_diagrams": ["image_nature", "mirror_formula", "mirror_magnification"],
    "concept_convex_ray_diagrams": ["image_nature", "mirror_formula", "mirror_magnification"],
    "concept_sign_convention": ["mirror_formula", "lens_formula", "focal_length_from_radius"],
    "concept_mirror_formula": ["mirror_formula", "mirror_magnification", "image_height"],
    "concept_refraction_laws": ["absolute_refractive_index", "relative_refractive_index", "relative_index_from_absolute"],
    "concept_refractive_index": ["absolute_refractive_index", "relative_refractive_index", "relative_index_from_absolute"],
    "concept_lens_image_formation": ["image_nature", "lens_formula", "lens_magnification"],
    "concept_lens_formula": ["lens_formula", "lens_magnification", "image_height"],
    "concept_lens_power": ["lens_power", "combine_lens_powers"],
    "concept_human_eye_structure": ["lens_power", "lens_formula"],
    "concept_accommodation": ["lens_power", "lens_formula"],
    "concept_myopia": ["lens_power", "lens_formula"],
    "concept_hypermetropia": ["lens_power", "lens_formula"],
    "concept_presbyopia": ["combine_lens_powers", "lens_power"],
    "concept_prism_refraction": ["relative_refractive_index", "absolute_refractive_index"],
    "concept_dispersion": ["relative_refractive_index", "absolute_refractive_index"],
    "concept_rainbow_formation": ["relative_refractive_index", "absolute_refractive_index"],
    "concept_atmospheric_refraction": ["relative_refractive_index", "absolute_refractive_index", "relative_index_from_absolute"],
    "concept_scattering": ["relative_refractive_index", "absolute_refractive_index"],
    "concept_electric_current": ["charge_current"],
    "concept_potential_difference": ["voltage_work_charge", "ohms_law"],
    "concept_ohms_law": ["ohms_law"],
    "concept_factors_resistance": ["resistivity", "wire_area"],
    "concept_series_combination": ["series_resistance", "ohms_law"],
    "concept_parallel_combination": ["parallel_resistance", "ohms_law"],
    "concept_resistors_combination": ["series_resistance", "parallel_resistance", "ohms_law"],
    "concept_joules_heating": ["joule_heating", "voltage_work_charge"],
    "concept_joule_heating": ["joule_heating", "voltage_work_charge"],
    "concept_electric_power": ["power_voltage_current", "power_current_resistance", "power_voltage_resistance", "energy_power_time", "energy_cost"],
}

CONCEPT_FALLBACK_QUESTIONS: dict[str, Any] = {
    "concept_reflection_laws": [
        {
            "question_text": "A ray of light reflects from a concave spherical mirror of radius of curvature 30 cm. Calculate the focal length of the mirror.",
            "gold_answer": "-15 cm",
            "difficulty": "easy",
            "calculation": {"formula": "focal_length_from_radius", "radius_of_curvature": -30, "length_unit": "cm", "find": "f"},
        },
        {
            "question_text": "A ray of light reflects from a convex spherical mirror of radius of curvature 40 cm. Calculate the focal length of the mirror.",
            "gold_answer": "20 cm",
            "difficulty": "medium",
            "calculation": {"formula": "focal_length_from_radius", "radius_of_curvature": 40, "length_unit": "cm", "find": "f"},
        },
    ],
    "concept_concave_mirror": {
        "question_text": "An object is placed 20 cm in front of a concave mirror of focal length 15 cm. Find the distance of the image from the mirror.",
        "gold_answer": "-60 cm",
        "difficulty": "medium",
        "calculation": {"formula": "mirror_formula", "u": -20, "f": -15, "length_unit": "cm", "find": "v"},
    },
    "concept_spherical_mirrors": [
        {
            "question_text": "A concave mirror has a radius of curvature of 30 cm. Find its focal length.",
            "gold_answer": "-15 cm",
            "difficulty": "easy",
            "calculation": {"formula": "focal_length_from_radius", "radius_of_curvature": -30, "length_unit": "cm", "find": "f"},
        },
        {
            "question_text": "A convex mirror has a radius of curvature of 40 cm. Find its focal length.",
            "gold_answer": "20 cm",
            "difficulty": "medium",
            "calculation": {"formula": "focal_length_from_radius", "radius_of_curvature": 40, "length_unit": "cm", "find": "f"},
        },
        {
            "question_text": "An object is placed 30 cm in front of a concave mirror of focal length 20 cm. Find the image distance.",
            "gold_answer": "-60 cm",
            "difficulty": "hard",
            "calculation": {"formula": "mirror_formula", "u": -30, "f": -20, "length_unit": "cm", "find": "v"},
        },
    ],
    "concept_concave_ray_diagrams": [
        {
            "question_text": "A concave mirror produces an image with magnification m = -2. Find the nature of the image.",
            "gold_answer": "real and inverted, enlarged",
            "difficulty": "easy",
            "calculation": {"formula": "image_nature", "m": -2, "find": "nature"},
        },
        {
            "question_text": "An object is placed 20 cm in front of a concave mirror of focal length 15 cm. Find the distance of the image from the mirror.",
            "gold_answer": "-60 cm",
            "difficulty": "medium",
            "calculation": {"formula": "mirror_formula", "u": -20, "f": -15, "length_unit": "cm", "find": "v"},
        },
    ],
    "concept_convex_ray_diagrams": [
        {
            "question_text": "A convex mirror produces an image with magnification m = 0.5. Find the nature of the image.",
            "gold_answer": "virtual and erect, diminished",
            "difficulty": "easy",
            "calculation": {"formula": "image_nature", "m": 0.5, "find": "nature"},
        },
        {
            "question_text": "An object is placed 30 cm in front of a convex mirror of focal length 15 cm. Find the image distance.",
            "gold_answer": "10 cm",
            "difficulty": "medium",
            "calculation": {"formula": "mirror_formula", "u": -30, "f": 15, "length_unit": "cm", "find": "v"},
        },
    ],
    "concept_sign_convention": [
        {
            "question_text": "A concave mirror has a focal length of 20 cm and an object is placed 30 cm in front of it. Using the New Cartesian sign convention, calculate the image distance.",
            "gold_answer": "-60 cm",
            "difficulty": "easy",
            "calculation": {"formula": "mirror_formula", "u": -30, "f": -20, "length_unit": "cm", "find": "v"},
        },
        {
            "question_text": "A convex mirror has a focal length of 15 cm and an object is placed 30 cm in front of it. Find the image distance.",
            "gold_answer": "10 cm",
            "difficulty": "medium",
            "calculation": {"formula": "mirror_formula", "u": -30, "f": 15, "length_unit": "cm", "find": "v"},
        },
    ],
    "concept_mirror_formula": {
        "question_text": "An object is placed 30 cm in front of a concave mirror of focal length 20 cm. Find the image distance using the mirror formula.",
        "gold_answer": "-60 cm",
        "difficulty": "medium",
        "calculation": {"formula": "mirror_formula", "u": -30, "f": -20, "length_unit": "cm", "find": "v"},
    },
    "concept_refraction_laws": [
        {
            "question_text": "Light enters a glass medium from vacuum where its speed is measured to be 200000000 m/s. Given that the speed of light in vacuum is 300000000 m/s, calculate the absolute refractive index of the glass.",
            "gold_answer": "1.5",
            "difficulty": "easy",
            "calculation": {"formula": "absolute_refractive_index", "v": 200000000, "find": "n"},
        },
        {
            "question_text": "Light travels from medium 1 at 225000000 m/s into medium 2 at 180000000 m/s. Find the relative refractive index of medium 2 with respect to medium 1.",
            "gold_answer": "1.25",
            "difficulty": "medium",
            "calculation": {"formula": "relative_refractive_index", "v1": 225000000, "v2": 180000000, "find": "n21"},
        },
    ],
    "concept_refractive_index": [
        {
            "question_text": "The speed of light in a diamond is 124000000 m/s. Calculate the absolute refractive index of diamond if the speed of light in vacuum is 300000000 m/s.",
            "gold_answer": "2.42",
            "difficulty": "easy",
            "calculation": {"formula": "absolute_refractive_index", "v": 124000000, "find": "n"},
        },
        {
            "question_text": "Light travels through two atmospheric layers. The first layer has an absolute refractive index of 1.2 and the second layer has an absolute refractive index of 1.5. Calculate the relative refractive index of the second layer with respect to the first layer.",
            "gold_answer": "1.25",
            "difficulty": "medium",
            "calculation": {"formula": "relative_index_from_absolute", "n1": 1.2, "n2": 1.5, "find": "n21"},
        },
    ],
    "concept_lens_image_formation": [
        {
            "question_text": "A convex lens produces an image with magnification m = -1. Find the nature of the image.",
            "gold_answer": "real and inverted, same size",
            "difficulty": "easy",
            "calculation": {"formula": "image_nature", "m": -1, "find": "nature"},
        },
        {
            "question_text": "A convex lens produces an image with magnification m = -2. Find the nature of the image.",
            "gold_answer": "real and inverted, enlarged",
            "difficulty": "medium",
            "calculation": {"formula": "image_nature", "m": -2, "find": "nature"},
        },
    ],
    "concept_lens_formula": [
        {
            "question_text": "A convex lens of focal length 20 cm produces an image of an object placed 30 cm in front of it. Find the image distance.",
            "gold_answer": "60 cm",
            "difficulty": "easy",
            "calculation": {"formula": "lens_formula", "u": -30, "f": 20, "length_unit": "cm", "find": "v"},
        },
        {
            "question_text": "An object is placed 30 cm in front of a concave lens of focal length 15 cm. Find the image distance.",
            "gold_answer": "-10 cm",
            "difficulty": "medium",
            "calculation": {"formula": "lens_formula", "u": -30, "f": -15, "length_unit": "cm", "find": "v"},
        },
    ],
    "concept_lens_power": [
        {
            "question_text": "A convex lens has a focal length of 0.5 m. Find its power.",
            "gold_answer": "2 D",
            "difficulty": "easy",
            "calculation": {"formula": "lens_power", "f": 0.5, "length_unit": "m", "find": "p"},
        },
        {
            "question_text": "Two thin lenses of powers 2 D and -3 D are placed in contact. Find the combined power of the combination.",
            "gold_answer": "-1 D",
            "difficulty": "medium",
            "calculation": {"formula": "combine_lens_powers", "powers": [2, -3]},
        },
    ],
    "concept_human_eye_structure": [
        {
            "question_text": "For a normal human eye, the near point of distinct vision corresponds to a focal length of 0.25 m. Calculate the refractive power of the eye lens in dioptres at this near point.",
            "gold_answer": "4 D",
            "difficulty": "easy",
            "calculation": {"formula": "lens_power", "values": {"f": 0.25}, "length_unit": "m", "find": "p"},
        },
        {
            "question_text": "An eye lens has an effective focal length of 0.2 m when viewing a close object. Find the power of the lens.",
            "gold_answer": "5 D",
            "difficulty": "medium",
            "calculation": {"formula": "lens_power", "values": {"f": 0.2}, "length_unit": "m", "find": "p"},
        },
    ],
    "concept_accommodation": [
        {
            "question_text": "When the eye accommodates to view an object at the near point of 25 cm (0.25 m), calculate the power of the eye lens.",
            "gold_answer": "4 D",
            "difficulty": "easy",
            "calculation": {"formula": "lens_power", "values": {"f": 0.25}, "length_unit": "m", "find": "p"},
        },
        {
            "question_text": "When viewing an object at 50 cm (0.5 m), calculate the power of the eye lens.",
            "gold_answer": "2 D",
            "difficulty": "medium",
            "calculation": {"formula": "lens_power", "values": {"f": 0.5}, "length_unit": "m", "find": "p"},
        },
    ],
    "concept_myopia": [
        {
            "question_text": "A myopic person uses a concave lens of focal length 2 m to view distant objects clearly. Calculate the power of the lens.",
            "gold_answer": "-0.5 D",
            "difficulty": "easy",
            "calculation": {"formula": "lens_power", "values": {"f": -2}, "length_unit": "m", "find": "p"},
        },
        {
            "question_text": "A person with a myopic eye has a far point of 2.5 m. Find the power of the corrective concave lens required to restore distant vision.",
            "gold_answer": "-0.4 D",
            "difficulty": "medium",
            "calculation": {"formula": "lens_power", "values": {"f": -2.5}, "length_unit": "m", "find": "p"},
        },
    ],
    "concept_hypermetropia": [
        {
            "question_text": "A hypermetropic person uses a convex reading lens of focal length 0.5 m. Calculate the power of the lens.",
            "gold_answer": "2 D",
            "difficulty": "easy",
            "calculation": {"formula": "lens_power", "values": {"f": 0.5}, "length_unit": "m", "find": "p"},
        },
        {
            "question_text": "A hypermetropic person requires a convex lens of focal length 0.4 m to read comfortably. Find the power of this lens.",
            "gold_answer": "2.5 D",
            "difficulty": "medium",
            "calculation": {"formula": "lens_power", "values": {"f": 0.4}, "length_unit": "m", "find": "p"},
        },
    ],
    "concept_presbyopia": [
        {
            "question_text": "A reading lens of power 2 D is used to correct presbyopia. Find the focal length of this convex lens in metres.",
            "gold_answer": "0.5 m",
            "difficulty": "easy",
            "calculation": {"formula": "lens_power", "p": 2, "length_unit": "m", "find": "f"},
        },
        {
            "question_text": "Two corrective lenses of powers 3 D and -1 D are combined. Calculate the net power in dioptres.",
            "gold_answer": "2 D",
            "difficulty": "medium",
            "calculation": {"formula": "combine_lens_powers", "powers": [3, -1]},
        },
    ],
    "concept_prism_refraction": [
        {
            "question_text": "Light enters a glass prism from air. If the speed of light in air is 300000000 m/s and in the glass prism is 200000000 m/s, find the refractive index of the prism.",
            "gold_answer": "1.5",
            "difficulty": "easy",
            "calculation": {"formula": "absolute_refractive_index", "v": 200000000, "find": "n"},
        },
        {
            "question_text": "Light travels from medium 1 where its speed is 240000000 m/s into a prism where its speed is 200000000 m/s. Calculate the relative refractive index of the prism with respect to medium 1.",
            "gold_answer": "1.2",
            "difficulty": "medium",
            "calculation": {"formula": "relative_refractive_index", "v1": 240000000, "v2": 200000000, "find": "n21"},
        },
    ],
    "concept_dispersion": [
        {
            "question_text": "During dispersion of white light in a glass prism, red light travels at 200000000 m/s. Given the speed of light in vacuum is 300000000 m/s, calculate the refractive index of the prism for red light.",
            "gold_answer": "1.5",
            "difficulty": "easy",
            "calculation": {"formula": "absolute_refractive_index", "v": 200000000, "find": "n"},
        },
        {
            "question_text": "In a dispersive medium, the speed of red light is 200000000 m/s and the speed of violet light is 160000000 m/s. Calculate the relative refractive index of violet light with respect to red light.",
            "gold_answer": "1.25",
            "difficulty": "medium",
            "calculation": {"formula": "relative_refractive_index", "v1": 200000000, "v2": 160000000, "find": "n21"},
        },
    ],
    "concept_rainbow_formation": [
        {
            "question_text": "In a rainbow, light refracts into a spherical water droplet where its speed is 225000000 m/s. Given that the speed of light in air is 300000000 m/s, calculate the refractive index of water.",
            "gold_answer": "1.33",
            "difficulty": "easy",
            "calculation": {"formula": "absolute_refractive_index", "v": 225000000, "find": "n"},
        },
        {
            "question_text": "Light passes from medium 1 with absolute refractive index 1.2 into a water droplet with absolute refractive index 1.5. Calculate the relative refractive index.",
            "gold_answer": "1.25",
            "difficulty": "medium",
            "calculation": {"formula": "relative_index_from_absolute", "n1": 1.2, "n2": 1.5, "find": "n21"},
        },
    ],
    "concept_atmospheric_refraction": [
        {
            "question_text": "Due to atmospheric refraction, the speed of light in a dense lower atmospheric layer is 299700000 m/s. Calculate the refractive index of this layer if the speed of light in vacuum is 300000000 m/s.",
            "gold_answer": "1.001",
            "difficulty": "easy",
            "calculation": {"formula": "absolute_refractive_index", "v": 299700000, "find": "n"},
        },
        {
            "question_text": "Light enters from an upper atmospheric layer where its speed is 299900000 m/s into a lower layer where its speed is 299700000 m/s. Find the relative refractive index of the lower layer with respect to the upper layer.",
            "gold_answer": "1.0007",
            "difficulty": "medium",
            "calculation": {"formula": "relative_refractive_index", "v1": 299900000, "v2": 299700000, "find": "n21"},
        },
        {
            "question_text": "Light travels through two atmospheric layers. The first layer has an absolute refractive index of 1.2 and the second layer has an absolute refractive index of 1.5. Calculate the relative refractive index of the second layer with respect to the first layer.",
            "gold_answer": "1.25",
            "difficulty": "hard",
            "calculation": {"formula": "relative_index_from_absolute", "n1": 1.2, "n2": 1.5, "find": "n21"},
        },
    ],
    "concept_scattering": [
        {
            "question_text": "Light is scattered by particles in a colloidal smoke chamber where the speed of light is 299000000 m/s. If the speed of light in vacuum is 300000000 m/s, calculate the refractive index of the medium.",
            "gold_answer": "1.0033",
            "difficulty": "easy",
            "calculation": {"formula": "absolute_refractive_index", "v": 299000000, "find": "n"},
        },
        {
            "question_text": "Light scatters across two air layers with absolute refractive indices 1.2 and 1.5. Calculate the relative refractive index of the second layer with respect to the first.",
            "gold_answer": "1.25",
            "difficulty": "medium",
            "calculation": {"formula": "relative_index_from_absolute", "n1": 1.2, "n2": 1.5, "find": "n21"},
        },
    ],
    "concept_electric_current": [
        {
            "question_text": "A current of 0.5 A is drawn by a filament of an electric bulb for 600 s. Find the amount of electric charge that flows through the circuit.",
            "gold_answer": "300 C",
            "difficulty": "easy",
            "calculation": {"formula": "charge_current", "i": 0.5, "t": 600, "find": "q"},
        },
        {
            "question_text": "An electric charge of 120 C flows through a conductor in 20 seconds. Calculate the electric current.",
            "gold_answer": "6 A",
            "difficulty": "medium",
            "calculation": {"formula": "charge_current", "q": 120, "t": 20, "find": "i"},
        },
    ],
    "concept_potential_difference": [
        {
            "question_text": "How much work is done in moving a charge of 2 C across two points having a potential difference of 12 V?",
            "gold_answer": "24 J",
            "difficulty": "easy",
            "calculation": {"formula": "voltage_work_charge", "q": 2, "v": 12, "find": "w"},
        },
        {
            "question_text": "A work of 100 J is done to move a charge of 5 C between two points. Find the potential difference between them.",
            "gold_answer": "20 V",
            "difficulty": "medium",
            "calculation": {"formula": "voltage_work_charge", "w": 100, "q": 5, "find": "v"},
        },
    ],
    "concept_ohms_law": [
        {
            "question_text": "A potential difference of 12 V is applied across a 4 ohm resistor. Find the current flowing through it.",
            "gold_answer": "3 A",
            "difficulty": "easy",
            "calculation": {"formula": "ohms_law", "v": 12, "r": 4, "find": "i"},
        },
        {
            "question_text": "A potential difference of 24 V is applied across a conductor carrying a current of 6 A. Find its resistance.",
            "gold_answer": "4 ohm",
            "difficulty": "medium",
            "calculation": {"formula": "ohms_law", "v": 24, "i": 6, "find": "r"},
        },
        {
            "question_text": "A current of 0.5 A flows through a 100 ohm resistor. Find the potential difference across it.",
            "gold_answer": "50 V",
            "difficulty": "hard",
            "calculation": {"formula": "ohms_law", "i": 0.5, "r": 100, "find": "v"},
        },
    ],
    "concept_factors_resistance": [
        {
            "question_text": "A copper wire has a length of 10 m and cross-sectional area of 0.0001 m^2. If its resistivity is 0.000017 ohm m, calculate its resistance.",
            "gold_answer": "1.7 ohm",
            "difficulty": "easy",
            "calculation": {"formula": "resistivity", "length": 10, "area": 0.0001, "rho": 0.000017, "find": "r"},
        },
        {
            "question_text": "A wire has a radius of 0.001 m. Find its cross-sectional area.",
            "gold_answer": "3.14159e-06 m^2",
            "difficulty": "medium",
            "calculation": {"formula": "wire_area", "radius": 0.001},
        },
    ],
    "concept_series_combination": [
        {
            "question_text": "Two resistors of 4 ohm and 6 ohm are connected in series across a 12 V battery. Calculate the equivalent resistance.",
            "gold_answer": "10 ohm",
            "difficulty": "easy",
            "calculation": {"formula": "series_resistance", "resistors": [4, 6]},
        },
        {
            "question_text": "Three resistors of 2 ohm, 3 ohm, and 5 ohm are connected in series. Find their total resistance.",
            "gold_answer": "10 ohm",
            "difficulty": "medium",
            "calculation": {"formula": "series_resistance", "resistors": [2, 3, 5]},
        },
    ],
    "concept_parallel_combination": [
        {
            "question_text": "Two resistors of 6 ohm and 3 ohm are connected in parallel across a 6 V battery. Calculate the effective resistance.",
            "gold_answer": "2 ohm",
            "difficulty": "easy",
            "calculation": {"formula": "parallel_resistance", "resistors": [6, 3]},
        },
        {
            "question_text": "Two resistors of 6 ohm and 3 ohm are connected in parallel across a 6 V battery. Calculate the current in the 3 ohm resistor.",
            "gold_answer": "2 A",
            "difficulty": "medium",
            "calculation": {"formula": "ohms_law", "v": 6, "r": 3, "find": "i"},
        },
    ],
    "concept_resistors_parallel": [
        {
            "question_text": "Two resistors of 6 ohm and 3 ohm are connected in parallel across a 6 V battery. Calculate the effective resistance.",
            "gold_answer": "2 ohm",
            "difficulty": "easy",
            "calculation": {"formula": "parallel_resistance", "resistors": [6, 3]},
        },
        {
            "question_text": "Two resistors of 6 ohm and 3 ohm are connected in parallel across a 6 V battery. Calculate the current in the 3 ohm resistor.",
            "gold_answer": "2 A",
            "difficulty": "medium",
            "calculation": {"formula": "ohms_law", "v": 6, "r": 3, "find": "i"},
        },
    ],
    "concept_resistors_combination": [
        {
            "question_text": "Two resistors of 10 ohm and 10 ohm are connected in parallel. Calculate their equivalent resistance.",
            "gold_answer": "5 ohm",
            "difficulty": "easy",
            "calculation": {"formula": "parallel_resistance", "resistors": [10, 10]},
        },
        {
            "question_text": "Two resistors of 5 ohm and 15 ohm are connected in series. Find their total resistance.",
            "gold_answer": "20 ohm",
            "difficulty": "medium",
            "calculation": {"formula": "series_resistance", "resistors": [5, 15]},
        },
    ],
    "concept_joules_heating": [
        {
            "question_text": "A 20 ohm resistor carries a current of 5 A for 30 seconds. Calculate the heat produced in joules.",
            "gold_answer": "15000 J",
            "difficulty": "easy",
            "calculation": {"formula": "joule_heating", "r": 20, "i": 5, "t": 30, "find": "h"},
        },
        {
            "question_text": "A 10 ohm resistor carries a current of 2 A for 10 seconds. Calculate the heat generated in joules.",
            "gold_answer": "400 J",
            "difficulty": "medium",
            "calculation": {"formula": "joule_heating", "r": 10, "i": 2, "t": 10, "find": "h"},
        },
    ],
    "concept_joule_heating": [
        {
            "question_text": "A 20 ohm resistor carries a current of 5 A for 30 seconds. Calculate the heat produced in joules.",
            "gold_answer": "15000 J",
            "difficulty": "medium",
            "calculation": {"formula": "joule_heating", "r": 20, "i": 5, "t": 30, "find": "h"},
        },
    ],
    "concept_electric_power": [
        {
            "question_text": "An electric bulb is connected to a 220 V generator. The current is 0.5 A. What is the power of the bulb?",
            "gold_answer": "110 W",
            "difficulty": "easy",
            "calculation": {"formula": "power_voltage_current", "v": 220, "i": 0.5, "find": "p"},
        },
        {
            "question_text": "An electric heater of resistance 20 ohm carries a current of 5 A. Calculate the power dissipated in the heater.",
            "gold_answer": "500 W",
            "difficulty": "medium",
            "calculation": {"formula": "power_current_resistance", "r": 20, "i": 5, "find": "p"},
        },
    ],
}


def get_existing_questions(concept_id: str, limit: int = 15) -> list[str]:
    """Retrieve existing question prompts from the bank for this concept to avoid generating duplicates."""
    try:
        import sqlite3
        from socratic_tutor.tools import question_bank
        conn = sqlite3.connect(question_bank.DB_PATH)
        rows = conn.execute(
            "SELECT prompt FROM questions WHERE concept_id = ? ORDER BY id DESC LIMIT ?",
            (concept_id, limit),
        ).fetchall()
        conn.close()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def select_question(
    concept_id: str,
    difficulty: str = "medium",
    existing_questions: list[str] | None = None,
) -> dict[str, Any]:
    cg = ConceptGraph()
    concept_info = cg.concepts.get(concept_id, {})
    title = concept_info.get("title") or concept_id.replace("concept_", "").replace("_", " ").title()

    prompt = f"Concept: {title} (ID: {concept_id})\nDifficulty: {difficulty}\n"
    if concept_id in CONCEPT_FORMULA_HINTS:
        recommended = CONCEPT_FORMULA_HINTS[concept_id]
        prompt += f"Recommended formula(s) for this concept: {', '.join(recommended)}.\n"

    existing: list[str] = list(existing_questions or [])
    for bq in get_existing_questions(concept_id):
        if bq not in existing:
            existing.append(bq)

    if existing:
        prompt += (
            "\nThe following questions ALREADY exist in the bank. You MUST create a different question "
            "with DIFFERENT numerical values, scenario, or asking for a different quantity (do NOT duplicate or rephrase these):\n"
        )
        for ex in existing[:10]:
            prompt += f"- {ex}\n"

    # PR-2 (R4): the solver's formula list, so the model names a formula and its inputs exactly as code expects.
    prompt = prompt + "\nFormulas you may use:\n" + solver_key.formula_list_for_the_model()
    res = llm.chat_json(prompt=prompt, system_prompt=QUESTION_SETTER_PROMPT, temperature=0.7)

    # PR-2 (R4): a usable reply has a question and a calculation.
    if isinstance(res, dict) and res.get("question_text") and res.get("calculation") and "error" not in res:
        solved = solver_key.solve_answer_key(res["question_text"], res["calculation"])
        if solved.get("ok") is True:
            res.setdefault("concept_id", concept_id)
            res.setdefault("difficulty", difficulty)
            return res

        # Attempt one targeted repair if the solver rejected the first draft
        repair_prompt = (
            prompt
            + f"\n\nNote: The solver rejected your draft with error: {solved.get('error')}.\n"
            "Please fix the error and output a valid question and calculation matching the New Cartesian sign convention and solver rules."
        )
        res_retry = llm.chat_json(prompt=repair_prompt, system_prompt=QUESTION_SETTER_PROMPT, temperature=0.7)
        if isinstance(res_retry, dict) and res_retry.get("question_text") and res_retry.get("calculation") and "error" not in res_retry:
            solved_retry = solver_key.solve_answer_key(res_retry["question_text"], res_retry["calculation"])
            if solved_retry.get("ok") is True:
                res_retry.setdefault("concept_id", concept_id)
                res_retry.setdefault("difficulty", difficulty)
                return res_retry

    fallback_entry = CONCEPT_FALLBACK_QUESTIONS.get(concept_id)
    if not fallback_entry:
        return {"error": f"No question generated or fallback available for concept '{concept_id}'"}

    if isinstance(fallback_entry, list):
        matching = [q for q in fallback_entry if q.get("difficulty") == difficulty]
        fallback = matching[0] if matching else fallback_entry[0]
    else:
        fallback = fallback_entry

    result = {
        "concept_id": concept_id,
        "difficulty": fallback.get("difficulty", difficulty),
        "question_text": fallback["question_text"],
        "gold_answer": fallback["gold_answer"],
        # PR-2 (R4): marks a fixed fallback question, so the teacher view can say the model gave none.
        "source": "fallback",
    }
    if "calculation" in fallback:
        result["calculation"] = fallback["calculation"]
    return result

