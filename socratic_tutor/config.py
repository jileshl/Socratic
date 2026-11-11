"""Global configuration settings for Socratic Tutor."""

import hashlib
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
# Generated documents, e.g. docs/mcp_tool_list.json from scripts/export_tool_list.py.
# Like DATA_DIR it can be set in .env, and a relative value is read relative to the repository.
DOCS_DIR = _configured_path("DOCS_DIR", BASE_DIR / "docs")
INDEX_DIR = _configured_path("INDEX_DIR", BASE_DIR / ".index")
CACHE_DIR = _configured_path("CACHE_DIR", BASE_DIR / ".cache")
EVAL_RESULTS_DIR = _configured_path("EVAL_RESULTS_DIR", BASE_DIR / "evalkit" / "results")  # git-ignored
TRACES_DIR = CACHE_DIR / "traces"  # scrubbed traces from the app and the eval harness

# Ensure directories exist
INDEX_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# Version & Local Server
CONFIG_VERSION = os.getenv("CONFIG_VERSION", "0.2.0")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# LLM Providers & API Keys
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# Model definitions (OpenRouter default)
SUPERVISOR_MODEL = os.getenv("SUPERVISOR_MODEL", "openai/gpt-4.1-mini")
SPECIALIST_MODEL = os.getenv("SPECIALIST_MODEL", "openai/gpt-4o-mini")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "google/gemini-3.1-flash-lite")
# Guardrails (R4): Content guard checks messages and replies for content unsafe for minors (capstone guide p.5).
GUARD_MODEL = os.getenv("GUARD_MODEL", "openai/gpt-4o-mini")
# "on" in the app. "off" skips the guard model and the pasted-homework reader (unit tests set it off).
GUARD_MODELS = os.getenv("GUARD_MODELS", "on")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "baai/bge-m3")
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# Socratic Policy Thresholds
MAX_HINT_STEPS = 3                 # Teacher-validated limit before switching strategy
PASSING_MASTERY_THRESHOLD = 0.70   # Required mastery to advance to dependent concept
MASTERY_WINDOW_SIZE = 3            # Rolling quiz-score window used for concept mastery
STUCK_FAILURE_COUNT = 3            # Consecutive below-threshold quiz results on one concept
STUCK_SESSION_COUNT = STUCK_FAILURE_COUNT  # Backward-compatible alias; counts failures, not sessions
VERIFY_LEAK_THRESHOLD = 0.85       # Similarity threshold to flag potential answer leak
RRF_K = 60                         # Reciprocal Rank Fusion parameter

# Teacher & Security Auth
TEACHER_PIN = os.getenv("TEACHER_PIN", "1234")
TEACHER_SECRET = os.getenv("TEACHER_SECRET", "")
OPS_DEMO = os.getenv("OPS_DEMO", "0")
EVAL_STUB = os.getenv("EVAL_STUB", "")

# Approval gate (R4): the server-only key that signs the teacher's decisions (socratic_tutor/approval_gate.py).
# A secret: set it in .env (Docker gets it through env_file), never in git. Empty = no decision can be made.
APPROVAL_SIGNING_KEY = os.getenv("APPROVAL_SIGNING_KEY", "")


def get_teacher_pin() -> str:
    """Return the active teacher PIN (checking env for dynamic overrides in tests)."""
    return os.getenv("TEACHER_PIN", TEACHER_PIN)


def get_teacher_secret() -> bytes:
    """Derive teacher auth secret from explicit secret or seed derived from PIN and BASE_DIR."""
    explicit = os.getenv("TEACHER_SECRET", TEACHER_SECRET)
    pin = get_teacher_pin()
    seed = explicit or f"{pin}|{BASE_DIR}"
    return hashlib.sha256(seed.encode()).digest()


# Tool hooks (R4, socratic_tutor/tool_hooks.py): the budget for ONE student turn, shared by all agents.
# Starting values, to be tuned from the "tool-hooks" log lines.
MAX_TOOL_CALLS_PER_TURN = int(os.getenv("MAX_TOOL_CALLS_PER_TURN", "20"))     # the 21st tool call in a turn is blocked
MAX_IDENTICAL_TOOL_CALLS = int(os.getenv("MAX_IDENTICAL_TOOL_CALLS", "2"))    # the same tool + same arguments a 3rd time is blocked

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
# Longest reply any model call may write. OpenRouter reserves credit for this many tokens on every
# call, so leaving it unset (the model maximum, up to 65,536) fails on keys with a low credit limit.
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1500"))
JUDGE_TEMPERATURE = float(os.getenv("JUDGE_TEMPERATURE", "0.0"))
SIMULATED_STUDENT_TEMPERATURE = float(os.getenv("SIMULATED_STUDENT_TEMPERATURE", "0.7"))

MAX_LLM_CALLS_PER_TURN = int(os.getenv("MAX_LLM_CALLS_PER_TURN", "12"))   # graph recursion budget per student turn
GRAPH_RECURSION_LIMIT = int(os.getenv("GRAPH_RECURSION_LIMIT", str(2 * MAX_LLM_CALLS_PER_TURN + 5)))
MAX_SESSION_TURNS = int(os.getenv("MAX_SESSION_TURNS", "6"))               # tutor turns in one simulated session
CASE_TIMEOUT_SECONDS = int(os.getenv("CASE_TIMEOUT_SECONDS", "180"))       # an eval case slower than this counts as a timeout

STUCK_MINUTES_ON_PROBLEM = 10      # Teacher-validated: flag a learner after 10+ minutes on one problem
CI_MIN_RECALL_AT_5 = 0.90          # CI gate on dev retrieval queries: never below the BM25 baseline (README)
