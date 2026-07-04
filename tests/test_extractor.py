"""
tests.test_extractor
--------------------
Unit tests for app.services.llm_extractor.

Tests:
  - Regex extraction on clean, structured OCR text
  - Regex handles missing optional fields gracefully
  - LineItem parsing from regex
  - parse_with_llm merges correctly without overwriting regex results

Sources:
- pytest documentation:
  https://docs.pytest.org/en/stable/
- Python unittest.mock:
  https://docs.python.org/3/library/unittest.mock.html
"""

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.services.llm_extractor import parse_with_regex, parse_with_llm, extract_invoice_fields
from app.models import Invoice, ProcessingStatus


# ── Fixtures ──────────────────────────────────────────────────────────────────

CLEAN_INVOICE_TEXT = """
ACME Supplies Inc.
Invoice Date: 06/15/2026
Due Date: 07/15/2026
Invoice #INV-00421

Bill To: Makky Corp

Widget A          2    $10.00    $20.00
Widget B          1    $50.00    $50.00

Subtotal: $70.00
Tax: $9.10
Total: $79.10
"""

MINIMAL_INVOICE_TEXT = """
Total Due: $125.00
"""


# ── parse_with_regex tests ────────────────────────────────────────────────────

def test_regex_extracts_total():
    result = parse_with_regex(CLEAN_INVOICE_TEXT)
    assert result["total_amount"] == Decimal("79.10")


def test_regex_extracts_subtotal():
    result = parse_with_regex(CLEAN_INVOICE_TEXT)
    assert result["subtotal"] == Decimal("70.00")


def test_regex_extracts_tax():
    result = parse_with_regex(CLEAN_INVOICE_TEXT)
    assert result["tax"] == Decimal("9.10")


def test_regex_extracts_invoice_date():
    result = parse_with_regex(CLEAN_INVOICE_TEXT)
    assert result["invoice_date"] == "06/15/2026"


def test_regex_extracts_due_date():
    result = parse_with_regex(CLEAN_INVOICE_TEXT)
    assert result["due_date"] == "07/15/2026"


def test_regex_extracts_invoice_number():
    result = parse_with_regex(CLEAN_INVOICE_TEXT)
    assert result["invoice_number"] == "INV-00421"


def test_regex_extracts_line_items():
    result = parse_with_regex(CLEAN_INVOICE_TEXT)
    assert len(result["line_items"]) == 2
    assert result["line_items"][0].name == "Widget A"
    assert result["line_items"][0].total == 20.00
    assert result["line_items"][1].name == "Widget B"
    assert result["line_items"][1].total == 50.00


def test_regex_handles_missing_fields_gracefully():
    result = parse_with_regex(MINIMAL_INVOICE_TEXT)
    assert result["total_amount"] == Decimal("125.00")
    assert result["vendor"] is None
    assert result["line_items"] == []


# ── parse_with_llm tests ──────────────────────────────────────────────────────

def test_llm_skipped_when_regex_complete():
    """LLM should not be called when all fields are already populated by regex."""
    full_partial = {
        "vendor":         "ACME Supplies Inc.",
        "invoice_number": "INV-00421",
        "invoice_date":   "06/15/2026",
        "due_date":       "07/15/2026",
        "subtotal":       70.00,
        "tax":            9.10,
        "total_amount":   79.10,
        "line_items":     [MagicMock()],
    }
    with patch("app.services.llm_extractor._openai_client") as mock_client:
        result = parse_with_llm(CLEAN_INVOICE_TEXT, full_partial)
        mock_client.assert_not_called()
        assert result["vendor"] == "ACME Supplies Inc."


def test_llm_fills_missing_fields():
    """LLM response should fill in fields that regex missed."""
    partial = {
        "vendor":         None,
        "invoice_number": None,
        "invoice_date":   None,
        "due_date":       None,
        "subtotal":       None,
        "tax":            None,
        "total_amount":   125.00,
        "line_items":     [],
    }
    llm_response = {
        "vendor":         "Test Corp",
        "invoice_number": "INV-999",
        "invoice_date":   "07/01/2026",
        "due_date":       "07/31/2026",
        "subtotal":       115.00,
        "tax":            10.00,
        "total_amount":   125.00,
        "currency":       "USD",
        "line_items":     [],
    }

    with patch("app.services.llm_extractor._openai_client") as mock_client:
        client_instance = MagicMock()
        response_mock = MagicMock()
        response_mock.choices = [MagicMock(message=MagicMock(content=json.dumps(llm_response)))]
        client_instance.chat.completions.create.return_value = response_mock
        mock_client.return_value = client_instance

        result = parse_with_llm(MINIMAL_INVOICE_TEXT, partial)
        assert result["vendor"] == "Test Corp"
        assert result["invoice_number"] == "INV-999"


# ── extract_invoice_fields integration test ───────────────────────────────────

def test_extract_invoice_fields_updates_invoice():
    invoice = Invoice(file_name="test.pdf", recognized_text=CLEAN_INVOICE_TEXT)

    with patch("app.services.llm_extractor._openai_client"):
        result = extract_invoice_fields(invoice)

    assert result.total_amount == Decimal("79.10")
    assert result.status == ProcessingStatus.EXTRACTING
    assert result.timestamps.extracted is not None
