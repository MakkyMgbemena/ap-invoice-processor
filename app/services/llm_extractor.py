"""
app.services.llm_extractor
--------------------------
Two-stage invoice field extraction:
  Stage 1 — Regex fast-path (zero cost, instant)
  Stage 2 — GPT-4o fallback (handles messy/unstructured OCR output)

Sources:
- OpenAI Python SDK v1.x:
  https://github.com/openai/openai-python
- OpenAI Chat Completions API:
  https://platform.openai.com/docs/api-reference/chat
- Python re module:
  https://docs.python.org/3/library/re.html
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Sequence
from openai import OpenAI, OpenAIError
from decimal import Decimal
from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.models import Invoice, LineItem, ProcessingStatus

logger = logging.getLogger(__name__)


def _openai_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY must be set before calling the LLM extractor.")
    return OpenAI(api_key=OPENAI_API_KEY, max_retries=6, timeout=30.0)

# ── Regex patterns ─────────────────────────────────────────────────────────────

_VENDOR_RE    = re.compile(r"(?:from|vendor|bill(?:ed)?\s+to)[:\s]+([A-Za-z0-9&',.\- ]{3,60})", re.I)
_INV_NUM_RE   = re.compile(
    r"(?:invoice|inv)(?:\s*(?:#|number|no\.?))\s*[:\-]?\s*([A-Z0-9\-]{3,20})",
    re.I,
)
_DATE_RE      = re.compile(r"(?:invoice\s+date|date)[:\s]+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", re.I)
_DUE_DATE_RE  = re.compile(r"(?:due\s+date|payment\s+due)[:\s]+(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})", re.I)
_TOTAL_RE     = re.compile(
    r"\b(?:total(?:\s+due)?|amount\s+due|balance\s+due)\b[:\s]*\$?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
    re.I,
)
_SUBTOTAL_RE  = re.compile(r"subtotal[:\s]*\$?\s*([0-9,]+(?:\.[0-9]{1,2})?)", re.I)
_TAX_RE       = re.compile(r"(?:tax|gst|hst|vat)[:\s]*\$?\s*([0-9,]+(?:\.[0-9]{1,2})?)", re.I)
_LINE_ITEM_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9\s\-&']{2,40}?)\s+"
    r"(\d+(?:\.\d+)?)\s+"
    r"\$?\s*([0-9,]+(?:\.[0-9]{1,2})?)\s+"
    r"\$?\s*([0-9,]+(?:\.[0-9]{1,2})?)",
    re.I,
)


def _clean(text: str) -> str:
    """Collapse whitespace and normalize newlines for regex matching."""
    return re.sub(r"\s{2,}", " ", text.replace("\n", " ")).strip()


def _to_decimal(raw) -> Decimal | None:
    if raw is None or raw == "":
        return None
    return Decimal(str(raw).replace(",", "")).quantize(Decimal("0.01"))


def _parse_line_items(raw_text: str) -> list[LineItem]:
    line_items: list[LineItem] = []
    for line in raw_text.splitlines():
        if not line.strip():
            continue
        match = _LINE_ITEM_RE.search(line)
        if not match:
            continue

        name, qty, unit_price, total = match.groups()
        line_items.append(
            LineItem(
                name=name.strip().title(),
                quantity=_to_decimal(qty),
                unit_price=_to_decimal(unit_price),
                total=_to_decimal(total),
            )
        )
    return line_items


def _find_field(raw_text: str, pattern: re.Pattern[str]) -> str | None:
    for line in raw_text.splitlines():
        if not line.strip():
            continue
        match = pattern.search(line)
        if match:
            return match.group(1).strip()
    return None


# ── Stage 1: Regex fast-path ───────────────────────────────────────────────────

def _first_nonempty_line(raw_text: str) -> str | None:
    for line in raw_text.splitlines():
        value = line.strip()
        if value:
            return value
    return None


def parse_with_regex(raw_text: str) -> dict:
    """
    Extract invoice fields using compiled regex patterns.
    Returns a partial dict — missing fields are None (filled by LLM stage).
    """
    line_items = _parse_line_items(raw_text)

    return {
        "vendor":         _find_field(raw_text, _VENDOR_RE),
        "invoice_number": _find_field(raw_text, _INV_NUM_RE),
        "invoice_date":   _find_field(raw_text, _DATE_RE),
        "due_date":       _find_field(raw_text, _DUE_DATE_RE),
        "total_amount":   _to_decimal(_find_field(raw_text, _TOTAL_RE)),
        "subtotal":       _to_decimal(_find_field(raw_text, _SUBTOTAL_RE)),
        "tax":            _to_decimal(_find_field(raw_text, _TAX_RE)),
        "line_items":     line_items,
    }


# ── Stage 2: GPT-4o fallback ───────────────────────────────────────────────────

def parse_with_llm(raw_text: str, partial: dict) -> dict:
    """
    Send OCR text to GPT-4o to fill in any fields that regex missed.
    Only called when one or more critical fields are None.
    """
    missing = [k for k, v in partial.items() if v is None and k != "line_items"]
    if not missing and partial.get("line_items"):
        logger.info("[LLM] Regex captured all fields — skipping GPT-4o call")
        return partial

    client = _openai_client()

    prompt = f"""
