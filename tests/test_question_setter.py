"""Tests for the Question Setter agent, concept formula hints, and fallback coverage.

Verifies:
1. Every concept in concept_graph.json has valid formula hints in CONCEPT_FORMULA_HINTS.
2. Every concept in concept_graph.json has working fallback questions in CONCEPT_FALLBACK_QUESTIONS.
3. Every fallback question has a valid calculation that keys through solver_key.
4. Conceptual ray diagram questions with image_nature key properly and grade as expected.
5. In-flight solver verification and self-repair in select_question():
   - Retries with error feedback when the model generates an invalid draft (e.g. sign convention mismatch).
   - Falls back when generation fails.
6. End-to-end question proposing through graph.node_question_setter for previously failing concepts
   (such as concept_atmospheric_refraction, concept_myopia, concept_human_eye_structure,
   concept_factors_resistance).
"""

from typing import Any
import pytest

from socratic_tutor import graph, solver_key, llm
from socratic_tutor.agents import question_setter, grader
from socratic_tutor.concept_graph import ConceptGraph
from socratic_tutor.tools import math_tools_server


def test_all_concept_graph_concepts_have_hints_and_fallbacks() -> None:
    """Every concept in concept_graph.json must have valid formula hints and verified fallback questions."""
    cg = ConceptGraph()
    all_formulas = set(math_tools_server.OPTICS_FORMULAS.keys()) | set(math_tools_server.ELECTRICITY_FORMULAS.keys())

    assert len(cg.concepts) > 0
    for cid in cg.concepts:
        # Every concept in the graph has formula hints
        assert cid in question_setter.CONCEPT_FORMULA_HINTS, f"Missing hints for {cid}"
        hints = question_setter.CONCEPT_FORMULA_HINTS[cid]
        assert len(hints) > 0
        for f in hints:
            assert f in all_formulas, f"Unknown formula '{f}' in hints for {cid}"

        # Every concept in the graph has at least one fallback question
        assert cid in question_setter.CONCEPT_FALLBACK_QUESTIONS, f"Missing fallback for {cid}"
        entry = question_setter.CONCEPT_FALLBACK_QUESTIONS[cid]
        entries = entry if isinstance(entry, list) else [entry]
        for q in entries:
            assert "calculation" in q, f"Fallback for {cid} missing calculation"
            made = solver_key.draft_from_model_reply(cid, q.get("difficulty", "easy"), q)
            assert made["ok"] is True, f"Fallback keying failed for {cid}: {made.get('error')}"
            assert made["draft"]["gold_answer"] == q["gold_answer"]


def test_conceptual_image_nature_key_and_grade(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ray diagram questions using image_nature key to descriptive text and grade properly."""
    # Concave mirror with magnification m = -2 -> real and inverted, enlarged
    q = "A concave mirror produces an image with magnification m = -2. Find the nature of the image."
    calc = {"formula": "image_nature", "values": {"m": -2}, "find": "nature"}
    keyed = solver_key.solve_answer_key(q, calc)
    assert keyed["ok"] is True
    assert keyed["gold_answer"] == "real and inverted, enlarged"

    # Grade with exact match through rubric evaluation
    def mock_grader_chat(prompt: str, system_prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        return {"is_correct": True, "score": 1.0, "feedback": "Correct nature and size."}

    monkeypatch.setattr(llm, "chat_json", mock_grader_chat)
    res1 = grader.grade_answer("real and inverted, enlarged", keyed["gold_answer"], is_numeric=False)
    assert res1["is_correct"] is True

    # Convex mirror with magnification m = 0.5 -> virtual and erect, diminished
    q2 = "A convex mirror produces an image with magnification m = 0.5. Find the nature of the image."
    calc2 = {"formula": "image_nature", "values": {"m": 0.5}, "find": "nature"}
    keyed2 = solver_key.solve_answer_key(q2, calc2)
    assert keyed2["ok"] is True
    assert keyed2["gold_answer"] == "virtual and erect, diminished"


def test_select_question_in_flight_repair_for_sign_convention(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the LLM gives a positive radius for a concave mirror, select_question sends the solver error for repair."""
    calls: list[dict] = []

    def mock_chat_json(prompt: str, system_prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        calls.append({"prompt": prompt, "system_prompt": system_prompt})
        if len(calls) == 1:
            return {
                "question_text": "A concave mirror has a radius of curvature of 30 cm. Find its focal length.",
                "calculation": {
                    "formula": "focal_length_from_radius",
                    "values": {"radius_of_curvature": 30},
                    "length_unit": "cm",
                    "find": "f",
                },
            }
        else:
            return {
                "question_text": "A concave mirror has a radius of curvature of 30 cm. Find its focal length.",
                "calculation": {
                    "formula": "focal_length_from_radius",
                    "values": {"radius_of_curvature": -30},
                    "length_unit": "cm",
                    "find": "f",
                },
            }

    monkeypatch.setattr(llm, "chat_json", mock_chat_json)
    res = question_setter.select_question("concept_spherical_mirrors", "easy")
    assert len(calls) == 2
    assert "radius_of_curvature must be negative" in calls[1]["prompt"]
    assert res["calculation"]["values"]["radius_of_curvature"] == -30


def test_end_to_end_question_proposal_for_challenging_concepts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concepts previously failing (refraction, myopia, eye structure, resistance) propose successfully."""
    def model_down(prompt: str, system_prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        return {"error": "LLM offline"}

    monkeypatch.setattr(llm, "chat_json", model_down)

    test_concepts = [
        "concept_atmospheric_refraction",
        "concept_myopia",
        "concept_human_eye_structure",
        "concept_accommodation",
        "concept_presbyopia",
        "concept_factors_resistance",
        "concept_prism_refraction",
        "concept_dispersion",
        "concept_rainbow_formation",
        "concept_scattering",
    ]

    for cid in test_concepts:
        state = {"current_concept_id": cid, "question_set_size": 2, "turn_steps": []}
        res = graph.node_question_setter(state)
        proposed = res.get("proposed_set", {})
        assert proposed.get("ok") is True, f"Failed proposing for {cid}: {proposed}"
        assert len(proposed.get("question_ids", [])) >= 1
        assert len(proposed.get("refused", [])) == 0, f"Refused items in {cid}: {proposed.get('refused')}"


def test_select_question_injects_concept_title_and_formula_hints(monkeypatch: pytest.MonkeyPatch) -> None:
    """select_question prompt includes human-readable concept title and recommended formulas."""
    recorded_prompts: list[str] = []

    def capture_prompt(prompt: str, system_prompt: str = "", **kwargs: Any) -> dict[str, Any]:
        recorded_prompts.append(prompt)
        return {
            "question_text": "A current of 0.5 A flows for 600 s. Find charge.",
            "calculation": {"formula": "charge_current", "values": {"i": 0.5, "t": 600}, "find": "q"},
        }

    monkeypatch.setattr(llm, "chat_json", capture_prompt)
    res = question_setter.select_question("concept_electric_current", "easy")
    assert len(recorded_prompts) == 1
    prompt = recorded_prompts[0]
    assert "Electric Current and Circuit" in prompt
    assert "charge_current" in prompt
    assert res.get("question_text") is not None
