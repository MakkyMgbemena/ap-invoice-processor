"""
app.utils
---------
Shared utilities for the OCR pipeline.

    doc_checker — Pre-flight PDF validation + structured logging
"""

from app.utils.doc_checker import (
    check_document,
    get_logger,
    DocCheckError,
)

__all__ = [
    "check_document",
    "get_logger",
    "DocCheckError",
]
