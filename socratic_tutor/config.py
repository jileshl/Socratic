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
# Generated documents, e.g. docs/mcp_tool_list.json from scripts/export_tool_list.py.
# Like DATA_DIR it can be set in .env, and a relative value is read relative to the repository.
DOCS_DIR = _configured_path("DOCS_DIR", BASE_DIR / "docs")
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