You are an invoice data extraction assistant.
Extract the following fields from the OCR text below.
Return ONLY valid JSON — no markdown, no explanation.

Fields to extract:
{{
  "vendor":         "string or null",
  "invoice_number": "string or null",
  "invoice_date":   "string (MM/DD/YYYY) or null",
  "due_date":       "string (MM/DD/YYYY) or null",
  "subtotal":       "number or null",
  "tax":            "number or null",
  "total_amount":   "number or null",
  "currency":       "string (e.g. USD, CAD) or null",
  "line_items": [
    {{"name": "string", "quantity": number, "unit_price": number, "total": number}}
  ]
}}

OCR TEXT:
{raw_text[:4000]}
"""
    # TODO: upgrade to structured outputs (client.beta.chat.completions.parse)
    #       when OpenAI schema validation is needed
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=60
        )
        extracted = json.loads(response.choices[0].message.content)
        logger.info(f"[LLM] GPT-4o extraction complete - fields: {list(extracted.keys())}")

        # Merge: regex wins where it already has a value
        for key, value in extracted.items():
            if key == "line_items":
                if not partial.get("line_items") and value:
                    partial["line_items"] = [
                        LineItem(**item) if isinstance(item, dict) else item
                        for item in value
                    ]
            elif not partial.get(key) and value is not None:
                partial[key] = value

        return partial

    except (OpenAIError, json.JSONDecodeError) as e:
        logger.error(f"[LLM] GPT-4o extraction failed: {e}")
        return partial


# ── Main entry point ───────────────────────────────────────────────────────────

def extract_invoice_fields(invoice: Invoice) -> Invoice:
    raw_text = invoice.recognized_text or ""
    if not raw_text:
        return invoice

    invoice.status = ProcessingStatus.EXTRACTING
    invoice.timestamps.extraction_start = datetime.now(timezone.utc)

    # Fast-path regex
    partial = parse_with_regex(raw_text)

    # Fallback LLM
    final_data = parse_with_llm(raw_text, partial)

    # Map back to model
    invoice.vendor         = final_data.get("vendor")
    invoice.invoice_number = final_data.get("invoice_number")
    invoice.invoice_date   = final_data.get("invoice_date")
    invoice.due_date       = final_data.get("due_date")
    invoice.subtotal       = _to_decimal(final_data.get("subtotal"))
    invoice.tax            = _to_decimal(final_data.get("tax"))
    invoice.total_amount   = _to_decimal(final_data.get("total_amount"))
    invoice.currency       = final_data.get("currency")
    invoice.line_items     = final_data.get("line_items") or []

    invoice.status = ProcessingStatus.VALIDATING
    invoice.timestamps.extraction_end = datetime.now(timezone.utc)
    return invoice
