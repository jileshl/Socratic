import re
from pathlib import Path
from socratic_tutor.topics import topic_of

HTML_PATH = Path("socratic_tutor/web/static/student.html")
CSS_PATH = Path("socratic_tutor/web/static/style.css")


def test_starter_questions_mapped_to_topics():
    assert topic_of("Why is the image in a concave mirror upside down?") == "concept_concave_ray_diagrams"
    assert topic_of("Why does a pencil look bent in water?") == "concept_refraction_laws"
    assert topic_of("Why is the sky blue?") == "concept_scattering"
    assert topic_of("How does a concave lens correct short-sightedness?") == "concept_myopia"
    assert topic_of("Why does adding a resistor in parallel lower the total resistance?") == "concept_parallel_combination"
    assert topic_of("Why does a heater wire get hot?") == "concept_joules_heating"


def test_textarea_in_student_html():
    content = HTML_PATH.read_text(encoding="utf-8")
    # Verify textarea element exists with rows="2"
    assert '<textarea id="msg"' in content
    assert 'rows="2"' in content
    assert 'maxlength="4000"' in content
    assert "onkeydown=" in content
    assert "if(event.key==='Enter'&&!event.shiftKey)" in content


def test_composer_textarea_in_style_css():
    css = CSS_PATH.read_text(encoding="utf-8")
    assert ".composer textarea" in css
    assert "overflow-y: auto" in css
    assert "min-height:" in css
    assert "max-height:" in css


def test_dynamic_questions_logic_in_student_html():
    content = HTML_PATH.read_text(encoding="utf-8")
    # Check CONCEPT_QUESTIONS and STARTER_CONCEPTS
    assert "const CONCEPT_QUESTIONS =" in content
    assert "const STARTER_CONCEPTS =" in content
    assert "function isTopicCompleted(" in content
    assert "function getChapterQuestions(" in content
    assert "function renderChapterCards(" in content
    # Check that when score is 0, static starters are used
    assert "!hasProgress" in content
    # Check that completed topics do not come back
    assert "!isTopicCompleted" in content
    # Check click counter steering to learn from book if clicked > 2 times
    assert "starterClicks[clickKey] > 2" in content

