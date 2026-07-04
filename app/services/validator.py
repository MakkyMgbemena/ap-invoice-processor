"""
app.services.validator
----------------------
Invoice data validation engine.

Checks:
  1. Required fields present (vendor, invoice_date, total_amount)
  2. Line item subtotal matches declared subtotal (within tolerance)
  3. subtotal + tax ≈ total_amount (within tolerance)
  4. Dates are parseable and not in the future
  5. Total amount is a positive number

Sources:
- Python `datetime` stdlib:
  https://docs.python.org/3/library/datetime.html
- Pydantic v2 field validation:
  https://docs.pydantic.dev/latest/concepts/validators/
"""

import logging
from datetime import datetime, timezone
from dateutil import parser as dateutil_parser
from decimal import Decimal
from app.models import Invoice, ProcessingStatus, ValidationFlag, ValidationResult

logger     = logging.getLogger(__name__)
TOLERANCE = Decimal("0.02")  # 2 cents tolerance for float rounding


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        parsed = dateutil_parser.parse(date_str)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, OverflowError):
        return None


def validate_invoice(invoice: Invoice) -> Invoice:
    """
    Run all validation checks against a fully extracted Invoice.
    Populates invoice.validation with a ValidationResult.
    Returns the updated invoice.
    """
    invoice.status = ProcessingStatus.VALIDATING
    issues: list[str] = []
    flag = ValidationFlag.PASS
    score = 1.0

    # ── Check 1: Required fields ──────────────────────────────────────────────
    required = {
        "vendor":         invoice.vendor,
        "invoice_date":   invoice.invoice_date,
        "total_amount":   invoice.total_amount,
    }
    for field_name, value in required.items():
        if not value:
            issues.append(f"Missing required field: {field_name}")
            score -= 0.2

    # ── Check 2: Total amount is positive ─────────────────────────────────────
    if invoice.total_amount is not None and invoice.total_amount <= 0:
        issues.append(f"total_amount must be positive, got {invoice.total_amount}")
        score -= 0.2

    # ── Check 3: Line items subtotal vs declared subtotal ─────────────────────
    if invoice.line_items:
        computed_subtotal = round(sum(item.total for item in invoice.line_items), 2)
        if invoice.subtotal is not None:
            diff = abs(computed_subtotal - invoice.subtotal)
            if diff > TOLERANCE:
                issues.append(
                    f"Line item subtotal {computed_subtotal} "
                    f"does not match declared subtotal {invoice.subtotal} "
                    f"(diff={diff:.2f})"
                )
                score -= 0.15

    # ── Check 4: subtotal + tax ≈ total_amount ────────────────────────────────
    if invoice.subtotal and invoice.total_amount:
        tax = invoice.tax if invoice.tax is not None else Decimal("0.0")
        computed = (invoice.subtotal + tax).quantize(Decimal("0.01"))
        diff       = abs(computed - invoice.total_amount)
        if diff > TOLERANCE:
            issues.append(
                f"subtotal ({invoice.subtotal}) + tax ({tax}) = {computed} "
                f"does not match total_amount ({invoice.total_amount}) "
                f"(diff={diff:.2f})"
            )
            score -= 0.15

    # ── Check 5: Invoice date is parseable and not in the future ──────────────
    if invoice.invoice_date:
        parsed_date = _parse_date(invoice.invoice_date)
        if parsed_date is None:
            issues.append(f"invoice_date '{invoice.invoice_date}' could not be parsed")
            score -= 0.1
        elif parsed_date > datetime.now(timezone.utc):
            issues.append(f"invoice_date '{invoice.invoice_date}' is in the future")
            score -= 0.1

    # ── Check 6: Due date is after invoice date ───────────────────────────────
    if invoice.invoice_date and invoice.due_date:
        inv_dt = _parse_date(invoice.invoice_date)
        due_dt = _parse_date(invoice.due_date)
        if inv_dt and due_dt and due_dt < inv_dt:
            issues.append(
                f"due_date '{invoice.due_date}' is before invoice_date '{invoice.invoice_date}'"
            )
            score -= 0.1

    # ── Determine flag ────────────────────────────────────────────────────────
    score = max(round(score, 2), 0.0)
    if score < 0.6:
        flag = ValidationFlag.FAIL
    elif issues:
        flag = ValidationFlag.WARNING

    invoice.validation = ValidationResult(
        flag=flag,
        score=score,
        issues=issues,
    )
    invoice.status = ProcessingStatus.COMPLETED if flag != ValidationFlag.FAIL else ProcessingStatus.FAILED
    invoice.timestamps.completed = datetime.now(timezone.utc)

    logger.info(
        f"[Validator] {invoice.document_id} — "
        f"flag={flag} | score={score} | issues={len(issues)}"
    )
    return invoice
