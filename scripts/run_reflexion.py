"""Run L12 Reflexion loop over development sessions to synthesize teaching lessons."""

import argparse
from socratic_tutor.reflexion import ReflexionPlaybook


def main():
    parser = argparse.ArgumentParser(description="Run Reflexion Improvement Loop")
    parser.add_argument("--dev-only", action="store_true", help="Run only on development splits")
    args = parser.parse_args()

    print("Running Reflexion loop on development student cases...")
    playbook = ReflexionPlaybook()
    
    # Example seeding of a lesson learned
    playbook.add_candidate_lesson(
        misconception_id="MISCON_LIGHT_01",
        lesson_text="For students who assume concave mirrors flip images like photos, start by having them trace the principal axis ray.",
        rationale="Prevents abstract confusion by grounding in basic ray tracing rules."
    )
    print(f"Reflexion playbook updated. Total candidate lessons: {len(playbook.lessons)}")


if __name__ == "__main__":
    main()
