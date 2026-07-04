import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── GCP / Document AI ─────────────────────────────────────────
PROJECT_ID        = os.getenv("GCP_PROJECT_ID", "your-project-id")
LOCATION          = os.getenv("GCP_LOCATION", "us")
PROCESSOR_ID      = os.getenv("GCP_PROCESSOR_ID", "your-processor-id")
PROCESSOR_VERSION = os.getenv("GCP_PROCESSOR_VERSION", "stable")   # was "rc" — changed to stable

# ── Cloud Storage ──────────────────────────────────────────────
INPUT_BUCKET  = os.getenv("GCS_INPUT_BUCKET", "your-input-bucket")
OUTPUT_BUCKET = os.getenv("GCS_OUTPUT_BUCKET", "your-output-bucket")
OUTPUT_PREFIX = "docai_output/"

# ── OpenAI ────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o")

# ── API settings ──────────────────────────────────────────────
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
DEBUG    = os.getenv("DEBUG", "false").lower() == "true"

# ── Local paths (dev only — gitignored in production) ─────────
BASE_DIR       = Path(__file__).parent
DATA_DIR       = BASE_DIR / "data"
INPUT_DIR      = DATA_DIR / "input"
OUTPUT_DIR     = DATA_DIR / "output"
DOC_STORE_PATH = OUTPUT_DIR / "document_store.json"


def init_dirs() -> None:
    """Create local dev directories. Call once at app startup — never at import time."""
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def validate_config() -> None:
    errors = []

    if not OPENAI_API_KEY:
        errors.append("OPENAI_API_KEY is not set.")

    if PROJECT_ID == "your-project-id":
        errors.append("GCP_PROJECT_ID is not set.")

    if PROCESSOR_ID == "your-processor-id":
        errors.append("GCP_PROCESSOR_ID is not set.")

    if INPUT_BUCKET == "your-input-bucket":
        errors.append("GCS_INPUT_BUCKET is not set.")

    if OUTPUT_BUCKET == "your-output-bucket":
        errors.append("GCS_OUTPUT_BUCKET is not set.")

    VALID_LOCATIONS = {"us", "eu"}
    if LOCATION not in VALID_LOCATIONS:
        errors.append(
            f"GCP_LOCATION '{LOCATION}' is invalid. Must be 'us' or 'eu'."
        )

    if not PROCESSOR_VERSION or PROCESSOR_VERSION.strip() == "":
        errors.append("GCP_PROCESSOR_VERSION is not set.")

    if errors:
        raise EnvironmentError(
            "OCR Pipeline — missing required config:\n " + "\n ".join(errors)
        )
