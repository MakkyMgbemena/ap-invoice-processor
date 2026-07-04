"""
tests.test_validator
--------------------
Unit tests for app.services.validator.

Tests:
  - Valid invoice passes all checks
  - Missing required fields generate issues + lower score
  - Line item mismatch is caught
  - Total math mismatch is caught
  - Future invoice date is flagged
  - Due date before invoice date is flagged
  - Negative total is flagged
  - Single penalty produces warning flag

Sources:
- pytest documentation:
  https://docs.pytest.org/en/stable/
"""

import pytest
from datetime import datetime, timedelta, timezone

from app.models import Invoice, LineItem, ValidationFlag, ProcessingStatus
from app.services.validator import validate_invoice


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_valid_invoice(**overrides) -> Invoice:
    base = dict(
        file_name="test.pdf",
        vendor="ACME Corp",
        invoice_date="06/15/2026",
        due_date="07/15/2026",
        subtotal=100.00,
        tax=13.00,
        total_amount=113.00,
        line_items=[
            LineItem(name="Widget A", quantity=2, unit_price=50.00, total=100.00)
        ],
    )
    base.update(overrides)
    return Invoice(**base)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_valid_invoice_passes():
    invoice = make_valid_invoice()
    result  = validate_invoice(invoice)
    assert result.validation.flag  == ValidationFlag.PASS
    assert result.validation.score == 1.0
    assert result.validation.issues == []


def test_missing_vendor_flagged():
    invoice = make_valid_invoice(vendor=None)
    result  = validate_invoice(invoice)
    assert any("vendor" in issue for issue in result.validation.issues)
    assert result.validation.flag != ValidationFlag.PASS


def test_missing_total_amount_flagged():
    invoice = make_valid_invoice(total_amount=None)
    result  = validate_invoice(invoice)
    assert any("total_amount" in issue for issue in result.validation.issues)


def test_missing_invoice_date_flagged():
    invoice = make_valid_invoice(invoice_date=None)
    result  = validate_invoice(invoice)
    assert any("invoice_date" in issue for issue in result.validation.issues)


def test_line_item_subtotal_mismatch():
    invoice = make_valid_invoice(
        line_items=[LineItem(name="Widget", quantity=1, unit_price=50.00, total=50.00)],
        subtotal=100.00,
    )
    result = validate_invoice(invoice)
    assert any("subtotal" in issue.lower() for issue in result.validation.issues)


def test_total_math_mismatch():
    invoice = make_valid_invoice(
        subtotal=100.00,
        tax=13.00,
        total_amount=200.00,
    )
    result = validate_invoice(invoice)
    assert any("total_amount" in issue.lower() for issue in result.validation.issues)


def test_negative_total_flagged():
    invoice = make_valid_invoice(total_amount=-50.00)
    result  = validate_invoice(invoice)
    assert any("positive" in issue.lower() for issue in result.validation.issues)


def test_future_invoice_date_flagged():
    future = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%m/%d/%Y")
    invoice = make_valid_invoice(invoice_date=future)
    result  = validate_invoice(invoice)
    assert any("future" in issue.lower() for issue in result.validation.issues)


def test_due_date_before_invoice_date_flagged():
    invoice = make_valid_invoice(
        invoice_date="06/15/2026",
        due_date="05/01/2026",
    )
    result = validate_invoice(invoice)
    assert any("due_date" in issue.lower() for issue in result.validation.issues)


def test_failed_invoice_has_low_score():
    invoice = make_valid_invoice(vendor=None, total_amount=None, invoice_date=None)
    result  = validate_invoice(invoice)
    assert result.validation.score < 0.6
    assert result.validation.flag == ValidationFlag.FAIL


def test_single_penalty_produces_warning():
    invoice = make_valid_invoice(due_date="05/01/2026")  # due before invoice date, -0.10
    result  = validate_invoice(invoice)
    assert 0.6 <= result.validation.score < 1.0
    assert result.validation.flag == ValidationFlag.WARNING
    assert result.status == ProcessingStatus.COMPLETED
