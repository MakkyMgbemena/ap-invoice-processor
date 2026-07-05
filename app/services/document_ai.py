from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import documentai

from app.config import (
    LOCATION,
    PROCESSOR_ID,
    PROCESSOR_VERSION,
    PROJECT_ID,
)
from app.models.invoice import Invoice, OCRMeta, ProcessingStatus

logger = logging.getLogger(__name__)


# ── Client (module-level singleton) ─────────────────────────────

def _doc_ai_client() -> documentai.DocumentProcessorServiceClient:
    opts = {"api_endpoint": f"{LOCATION}-documentai.googleapis.com"}
    return documentai.DocumentProcessorServiceClient(client_options=opts)


# ── Core OCR call ─────────────────────────────────────────────

def run_ocr(invoice: Invoice) -> Invoice:
    """
    Submit invoice PDF to Document AI (online, synchronous).
    Reads raw bytes from invoice.file_path and sends directly to the
    online processor — no GCS upload or polling required.
    Returns the mutated Invoice.
    """
    if not invoice.file_path:
        raise ValueError(f"Invoice {invoice.document_id} has no file_path set.")

    invoice.status = ProcessingStatus.OCR_START
    invoice.timestamps.ocr_start = datetime.now(timezone.utc)
    logger.info("[%s] OCR starting — file: %s", invoice.document_id, invoice.file_path)

    client = _doc_ai_client()

    processor_name = client.processor_version_path(
        PROJECT_ID, LOCATION, PROCESSOR_ID, PROCESSOR_VERSION
    )

    file_content = Path(invoice.file_path).read_bytes()

    raw_document = documentai.RawDocument(
        content=file_content,
        mime_type="application/pdf",
    )

    request = documentai.ProcessRequest(
        name=processor_name,
        raw_document=raw_document,
        skip_human_review=True,
    )

    try:
        result = client.process_document(request=request)
        document = result.document
    except GoogleAPICallError as exc:
        invoice.error.stage   = "ocr"
        invoice.error.message = str(exc)
        invoice.status        = ProcessingStatus.FAILED
        logger.error("[%s] Document AI call failed: %s", invoice.document_id, exc)
        return invoice

    text = document.text or ""

    confidences: list[float] = []
    for page in document.pages:
        for token in page.tokens:
            confidences.append(token.layout.confidence)

    avg_confidence = round(sum(confidences) / len(confidences), 4) if confidences else None

    invoice.ocr = OCRMeta(
        engine="google_document_ai",
        confidence=avg_confidence,
        page_count=len(document.pages),
    )

    invoice.recognized_text    = text
    invoice.status             = ProcessingStatus.OCR_DONE
    invoice.timestamps.ocr_end = datetime.now(timezone.utc)

    logger.info(
        "[%s] OCR complete — %d chars extracted, confidence %.2f",
        invoice.document_id,
        len(text),
        invoice.ocr.confidence,
    )
    return invoice
