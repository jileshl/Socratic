"""Environment and preflight checks."""

import sys
import os
from socratic_tutor import config


def main():
    print("Checking environment for Socratic Tutor...")
    print(f"Python: {sys.version}")
    
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("WARNING: Neither OPENROUTER_API_KEY nor OPENAI_API_KEY is set in environment.")
    else:
        print("API Key detected.")

    print(f"Target Chapters: {config.TARGET_CHAPTERS}")
    print(f"Index Directory: {config.INDEX_DIR}")
    print("Preflight check complete.")


if __name__ == "__main__":
    main()
