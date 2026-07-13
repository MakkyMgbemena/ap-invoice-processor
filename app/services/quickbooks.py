"""
app.services.quickbooks
-----------------------
QuickBooks Online Bill submission service.
Fires after an invoice is approved.

Token behavior:
- Reads QuickBooks OAuth tokens from app/services/qb.tokens.json first.
- Falls back to .env values if the JSON file is missing/incomplete.
- On 401, refreshes once, writes the rotated token pair back to qb.tokens.json,
  then retries the failed QuickBooks request once.
"""

import base64
import json
import logging
import os
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

TOKEN_FILE = Path(__file__).with_name("qb.tokens.json")

QB_SANDBOX = os.getenv("QB_SANDBOX", "true").lower() == "true"
QB_CLIENT_ID = os.getenv("QB_CLIENT_ID", "")
QB_CLIENT_SECRET = os.getenv("QB_CLIENT_SECRET", "")
QB_AP_ACCOUNT_ID = os.getenv("QB_AP_ACCOUNT_ID", "31")
QB_EXPENSE_ACCOUNT_ID = os.getenv("QB_EXPENSE_ACCOUNT_ID", "13")

BASE_URL = (
    "https://sandbox-quickbooks.api.intuit.com"
    if QB_SANDBOX
    else "https://quickbooks.api.intuit.com"
)
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"


def _load_token_file() -> dict:
    if not TOKEN_FILE.exists():
        return {}

    try:
        data = json.loads(TOKEN_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error("[QuickBooks] Could not read token file | path=%s error=%s", TOKEN_FILE, e)
        return {}


_TOKEN_DATA = _load_token_file()

QB_REALM_ID = os.getenv("QB_REALM_ID") or _TOKEN_DATA.get("realm_id", "")
QB_ACCESS_TOKEN = _TOKEN_DATA.get("access_token") or os.getenv("QB_ACCESS_TOKEN", "")
QB_REFRESH_TOKEN = _TOKEN_DATA.get("refresh_token") or os.getenv("QB_REFRESH_TOKEN", "")


def _save_token_file(tokens: dict) -> None:
    current = _load_token_file()

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in")

    if access_token:
        current["access_token"] = access_token
    if refresh_token:
        current["refresh_token"] = refresh_token

    current["realm_id"] = QB_REALM_ID
    current["token_type"] = tokens.get("token_type", current.get("token_type", "bearer"))

    if expires_in:
        current["expires_at"] = int(time.time()) + int(expires_in) - 60
    elif "expires_at" not in current:
        current["expires_at"] = None

    TOKEN_FILE.write_text(json.dumps(current, indent=2) + "\n")


def _basic_auth_header() -> str:
    raw = f"{QB_CLIENT_ID}:{QB_CLIENT_SECRET}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _qbo_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _as_money(value) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _as_qbo_date(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value[:10]
    return datetime.now(timezone.utc).date().isoformat()


def _vendor_name(invoice) -> str:
    return (getattr(invoice, "vendor", None) or "Unknown Vendor").strip() or "Unknown Vendor"


async def _refresh_access_token(client: httpx.AsyncClient) -> str | None:
    global QB_ACCESS_TOKEN, QB_REFRESH_TOKEN

    latest_tokens = _load_token_file()
    refresh_token = latest_tokens.get("refresh_token") or QB_REFRESH_TOKEN

    if not all([QB_CLIENT_ID, QB_CLIENT_SECRET, refresh_token]):
        logger.error("[QuickBooks] Missing client credentials or refresh token")
        return None

    response = await client.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        headers={
            "Authorization": _basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )

    if response.status_code >= 400:
        logger.error(
            "[QuickBooks] Token refresh failed | status=%s body=%s",
            response.status_code,
            response.text,
        )
        return None

    tokens = response.json()
    access_token = tokens.get("access_token")
    new_refresh_token = tokens.get("refresh_token")

    if not access_token:
        logger.error("[QuickBooks] Token refresh response missing access_token")
        return None

    QB_ACCESS_TOKEN = access_token
    os.environ["QB_ACCESS_TOKEN"] = access_token

    if new_refresh_token:
        QB_REFRESH_TOKEN = new_refresh_token
        os.environ["QB_REFRESH_TOKEN"] = new_refresh_token

    _save_token_file(tokens)

    logger.info("[QuickBooks] Access token refreshed and saved successfully")
    return access_token


async def _qbo_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    access_token: str,
    *,
    retry_on_401: bool = True,
    **kwargs,
) -> httpx.Response:
    headers = kwargs.pop("headers", {}) or {}
    headers.setdefault("Accept", "application/json")
    headers["Authorization"] = f"Bearer {access_token}"

    if "json" in kwargs:
        headers.setdefault("Content-Type", "application/json")

    response = await client.request(method, url, headers=headers, **kwargs)

    if response.status_code == 401 and retry_on_401:
        logger.info("[QuickBooks] Token rejected; refreshing and retrying request once")
        refreshed = await _refresh_access_token(client)

        if refreshed:
            headers["Authorization"] = f"Bearer {refreshed}"
            response = await client.request(method, url, headers=headers, **kwargs)

    response.raise_for_status()
    return response


