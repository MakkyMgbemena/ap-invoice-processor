"""
app.utils.doc_checker
---------------------
Pre-flight document validation + structured logging setup.

Checks before any file hits GCS or Document AI:
  1. File exists on disk
  2. File is not empty
  3. File size is within the Document AI 20MB limit
  4. MIME type is application/pdf
  5. PDF magic bytes confirm it is a real PDF (not a renamed file)

Sources:
- Python `magic` (python-magic PyPI):
  https://pypi.org/project/python-magic/
- Document AI quotas & limits:
  https://cloud.google.com/document-ai/quotas
- Python `logging` stdlib:
  https://docs.python.org/3/library/logging.html
- Python `pathlib` stdlib:
  https://docs.python.org/3/library/pathlib.html
"""

import logging
import logging.config
import sys
from pathlib import Path

try:
    import magic  # python-magic
    _MAGIC_AVAILABLE = True
except ImportError:
    _MAGIC_AVAILABLE = False

# ── Limits ────────────────────────────────────────────────────────────────────
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB — Document AI hard limit
PDF_MAGIC_BYTES     = b"%PDF"


# ── Logging setup ─────────────────────────────────────────────────────────────

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "format": (
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
            ),
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        }
    },
    "handlers": {
        "stdout": {
            "class":     "logging.StreamHandler",
            "stream":    "ext://sys.stdout",
            "formatter": "structured",
        }
    },
    "root": {
        "level":    "INFO",
        "handlers": ["stdout"],
    },
})

def get_logger(name: str = "ocr_pipeline") -> logging.Logger:
    """
    Returns a consistently configured logger.
    Outputs structured log lines to stdout — compatible with
    Google Cloud Logging's structured JSON ingestion.
    """
    return logging.getLogger(name)


logger = get_logger(__name__)


# ── Pre-flight checks ─────────────────────────────────────────────────────────

class DocCheckError(ValueError):
    """Raised when a document fails pre-flight validation."""


def check_document(file_path: str | Path) -> Path:
    """
    Run all pre-flight checks on a document before processing.

    Returns the resolved Path if all checks pass.
    Raises DocCheckError with a human-readable message if any check fails.

    Checks:
        1. File exists
        2. File is not empty
        3. File size ≤ 20 MB
        4. MIME type is application/pdf  (if python-magic is installed)
        5. PDF magic bytes (%PDF header) are present
    """
    path = Path(file_path).resolve()

    # ── 1. Exists ─────────────────────────────────────────────────────────────
    if not path.exists():
        raise DocCheckError(f"File not found: {path}")

    # ── 2. Not empty ──────────────────────────────────────────────────────────
    size = path.stat().st_size
    if size == 0:
        raise DocCheckError(f"File is empty: {path}")

    # ── 3. Size limit ─────────────────────────────────────────────────────────
    if size > MAX_FILE_SIZE_BYTES:
        mb = size / (1024 * 1024)
        raise DocCheckError(
            f"File too large: {mb:.1f} MB (Document AI limit is 20 MB). "
            f"File: {path.name}"
        )

    # ── 4. MIME type (python-magic) ───────────────────────────────────────────
    if _MAGIC_AVAILABLE:
        mime = magic.from_file(str(path), mime=True)
        if mime != "application/pdf":
            raise DocCheckError(
                f"Invalid file type: expected application/pdf, got {mime}. "
                f"File: {path.name}"
            )
    else:
        logger.warning(
            "[DocChecker] python-magic not available — skipping MIME check. "
            "Install python-magic for full validation."
        )

    # ── 5. PDF magic bytes ────────────────────────────────────────────────────
    with open(path, "rb") as f:
        header = f.read(4)
    if header != PDF_MAGIC_BYTES:
        raise DocCheckError(
            f"File does not appear to be a valid PDF (bad magic bytes): {path.name}"
        )

    logger.info(
        f"[DocChecker] ✅ {path.name} passed all checks — "
        f"size={size / 1024:.1f} KB"
    )
    return path
