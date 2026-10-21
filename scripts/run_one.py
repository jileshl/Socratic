"""Run a single student query through the Socratic graph with detailed trace logging."""

import argparse
from socratic_tutor.graph import build_graph


def main():
    parser = argparse.ArgumentParser(description="Run one student query through Socratic Tutor")
    parser.add_argument("query", type=str, help="Student question or statement")
    parser.add_argument("--student", type=str, default="student_dev_01", help="Pseudonymous student ID")
    parser.add_argument("--mode", type=str, default="practice", choices=["practice", "quiz"], help="Interaction mode")
    args = parser.parse_args()

    app = build_graph()
    initial_state = {
        "session_id": "test_session_01",
        "student_id": args.student,
        "mode": args.mode,
        "query": args.query,
        "messages": [],
        "steps": [],
        "mastery_map": {},
        "hint_step": 1
    }

    print(f"\nExecuting query: '{args.query}' (Mode: {args.mode})")
    final_state = app.invoke(initial_state)

    print("\n--- Execution Steps ---")
    for step in final_state.get("steps", []):
        print(f"-> {step}")

    print("\n--- Socratic Tutor Response ---")
    print(final_state.get("response", "No response generated."))
    if final_state.get("citations"):
        print(f"\nCitations: {final_state['citations']}")


if __name__ == "__main__":
    main()
