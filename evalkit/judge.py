"""Cross-family LLM Judge for evaluating Socratic pedagogical quality."""

from socratic_tutor import llm, config

JUDGE_PROMPT = """You are an independent educational evaluator.
Assess the tutoring interaction based on:
1. Socratic Scaffolding: Did the tutor guide rather than give away the answer? (Score 0-5)
2. NCERT Grounding: Was the hint factually aligned with NCERT? (Score 0-5)
3. Misconception Targeting: Did the tutor address the student's actual error? (Score 0-5)

Return JSON with {scaffolding_score, grounding_score, targeting_score, overall_verdict, rationale}.
"""


def evaluate_transcript(transcript: str) -> dict:
    prompt = f"Transcript:\n{transcript}\n"
    return llm.chat_json(prompt=prompt, system_prompt=JUDGE_PROMPT, model=config.JUDGE_MODEL)
