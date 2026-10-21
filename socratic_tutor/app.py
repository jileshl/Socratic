"""Web Application UI & API service for Socratic Tutor."""

import os
from socratic_tutor.graph import build_graph


def main():
    print("Initializing Socratic Tutor service...")
    app = build_graph()
    print("Socratic Tutor graph successfully loaded.")
    # In future steps, start FastAPI or Gradio/Streamlit UI server
    print("Visit http://127.0.0.1:7860 to interact with Socratic Tutor.")


if __name__ == "__main__":
    main()
