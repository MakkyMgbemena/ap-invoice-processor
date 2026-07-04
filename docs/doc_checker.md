# Document AI Service

**File:** `app/services/document_ai.py`  
**Purpose:** Handles all interaction with Google Cloud Storage and Google Document AI.

---

## What It Does

1. Uploads the local PDF to GCS (`gs://input-bucket/invoices/{doc_id}/filename.pdf`)
2. Calls Document AI using a `GcsDocument` request (URI path — not raw bytes)
3. Extracts full text and per-token confidence scores
4. Returns the updated `Invoice` model with `recognized_text`, `ocr.confidence`, and `ocr.page_count`

## Key Design Decisions

- **GcsDocument over RawDocument** — Supports files up to 20MB via GCS. RawDocument is limited to in-memory bytes and is less reliable for production use.
- **Average token confidence** — Confidence is averaged across all tokens on all pages to give a single quality signal.
- **GoogleAPICallError handling** — Caught explicitly; invoice status is set to `failed` and error message is persisted.

## Environment Variables Required

| Variable | Description |
|---|---|
| `GCP_PROJECT_ID` | Your GCP project ID |
| `GCP_LOCATION` | Processor region (`us` or `eu`) |
| `GCP_PROCESSOR_ID` | Document AI processor ID |
| `GCP_PROCESSOR_VERSION` | Processor version — set to `stable` |
| `GCS_INPUT_BUCKET` | Bucket for PDF uploads |

## References

- [Document AI Python Client](https://cloud.google.com/document-ai/docs/reference/rest)
- [GcsDocument vs RawDocument](https://cloud.google.com/document-ai/docs/send-request)
- [google-cloud-documentai PyPI](https://pypi.org/project/google-cloud-documentai/)
