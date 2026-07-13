from app.services.sheets import log_status_change
"""
app.routes.invoice
------------------
FastAPI routes for the OCR invoice processing pipeline.

Endpoints:
  POST /invoices/upload          — Upload a PDF invoice and begin processing
  GET  /invoices/{document_id}/status   — Poll processing status
  GET  /invoices/{document_id}/results  — Retrieve extracted + validated data
  GET  /invoices/                — List all processed invoices

Sources:
- FastAPI file uploads:
  https://fastapi.tiangolo.com/tutorial/request-files/
- FastAPI path + response models:
  https://fastapi.tiangolo.com/tutorial/response-model/
- Python `aiofiles` for async file I/O:
  https://pypi.org/project/aiofiles/
"""

import json
import logging
import aiofiles
import asyncio
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, HTMLResponse
from datetime import datetime, timezone
from app.services.email_notifier import send_invoice_notification
from app.services.quickbooks import push_to_quickbooks

from app.config import INPUT_DIR, DOC_STORE_PATH
from app.models import (
    Invoice,
    ProcessingStatus,
    InvoiceUploadResponse,
    InvoiceStatusResponse,
    InvoiceResultResponse,
)
from app.services.document_ai   import run_ocr
from app.services.llm_extractor import extract_invoice_fields
from app.services.validator     import validate_invoice
from app.utils.doc_checker      import check_document, DocCheckError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/invoices", tags=["Invoices"])


# ── Document store helpers ────────────────────────────────────────────────────

def _load_store() -> list[dict]:
    if DOC_STORE_PATH.exists():
        with open(DOC_STORE_PATH, "r") as f:
            return json.load(f)
    return []


