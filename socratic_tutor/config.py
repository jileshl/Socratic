"""Global configuration settings for Socratic Tutor."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _configured_path(variable: str, default: Path) -> Path:
    value = Path(os.getenv(variable, str(default))).expanduser()
    return value.resolve() if value.is_absolute() else (BASE_DIR / value).resolve()


DATA_DIR = _configured_path("DATA_DIR", BASE_DIR / "data")
DOCUMENT_PATH = _configured_path("DOCUMENT_PATH", DATA_DIR)
INDEX_DIR = BASE_DIR / ".index"
CACHE_DIR = BASE_DIR / ".cache"

# Ensure directories exist
INDEX_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# Model definitions (OpenRouter default)
SUPERVISOR_MODEL = os.getenv("SUPERVISOR_MODEL", "openai/gpt-4.1-mini")
SPECIALIST_MODEL = os.getenv("SPECIALIST_MODEL", "openai/gpt-4o-mini")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "google/gemini-2.5-flash")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "baai/bge-m3")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# Socratic Policy Thresholds
MAX_HINT_STEPS = 3                 # Teacher-validated limit before switching strategy
PASSING_MASTERY_THRESHOLD = 0.70   # Required mastery to advance to dependent concept
STUCK_SESSION_COUNT = 3            # Sessions without progress before triggering teacher alert
VERIFY_LEAK_THRESHOLD = 0.85       # Similarity threshold to flag potential answer leak
RRF_K = 60                         # Reciprocal Rank Fusion parameter

# Curriculum Scope
TARGET_CLASS = "10"
TARGET_SUBJECT = "Science"
TARGET_CHAPTERS = [
    "Light - Reflection and Refraction",
    "Human Eye and the Colourful World",
    "Electricity"
]

# --- Evaluation (R5) and operations (R6) -----------------------------------
# Kept here so every model ID, budget and threshold lives in this one file.
# Each evaluation run records these values and the git commit it ran on.
SIMULATED_STUDENT_MODEL = os.getenv("SIMULATED_STUDENT_MODEL", "meta-llama/llama-3.3-70b-instruct")  # not the agents' family
AGENT_TEMPERATURE = float(os.getenv("AGENT_TEMPERATURE", "0.2"))
JUDGE_TEMPERATURE = float(os.getenv("JUDGE_TEMPERATURE", "0.0"))
SIMULATED_STUDENT_TEMPERATURE = float(os.getenv("SIMULATED_STUDENT_TEMPERATURE", "0.7"))

MAX_LLM_CALLS_PER_TURN = int(os.getenv("MAX_LLM_CALLS_PER_TURN", "12"))   # graph recursion budget per student turn
MAX_SESSION_TURNS = int(os.getenv("MAX_SESSION_TURNS", "6"))               # tutor turns in one simulated session
CASE_TIMEOUT_SECONDS = int(os.getenv("CASE_TIMEOUT_SECONDS", "180"))       # an eval case slower than this counts as a timeout

STUCK_MINUTES_ON_PROBLEM = 10      # Teacher-validated: flag a learner after 10+ minutes on one problem
CI_MIN_RECALL_AT_5 = 0.90          # CI gate on dev retrieval queries: never below the BM25 baseline (README)

EVAL_RESULTS_DIR = _configured_path("EVAL_RESULTS_DIR", BASE_DIR / "evalkit" / "results")  # git-ignored
TRACES_DIR = CACHE_DIR / "traces"  # scrubbed traces from the app and the eval harness
