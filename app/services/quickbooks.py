"""
app.services.quickbooks
-----------------------
QuickBooks Online Bill submission service.
Fires after an invoice is approved via the email approval link.

Environment variables required:
  QB_SANDBOX=true           # Set false in production
  QB_CLIENT_ID=...
  QB_CLIENT_SECRET=...
  QB_REALM_ID=...           # Company ID from QB
  QB_ACCESS_TOKEN=...       # OAuth2 bearer token

Sources:
- QuickBooks Online Bill API:
  https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities/bill
- OAuth2 flow:
  https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization
"""

import logging
import os
import uuid
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

QB_SANDBOX     = os.getenv("QB_SANDBOX", "true").lower() == "true"
QB_REALM_ID    = os.getenv("QB_REALM_ID", "")
QB_ACCESS_TOKEN = os.getenv("QB_ACCESS_TOKEN", "")

BASE_URL = (
    "https://sandbox-quickbooks.api.intuit.com"
    if QB_SANDBOX
    else "https://quickbooks.api.intuit.com"
)


def _build_bill_payload(invoice) -> dict:
    """Map Invoice model fields to a QuickBooks Bill object."""
    return {
        "VendorRef": {"name": invoice.vendor or "Unknown Vendor"},
        "TotalAmt": float(invoice.total_amount or 0),
        "DueDate": (
            invoice.due_date.strftime("%Y-%m-%d")
            if invoice.due_date
            else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ),
        "Line": [
            {
                "DetailType": "AccountBasedExpenseLineDetail",
                "Amount": float(invoice.subtotal or invoice.total_amount or 0),
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": "7", "name": "Accounts Payable"}
                },
            }
        ],
        "PrivateNote": f"Auto-submitted via AP Pipeline | Document ID: {invoice.document_id}",
    }


async def push_to_quickbooks(invoice) -> dict:
    """
    Submit an approved invoice to QuickBooks Online as a Bill.
    In sandbox mode, skips the real API call and returns a mock response.
    Returns a dict with keys: success (bool), qb_bill_id (str), message (str).
    """
    doc_id = invoice.document_id

    if not QB_ACCESS_TOKEN or not QB_REALM_ID:
        mock_id = f"MOCK-QB-{uuid.uuid4().hex[:8].upper()}"
        logger.info(
            "[QuickBooks] 🟡 SANDBOX — skipping real API | doc=%s mock_bill_id=%s",
            doc_id, mock_id,
        )
        return {"success": True, "qb_bill_id": mock_id, "message": "Mock submission — no credentials configured"}

    if not QB_REALM_ID or not QB_ACCESS_TOKEN:
        logger.error("[QuickBooks] ❌ Missing QB_REALM_ID or QB_ACCESS_TOKEN")
        return {"success": False, "qb_bill_id": None, "message": "QB credentials not configured"}

    url = f"{BASE_URL}/v3/company/{QB_REALM_ID}/bill?minorversion=65"
    headers = {
        "Authorization": f"Bearer {QB_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = _build_bill_payload(invoice)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            bill_id = data.get("Bill", {}).get("Id", "unknown")
            logger.info("[QuickBooks] ✅ Bill created | doc=%s qb_bill_id=%s", doc_id, bill_id)
            return {"success": True, "qb_bill_id": bill_id, "message": "Bill created in QuickBooks"}
    except httpx.HTTPStatusError as e:
        logger.error("[QuickBooks] ❌ HTTP error | doc=%s status=%s body=%s", doc_id, e.response.status_code, e.response.text)
        return {"success": False, "qb_bill_id": None, "message": f"QB API error: {e.response.status_code}"}
    except Exception as e:
        logger.error("[QuickBooks] ❌ Unexpected error | doc=%s error=%s", doc_id, str(e))
        return {"success": False, "qb_bill_id": None, "message": str(e)}
