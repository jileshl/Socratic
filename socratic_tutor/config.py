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
# NCERT PDFs are git-ignored (the guide forbids redistributing them). They live
# in data/ncert/ (scripts/fetch_ncert.py); older checkouts kept them in data/.
_DEFAULT_DOCUMENT_PATH = DATA_DIR / "ncert"
if not any(_DEFAULT_DOCUMENT_PATH.glob("*.pdf")) and any(DATA_DIR.glob("ch*.pdf")):
    _DEFAULT_DOCUMENT_PATH = DATA_DIR
DOCUMENT_PATH = _configured_path("DOCUMENT_PATH", _DEFAULT_DOCUMENT_PATH)
INDEX_DIR = BASE_DIR / ".index"
CACHE_DIR = BASE_DIR / ".cache"

# Ensure directories exist
INDEX_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# Versioned model config (config/models.yaml). Environment variables with the
# same UPPER_CASE name override a value for a one-off run.
MODEL_CONFIG_PATH = BASE_DIR / "config" / "models.yaml"


def _load_model_config() -> dict:
    try:
        import yaml
    except ImportError:  # pragma: no cover - yaml is in requirements.txt
        return {}
    if not MODEL_CONFIG_PATH.exists():
        return {}
    with open(MODEL_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


MODEL_CONFIG: dict = _load_model_config()
CONFIG_VERSION: str = str(MODEL_CONFIG.get("config_version", "unversioned"))


def _setting(section: str, key: str, default):
    env_value = os.getenv(key.upper())
    if env_value is not None:
        return type(default)(env_value) if not isinstance(default, str) else env_value
    return MODEL_CONFIG.get(section, {}).get(key, default)


# Model definitions (OpenRouter default)
SUPERVISOR_MODEL = _setting("models", "supervisor_model", "openai/gpt-4.1-mini")
SPECIALIST_MODEL = _setting("models", "specialist_model", "openai/gpt-4o-mini")
JUDGE_MODEL = _setting("models", "judge_model", "google/gemini-2.5-flash")
SIMULATED_STUDENT_MODEL = _setting("models", "simulated_student_model", "meta-llama/llama-3.3-70b-instruct")
EMBEDDING_MODEL = _setting("models", "embedding_model", "baai/bge-m3")

AGENT_TEMPERATURE = float(_setting("sampling", "agent_temperature", 0.2))
JUDGE_TEMPERATURE = float(_setting("sampling", "judge_temperature", 0.0))
SIMULATED_STUDENT_TEMPERATURE = float(_setting("sampling", "simulated_student_temperature", 0.7))

MAX_LLM_CALLS_PER_TURN = int(_setting("budgets", "max_llm_calls_per_turn", 12))
MAX_SESSION_TURNS = int(_setting("budgets", "max_session_turns", 6))
CASE_TIMEOUT_SECONDS = int(_setting("budgets", "case_timeout_seconds", 180))

PROMPT_FILES: dict[str, str] = dict(MODEL_CONFIG.get("prompts", {}))


def load_prompt(name: str) -> str:
    """Read a versioned prompt file named in config/models.yaml."""
    relative = PROMPT_FILES.get(name)
    if not relative:
        raise KeyError(f"No prompt named {name!r} in {MODEL_CONFIG_PATH}")
    return (BASE_DIR / relative).read_text(encoding="utf-8")


# Evaluation locations. eval_heldout/ is mounted only into the eval container;
# nothing under socratic_tutor/ may read it (tests/test_heldout_isolation.py).
RESULTS_DIR = _configured_path("RESULTS_DIR", BASE_DIR / "results")
EVAL_DIR = BASE_DIR / "eval"
EVAL_HELDOUT_DIR = _configured_path("EVAL_HELDOUT_DIR", BASE_DIR / "eval_heldout")

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
