"""
app.services
------------
Core processing services for the OCR pipeline.

Services (imported lazily to avoid circular imports at startup):
    document_ai   — Google Document AI OCR + GCS upload/download
    llm_extractor — Regex + GPT-4o field extraction
    validator     — Invoice data validation engine
"""

# Services are imported directly in routes to keep startup fast.
# This file intentionally does not re-export — import explicitly:
#
#   from app.services.document_ai   import run_ocr
#   from app.services.llm_extractor import extract_invoice_fields
#   from app.services.validator     import validate_invoice
