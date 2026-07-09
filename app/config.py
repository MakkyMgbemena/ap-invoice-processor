import os
from dotenv import load_dotenv

# ── GCP Core ──────────────────────────────────────────────────────────────────
GCP_PROJECT_ID        = os.getenv("GCP_PROJECT_ID",        "project-24b04b3d-fdd9-4b07-855")
GCP_LOCATION          = os.getenv("GCP_LOCATION",          "us")
GCP_REGION            = os.getenv("GCP_REGION",            "us-central1")

# ── Document AI ───────────────────────────────────────────────────────────────
GCP_PROCESSOR_ID      = os.getenv("GCP_PROCESSOR_ID",      "813591c0e321b52b")
GCP_PROCESSOR_VERSION = os.getenv("GCP_PROCESSOR_VERSION", "stable")

# ── Cloud Storage ─────────────────────────────────────────────────────────────
GCS_INPUT_BUCKET      = os.getenv("GCS_INPUT_BUCKET",      "ocr-invoice-input-prod")

# ── Service Account ───────────────────────────────────────────────────────────
GOOGLE_APPLICATION_CREDENTIALS = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS", "/secrets/ocr-pipeline-sa-key.json"
)

# ── OpenAI ────────────────────────────────────────────────────────────────────
OPENAI_API_KEY        = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL          = os.getenv("OPENAI_MODEL", "gpt-4o")

# ── App ───────────────────────────────────────────────────────────────────────
APP_ENV               = os.getenv("APP_ENV",           "production")
LOG_LEVEL             = os.getenv("LOG_LEVEL",         "INFO")
MAX_FILE_SIZE_MB      = int(os.getenv("MAX_FILE_SIZE_MB", "20"))

# ── Server ────────────────────────────────────────────────────────────────────
API_HOST    = os.getenv("API_HOST", "0.0.0.0")
API_PORT    = int(os.getenv("PORT", "8080"))
DEBUG       = os.getenv("APP_ENV", "production") != "production"


def validate_config() -> None:
    import logging
    logger = logging.getLogger(__name__)
    required = {"GCP_PROJECT_ID": GCP_PROJECT_ID, "GCP_PROCESSOR_ID": GCP_PROCESSOR_ID}
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(f"Missing required config vars: {missing}")
    if not OPENAI_API_KEY:
        logger.warning("[Config] OPENAI_API_KEY not set — AI features disabled.")
    logger.info(f"[Config] {APP_ENV} | {GCP_REGION} | port {API_PORT}")


def init_dirs() -> None:
    for d in ("/tmp/uploads", "/tmp/outputs"):
        os.makedirs(d, exist_ok=True)

# ── Service aliases (used by services layer) ──────────────────────────────────
PROJECT_ID        = GCP_PROJECT_ID
LOCATION          = GCP_LOCATION
PROCESSOR_ID      = GCP_PROCESSOR_ID
PROCESSOR_VERSION = GCP_PROCESSOR_VERSION
INPUT_BUCKET      = GCS_INPUT_BUCKET

# ── Output Storage ────────────────────────────────────────────────────────────
OUTPUT_BUCKET  = os.getenv("GCS_OUTPUT_BUCKET", "ocr-invoice-output-prod")
OUTPUT_PREFIX  = os.getenv("GCS_OUTPUT_PREFIX", "ocr-output/")

# ── Local Paths ───────────────────────────────────────────────────────────────
from pathlib import Path

load_dotenv()
INPUT_DIR      = Path(os.getenv("INPUT_DIR",      "/tmp/uploads"))
DOC_STORE_PATH = Path(os.getenv("DOC_STORE_PATH", "/tmp/doc_store.json"))

# ── Email Notification ────────────────────────────────────────────────────────
SMTP_HOST     = os.getenv("SMTP_HOST",     "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER",     "")   # your Gmail address
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")   # Gmail App Password
NOTIFY_EMAIL  = os.getenv("NOTIFY_EMAIL",  "")   # who receives the alert
BASE_URL      = os.getenv("BASE_URL",      "http://localhost:8082")
