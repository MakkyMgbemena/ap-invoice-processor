# Validator Service

**File:** `app/services/validator.py`  
**Purpose:** Validates extracted invoice data for completeness and mathematical correctness.

---

## Validation Checks

| # | Check | Score Penalty |
|---|---|---|
| 1 | Required fields present (vendor, invoice_date, total_amount) | -0.20 per missing field |
| 2 | total_amount is a positive number | -0.20 |
| 3 | Line item sum matches declared subtotal (±$0.02) | -0.15 |
| 4 | subtotal + tax ≈ total_amount (±$0.02) | -0.15 |
| 5 | invoice_date is parseable and not in the future | -0.10 |
| 6 | due_date is after invoice_date | -0.10 |

> **Check 3:** If `line_items` is empty, this check is skipped — no penalty applied.  
> **Check 4:** If `tax` is `None`, this check is skipped — no penalty applied.

---

## Scoring & Flags

| Score | Flag |
|---|---|
| 1.0 | `pass` |
| 0.6 – 0.99 | `warning` |
| < 0.6 | `fail` |

A `fail` result sets `invoice.status = failed`. A `warning` still sets `completed`.  
Score is floored at 0.0 — penalties cannot produce a negative result.

---

## References

- [Python datetime stdlib](https://docs.python.org/3/library/datetime.html)
- [python-dateutil](https://dateutil.readthedocs.io/)
- [Pydantic v2 validators](https://docs.pydantic.dev/latest/concepts/validators/)