async def _qbo_query(client: httpx.AsyncClient, access_token: str, query: str) -> dict:
    response = await _qbo_request(
        client,
        "GET",
        f"{BASE_URL}/v3/company/{QB_REALM_ID}/query",
        access_token,
        params={"query": query, "minorversion": "65"},
    )
    return response.json()


async def _get_or_create_vendor(
    client: httpx.AsyncClient,
    access_token: str,
    display_name: str,
) -> dict:
    escaped_name = _qbo_escape(display_name)
    data = await _qbo_query(
        client,
        access_token,
        f"select Id, DisplayName from Vendor where DisplayName = '{escaped_name}' maxresults 1",
    )

    vendors = data.get("QueryResponse", {}).get("Vendor", [])
    if vendors:
        vendor = vendors[0]
        return {"value": vendor["Id"], "name": vendor.get("DisplayName", display_name)}

    response = await _qbo_request(
        client,
        "POST",
        f"{BASE_URL}/v3/company/{QB_REALM_ID}/vendor",
        access_token,
        params={"minorversion": "65"},
        json={"DisplayName": display_name},
    )

    vendor = response.json().get("Vendor", {})
    vendor_id = vendor.get("Id")
    if not vendor_id:
        raise RuntimeError("QuickBooks vendor creation response missing Vendor.Id")

    logger.info("[QuickBooks] Vendor created | name=%s vendor_id=%s", display_name, vendor_id)
    return {"value": vendor_id, "name": vendor.get("DisplayName", display_name)}


def _build_bill_payload(invoice, vendor_ref: dict) -> dict:
    amount = _as_money(getattr(invoice, "subtotal", None) or getattr(invoice, "total_amount", None))

    return {
        "VendorRef": vendor_ref,
        "APAccountRef": {"value": QB_AP_ACCOUNT_ID},
        "TotalAmt": _as_money(getattr(invoice, "total_amount", None) or amount),
        "DueDate": _as_qbo_date(getattr(invoice, "due_date", None)),
        "Line": [
            {
                "DetailType": "AccountBasedExpenseLineDetail",
                "Amount": amount,
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": QB_EXPENSE_ACCOUNT_ID}
                },
            }
        ],
        "PrivateNote": (
            "Auto-submitted via AP Pipeline | "
            f"Document ID: {getattr(invoice, 'document_id', '')}"
        ),
    }


async def push_to_quickbooks(invoice) -> dict:
    """
    Submit an approved invoice to QuickBooks Online as a Bill.
    Returns a dict with keys: success (bool), qb_bill_id (str), message (str).
    """
    doc_id = invoice.document_id

    if not QB_REALM_ID:
        mock_id = f"MOCK-QB-{uuid.uuid4().hex[:8].upper()}"
        logger.info(
            "[QuickBooks] No realm configured; skipping API call | doc=%s mock_bill_id=%s",
            doc_id,
            mock_id,
        )
        return {
            "success": True,
            "qb_bill_id": mock_id,
            "message": "Mock submission - no realm configured",
        }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token_data = _load_token_file()
            access_token = token_data.get("access_token") or os.getenv("QB_ACCESS_TOKEN") or QB_ACCESS_TOKEN

            if not access_token:
                access_token = await _refresh_access_token(client)

            if not access_token:
                logger.error("[QuickBooks] Missing QB access token")
                return {
                    "success": False,
                    "qb_bill_id": None,
                    "message": "QB credentials not configured",
                }

            vendor_ref = await _get_or_create_vendor(client, access_token, _vendor_name(invoice))
            payload = _build_bill_payload(invoice, vendor_ref)

            response = await _qbo_request(
                client,
                "POST",
                f"{BASE_URL}/v3/company/{QB_REALM_ID}/bill",
                access_token,
                params={"minorversion": "65"},
                json=payload,
            )

            data = response.json()
            bill_id = data.get("Bill", {}).get("Id", "unknown")

            logger.info("[QuickBooks] Bill created | doc=%s qb_bill_id=%s", doc_id, bill_id)
            return {
                "success": True,
                "qb_bill_id": bill_id,
                "message": "Bill created in QuickBooks",
            }

    except httpx.HTTPStatusError as e:
        logger.error(
            "[QuickBooks] HTTP error | doc=%s status=%s body=%s",
            doc_id,
            e.response.status_code,
            e.response.text,
        )
        return {
            "success": False,
            "qb_bill_id": None,
            "message": f"QB API error: {e.response.status_code}",
        }
    except Exception as e:
        logger.error("[QuickBooks] Unexpected error | doc=%s error=%s", doc_id, str(e))
        return {"success": False, "qb_bill_id": None, "message": str(e)}