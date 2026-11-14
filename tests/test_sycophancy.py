"""Tests for dynamic anti-sycophancy defense, misconception resolution, and core physics grounding."""

from __future__ import annotations

from socratic_tutor.agents import diagnostician, tutor
from socratic_tutor.graph import node_diagnostician
from socratic_tutor.prompts import TUTOR_PROMPT, PROMPT_VERSION


def test_keyword_matcher_catches_conventional_current_misconception():
    """Verify keyword matcher identifies MISCON_ELEC_01 dynamically from student concluding current flows negative to positive."""
    catalog = diagnostician._load_catalog()
    elec_catalog = [m for m in catalog if m.get("chapter") == "Electricity"]
    query = "I see, so current flows from negative pole to positive pole"
    res = diagnostician.match_misconception_by_keywords(query, elec_catalog)
    assert res is not None
    assert res["identified_misconception_id"] == "MISCON_ELEC_01"
    assert "description" in res
    assert "scaffolding_hint" in res
    assert "diagnostic_probe" in res


def test_node_diagnostician_prioritizes_active_chapter():
    """Verify node_diagnostician with Electricity chapter identifies MISCON_ELEC_01 rather than cross-chapter Light misconception."""
    state = {
        "query": "I see, so current flows from negative pole to positive pole",
        "chapter": "11",
        "current_concept_id": "concept_electric_current",
        "messages": [],
    }
    out = node_diagnostician(state)
    diag = out.get("identified_misconception")
    assert diag is not None
    assert diag["id"] == "MISCON_ELEC_01"
    assert diag.get("scaffolding_hint") is not None
    assert diag.get("diagnostic_probe") is not None


def test_tutor_instructions_include_dynamic_misconception_scaffold():
    """Verify tutor instructions dynamically format misconception scaffolding and anti-sycophancy rules."""
    miscon = {
        "id": "MISCON_ELEC_01",
        "name": "Conventional current follows electron flow",
        "description": "The learner assumes conventional current arrow points in same direction as electron motion.",
        "scaffolding_hint": "Recall which sign of charge was historically used to define current direction.",
        "diagnostic_probe": "How would you decide the direction of the conventional current arrow?",
    }
    desc, extra = tutor._instructions(
        hint_level=1,
        approved_lesson=None,
        remediation=None,
        misconception=miscon,
        conversation_history=None,
        learner_context=None,
    )
    extra_text = " ".join(extra)
    assert "Targeted Misconception: Conventional current follows electron flow" in extra_text
    assert "Scaffolding Hint for this mix-up: Recall which sign" in extra_text
    assert "Diagnostic Probe to ask: How would you decide" in extra_text
    assert "ANTI-SYCOPHANCY RULE" in extra_text


def test_tutor_prompt_invariants_forbid_false_validation():
    """Verify TUTOR_PROMPT contains strict anti-sycophancy constraints (Invariant 7 and 12)."""
    assert "CRITICAL: Never apply this if the student's statement contains an error, inverted premise, or misconception" in TUTOR_PROMPT
    assert '<invariant id="12">' in TUTOR_PROMPT
    assert "Anti-Sycophancy &amp; Core Scientific Grounding" in TUTOR_PROMPT
    assert PROMPT_VERSION.startswith("2026-11-14")