def _save_store(data: list[dict]) -> None:
    with open(DOC_STORE_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _get_invoice(document_id: str) -> dict:
    store = _load_store()
    for record in store:
        if record["document_id"] == document_id:
            return record
    return None


def _upsert_invoice(invoice: Invoice) -> None:
    store = _load_store()
    record = invoice.model_dump()
    for i, existing in enumerate(store):
        if existing["document_id"] == invoice.document_id:
            store[i] = record
            _save_store(store)
            return
    store.append(record)
    _save_store(store)


# ── Background pipeline ───────────────────────────────────────────────────────

def _run_pipeline(invoice: Invoice) -> None:
    """
    Full OCR → Extract → Validate pipeline.
    Runs as a background task so the upload endpoint returns immediately.
    Errors at any stage are captured on the Invoice and persisted.
    """
    try:
        # Stage 1: OCR
        invoice = run_ocr(invoice)
        _upsert_invoice(invoice)

        # Stage 2: Field extraction
        invoice = extract_invoice_fields(invoice)
        _upsert_invoice(invoice)

        # Stage 3: Validation
        invoice = validate_invoice(invoice)
        _upsert_invoice(invoice)

        # Stage 4: Email notification
        send_invoice_notification(invoice)

        logger.info(f"[Pipeline] ✅ Completed — {invoice.document_id}")

    except Exception as e:
        invoice.status        = ProcessingStatus.FAILED
        invoice.error.stage = "pipeline"
        invoice.error.message = str(e)
        _upsert_invoice(invoice)
        logger.error(f"[Pipeline] ❌ Failed — {invoice.document_id}: {e}")


# ── Endpoints ─────────────────────────────────────────────────────────────────


def _confirmation_page(title: str, message: str, color: str) -> HTMLResponse:
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{title}</title>
        <style>
            body {{ font-family: -apple-system, sans-serif; display: flex; align-items: center;
                   justify-content: center; min-height: 100vh; margin: 0; background: #f5f5f5; }}
            .card {{ background: white; border-radius: 12px; padding: 48px; text-align: center;
                     box-shadow: 0 4px 24px rgba(0,0,0,0.08); max-width: 420px; width: 90%; }}
            .icon {{ font-size: 64px; margin-bottom: 16px; }}
            h1 {{ color: {color}; margin: 0 0 12px; font-size: 28px; }}
            p {{ color: #666; font-size: 16px; margin: 0; }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="icon">{"✅" if color == "#16a34a" else "❌"}</div>
            <h1>{title}</h1>
            <p>{message}</p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

@router.post(
    "/upload",
    response_model=InvoiceUploadResponse,
    status_code=202,
    summary="Upload a PDF invoice and start processing",
)
async def upload_invoice(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="PDF invoice file (max 20 MB)"),
):
    """
    Accepts a PDF upload, runs pre-flight checks, saves the file locally,
    creates an Invoice record, and kicks off the OCR pipeline as a
    background task. Returns 202 Accepted with the document_id immediately.
    """
    # ── Save upload to disk ───────────────────────────────────────────────────
    dest_path = INPUT_DIR / file.filename
    try:
        async with aiofiles.open(dest_path, "wb") as buffer:
            content = await file.read()
            await buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not save file: {e}")
    finally:
        file.file.close()

    MAX_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
    if dest_path.stat().st_size > MAX_SIZE_BYTES:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail="File exceeds 20 MB limit.")

    # ── Pre-flight doc check ──────────────────────────────────────────────────
    try:
        check_document(dest_path)
    except DocCheckError as e:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(e))

    # ── Create Invoice record ─────────────────────────────────────────────────
    invoice = Invoice(
        file_name=file.filename,
        file_path=str(dest_path),
    )
    _upsert_invoice(invoice)
    logger.info(f"[Upload] Ingested {invoice.document_id} — {file.filename}")

    # ── Kick off background pipeline ──────────────────────────────────────────
    background_tasks.add_task(asyncio.to_thread, _run_pipeline, invoice)

    return InvoiceUploadResponse(
        document_id=invoice.document_id,
        file_name=invoice.file_name,
        status=invoice.status,
        message="Invoice accepted. Processing started in background.",
    )


@router.get(
    "/{document_id}/status",
    response_model=InvoiceStatusResponse,
    summary="Poll the processing status of an invoice",
)
async def get_invoice_status(document_id: str):
    """
    Returns the current status and timestamps for an invoice.
    Poll this endpoint after upload to track pipeline progress.

    Status flow:
      ingested → ocr_start → ocr_done → extracting → validating → completed | failed
    """
    record = _get_invoice(document_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Invoice not found: {document_id}")

    invoice = Invoice.model_construct(**record)
    return InvoiceStatusResponse(
        document_id=invoice.document_id,
        status=invoice.status,
        timestamps=invoice.timestamps,
        error=invoice.error,
    )


@router.get(
    "/{document_id}/results",
    response_model=InvoiceResultResponse,
    summary="Get extracted and validated invoice data",
)
async def get_invoice_results(document_id: str):
    """
    Returns the fully extracted and validated invoice fields.
    Only available once status = 'completed' or 'failed'.
    """
    record = _get_invoice(document_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Invoice not found: {document_id}")

    invoice = Invoice.model_construct(**record)

    if invoice.status not in (ProcessingStatus.COMPLETED, ProcessingStatus.FAILED):
        raise HTTPException(
            status_code=409,
            detail=f"Invoice is still processing. Current status: {invoice.status}",
        )

    return InvoiceResultResponse(
        document_id=invoice.document_id,
        vendor=invoice.vendor,
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        subtotal=invoice.subtotal,
        tax=invoice.tax,
        total_amount=invoice.total_amount,
        currency=invoice.currency,
        line_items=invoice.line_items,
        validation=invoice.validation,
        status=invoice.status,
    )


@router.get(
    "/",
    summary="List all invoices",
)
async def list_invoices(
    status: str | None = None,
    limit: int = 50,
):
    """
    Returns a summary list of all invoices in the store.
    Optionally filter by status (e.g. ?status=completed).
    """
    store = _load_store()

    if status:
        store = [r for r in store if r.get("status") == status]

    # Return lightweight summary — not full record
    summaries = [
        {
            "document_id":  r.get("document_id"),
            "file_name":    r.get("file_name"),
            "status":       r.get("status"),
            "uploaded":     r.get("timestamps", {}).get("uploaded"),
            "total_amount": r.get("total_amount"),
            "vendor":       r.get("vendor"),
            "flag":         r.get("validation", {}).get("flag") if r.get("validation") else None,
            "approval_status": r.get("approval_status"),
            "approval_at":     r.get("approval_at"),
            "qb_bill_id":      r.get("qb_bill_id"),
            "qb_status":       r.get("qb_status"),
        }
        for r in store[:limit]
    ]

    return JSONResponse(content={"count": len(summaries), "invoices": summaries})


# ── Approval endpoints ────────────────────────────────────────────────────────

@router.get("/{document_id}/approve", response_class=HTMLResponse, tags=["Approvals"])
async def approve_invoice(document_id: str):
    """One-click approval from email link."""
    record = _get_invoice(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Invoice not found")
    invoice = Invoice.model_construct(**record)
    invoice.approval_status = "approved"
    qb_result = await push_to_quickbooks(invoice)
    invoice.qb_bill_id = qb_result.get("qb_bill_id")
    invoice.qb_status = "synced" if qb_result["success"] else "failed"
    invoice.approval_at     = datetime.now(timezone.utc)
    _upsert_invoice(invoice)
    log_status_change(
        invoice_id=invoice.document_id,
        filename=invoice.file_name,
        vendor=invoice.vendor or "",
        amount=float(invoice.total_amount or 0),
        currency=invoice.currency or "CAD",
        old_status="pending",
        new_status="approved",
        qb_bill_id=invoice.qb_bill_id or "",
        notes=qb_result.get("message", ""),
    )
    return """
    <html><body style='font-family:Arial,sans-serif;text-align:center;padding:80px;background:#f9fafb;'>
      <div style='max-width:400px;margin:auto;background:#fff;padding:40px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.08);'>
        <h1 style='color:#16a34a;'>✅ Approved</h1>
        <p style='color:#64748b;'>Invoice has been approved and is queued for ERP submission.</p>
        <p style='color:#94a3b8;font-size:0.85em;'>You can close this tab.</p>
      </div>
    </body></html>"""


@router.get("/{document_id}/reject", response_class=HTMLResponse, tags=["Approvals"])
async def reject_invoice(document_id: str):
    """One-click rejection from email link."""
    record = _get_invoice(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Invoice not found")
    invoice = Invoice.model_construct(**record)
    invoice.approval_status = "rejected"
    invoice.approval_at     = datetime.now(timezone.utc)
    _upsert_invoice(invoice)
    log_status_change(
        invoice_id=invoice.document_id,
        filename=invoice.file_name,
        vendor=invoice.vendor or "",
        amount=float(invoice.total_amount or 0),
        currency=invoice.currency or "CAD",
        old_status="pending",
        new_status="rejected",
        notes="Rejected by approver",
    )
    return """
    <html><body style='font-family:Arial,sans-serif;text-align:center;padding:80px;background:#f9fafb;'>
      <div style='max-width:400px;margin:auto;background:#fff;padding:40px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.08);'>
        <h1 style='color:#dc2626;'>❌ Rejected</h1>
        <p style='color:#64748b;'>Invoice has been marked as rejected. No further action will be taken.</p>
        <p style='color:#94a3b8;font-size:0.85em;'>You can close this tab.</p>
      </div>
    </body></html>"""
