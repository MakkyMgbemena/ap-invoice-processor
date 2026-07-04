# API Reference

**File:** `app/routes/invoice.py`  
**Base URL:** `http://localhost:8000`  
**Interactive docs:** `http://localhost:8000/docs`

---

## Endpoints

### `POST /invoices/upload`
Upload a PDF invoice and start the OCR pipeline.

**Request:** `multipart/form-data` with field `file` (PDF, max 20MB)  
**Response:** `202 Accepted`
```json
{
  "document_id": "uuid",
  "file_name": "invoice.pdf",
  "status": "ingested",
  "message": "Invoice accepted. Processing started in background."
}
---

### `GET /invoices/{document_id}`
Poll the processing status of an uploaded invoice.

**Path parameter:** `document_id` — the UUID returned from the upload endpoint  
**Response:** `200 OK`
```json
{
  "document_id": "uuid",
  "file_name": "invoice.pdf",
  "status": "processing"
}
