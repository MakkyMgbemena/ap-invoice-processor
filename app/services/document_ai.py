from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import documentai, storage

from app.config import (
    INPUT_BUCKET,
    LOCATION,
    OUTPUT_BUCKET,
    OUTPUT_PREFIX,
    PROCESSOR_ID,
    PROCESSOR_VERSION,
    PROJECT_ID,
)
from app.models.invoice import Invoice, OCRMeta, ProcessingStatus

logger = logging.getLogger(__name__)


# ── Clients (module-level singletons) ─────────────────────────

def _doc_ai_client() -> documentai.DocumentProcessorServiceClient:
    opts = {"api_endpoint": f"{LOCATION}-documentai.googleapis.com"}
    return documentai.DocumentProcessorServiceClient(client_options=opts)


def _storage_client() -> storage.Client:
    return storage.Client()


# ── GCS helpers ───────────────────────────────────────────────

def upload_to_gcs(local_path: str | Path, document_id: str) -> str:
    """
    Upload a local file to the GCS input bucket.
    Returns the gs:// URI.
    """
    local_path = Path(local_path)
    blob_name  = f"uploads/{document_id}/{local_path.name}"

    client = _storage_client()
    bucket = client.bucket(INPUT_BUCKET)
    blob   = bucket.blob(blob_name)
    blob.upload_from_filename(str(local_path))

    uri = f"gs://{INPUT_BUCKET}/{blob_name}"
    logger.info("Uploaded %s → %s", local_path.name, uri)
    return uri


def _output_prefix(document_id: str) -> str:
    return f"{OUTPUT_PREFIX}{document_id}/"


# ── Core OCR call ─────────────────────────────────────────────

def run_ocr(invoice: Invoice) -> Invoice:
    """
    Submit invoice PDF to Document AI (batch async).
    Updates invoice status, OCR metadata, and GCS URIs in-place.
    Returns the mutated Invoice.
    """
    if not invoice.gcs_input_uri:
        raise ValueError(f"Invoice {invoice.document_id} has no gcs_input_uri set.")

    # Mark start
    invoice.status = ProcessingStatus.OCR_START
    invoice.timestamps.ocr_start = datetime.now(timezone.utc)
    logger.info("[%s] OCR starting — input: %s", invoice.document_id, invoice.gcs_input_uri)

    client = _doc_ai_client()

    processor_name = client.processor_version_path(
        PROJECT_ID, LOCATION, PROCESSOR_ID, PROCESSOR_VERSION
    )

    gcs_input = documentai.GcsDocument(
        gcs_uri=invoice.gcs_input_uri,
        mime_type="application/pdf",
    )
    input_config = documentai.BatchDocumentsInputConfig(
        gcs_documents=documentai.GcsDocuments(documents=[gcs_input])
    )

    gcs_output_uri = f"gs://{OUTPUT_BUCKET}/{_output_prefix(invoice.document_id)}"
    output_config  = documentai.DocumentOutputConfig(
        gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(
            gcs_uri=gcs_output_uri
        )
    )

    request = documentai.BatchProcessRequest(
        name=processor_name,
        input_documents=input_config,
        document_output_config=output_config,
    )

    try:
        operation = client.batch_process_documents(request=request)
        logger.info("[%s] Waiting for Document AI operation…", invoice.document_id)
        operation.result(timeout=300)          # 5-min hard timeout
    except GoogleAPICallError as exc:
        invoice.error.stage   = "ocr"
        invoice.error.message = str(exc)
        invoice.status        = ProcessingStatus.FAILED
        logger.error("[%s] Document AI call failed: %s", invoice.document_id, exc)
        return invoice

    # ── Read output from GCS ───────────────────────────────────
    invoice.gcs_output_uri = gcs_output_uri
    invoice, text = _extract_text_from_gcs(invoice)

    invoice.recognized_text      = text
    invoice.status               = ProcessingStatus.OCR_DONE
    invoice.timestamps.ocr_end   = datetime.now(timezone.utc)

    logger.info(
        "[%s] OCR complete — %d chars extracted, confidence %.2f",
        invoice.document_id,
        len(text),
        invoice.ocr.confidence or 0.0,
    )
    return invoice


# ── GCS output reader ──────────────────────────────────────────

def _extract_text_from_gcs(invoice: Invoice) -> tuple[Invoice, str]:
    """
    Read Document AI JSON output from GCS and extract full text + metadata.
    Returns (updated_invoice, full_text).
    """
    client  = _storage_client()
    bucket  = client.bucket(OUTPUT_BUCKET)
    prefix  = _output_prefix(invoice.document_id)
    blobs = list(bucket.list_blobs(prefix=prefix))

    if not blobs:
        invoice.error.stage   = "ocr_read"
        invoice.error.message = f"No output files found at gs://{OUTPUT_BUCKET}/{prefix}"
        invoice.status        = ProcessingStatus.FAILED
        return invoice, ""

    full_text   : list[str] = []
    total_conf  : list[float] = []
    total_pages : int = 0

    for blob in blobs:
        if not blob.name.endswith(".json"):
            continue

        raw      = blob.download_as_bytes()
        document = documentai.Document.from_json(raw)

        if document.text:
            full_text.append(document.text)

        # Confidence — average across all pages
        for page in document.pages:
            total_pages += 1
            if page.image_quality_scores:
                total_conf.append(page.image_quality_scores.quality_score)

    avg_confidence = round(sum(total_conf) / len(total_conf), 4) if total_conf else None

    invoice.ocr = OCRMeta(
        engine="google_document_ai",
        confidence=avg_confidence,
        page_count=total_pages,
    )

    return invoice, "\n\n".join(full_text)
