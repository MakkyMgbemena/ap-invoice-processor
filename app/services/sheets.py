"""
app.services.sheets
-------------------
Appends one audit row to the AP Invoice Audit Log Google Sheet
every time an invoice changes status.

Columns (A–J):
  Timestamp | Invoice ID | Filename | Vendor | Amount | Currency |
  Old Status | New Status | QB Bill ID | Notes
"""

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

SPREADSHEET_ID = os.getenv("SHEETS_SPREADSHEET_ID", "")
CREDS_PATH = os.getenv("SHEETS_CREDS_PATH", "/app/sheets_creds.json")
SHEET_NAME = "Sheet1"


def _get_client():
    """Return an authenticated gspread client, or None if not configured."""
    if not SPREADSHEET_ID:
        logger.warning("[Sheets] SHEETS_SPREADSHEET_ID not set — skipping")
        return None, None
    if not os.path.exists(CREDS_PATH):
        logger.warning("[Sheets] Creds file not found at %s — skipping", CREDS_PATH)
        return None, None
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ]
        creds = Credentials.from_service_account_file(CREDS_PATH, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        return client, sheet
    except Exception as exc:
        logger.error("[Sheets] Auth failed: %s", exc)
        return None, None


def ensure_header(sheet) -> None:
    """Write header row if the sheet is empty."""
    try:
        first = sheet.row_values(1)
        if not first:
            sheet.append_row([
                "Timestamp", "Invoice ID", "Filename", "Vendor",
                "Amount", "Currency", "Old Status", "New Status",
                "QB Bill ID", "Notes"
            ], value_input_option="RAW")
    except Exception as exc:
        logger.error("[Sheets] Header write failed: %s", exc)


def log_status_change(
    invoice_id: str,
    filename: str = "",
    vendor: str = "",
    amount: float = 0.0,
    currency: str = "CAD",
    old_status: str = "",
    new_status: str = "",
    qb_bill_id: str = "",
    notes: str = "",
) -> bool:
    """Append one row to the audit sheet. Returns True on success."""
    _, sheet = _get_client()
    if sheet is None:
        return False
    try:
        ensure_header(sheet)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        sheet.append_row([
            ts, invoice_id, filename, vendor,
            amount, currency, old_status, new_status,
            qb_bill_id, notes,
        ], value_input_option="USER_ENTERED")
        logger.info(
            "[Sheets] ✅ Audit row appended | invoice=%s status=%s→%s",
            invoice_id, old_status, new_status,
        )
        return True
    except Exception as exc:
        logger.error("[Sheets] Row append failed: %s", exc)
        return False
