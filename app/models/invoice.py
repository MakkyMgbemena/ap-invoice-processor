from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ── Enums ─────────────────────────────────────────────────────

class ProcessingStatus(str, Enum):
    INGESTED   = "ingested"
    OCR_START  = "ocr_start"
    OCR_DONE   = "ocr_done"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    COMPLETED  = "completed"
    FAILED     = "failed"


class ValidationFlag(str, Enum):
    PASS    = "pass"
    WARNING = "warning"
    FAIL    = "fail"


# ── Sub-models ────────────────────────────────────────────────

class LineItem(BaseModel):
    name:       str
    quantity:   Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    total:      Decimal

    @field_validator("total", "unit_price", "quantity", mode="before")
    @classmethod
    def round_currency(cls, v):
        return Decimal(str(v)).quantize(Decimal("0.01")) if v is not None else v


class ValidationResult(BaseModel):
    flag:       ValidationFlag = ValidationFlag.PASS
    score:      float          = Field(default=1.0, ge=0.0, le=1.0)
    issues:     list[str]      = Field(default_factory=list)
    checked_at: datetime       = Field(default_factory=lambda: datetime.now(timezone.utc))


class OCRMeta(BaseModel):
    engine:     str             = "google_document_ai"
    confidence: Optional[float] = None
    page_count: Optional[int]   = None


class ErrorMeta(BaseModel):
    stage:   Optional[str] = None
    message: Optional[str] = None


class Timestamps(BaseModel):
    uploaded:  datetime           = Field(default_factory=lambda: datetime.now(timezone.utc))
    ocr_start: Optional[datetime] = None
    ocr_end:   Optional[datetime] = None
    extracted: Optional[datetime] = None
    completed: Optional[datetime] = None


# ── Core Invoice Model ────────────────────────────────────────

class Invoice(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    document_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_name:   str
    file_path:   Optional[str]       = None
    status:      ProcessingStatus    = ProcessingStatus.INGESTED
    timestamps:  Timestamps          = Field(default_factory=Timestamps)
    ocr:         OCRMeta             = Field(default_factory=OCRMeta)
    error:       ErrorMeta           = Field(default_factory=ErrorMeta)

    # ── GCS ──────────────────────────────────────────────────
    gcs_input_uri:  Optional[str] = None
    gcs_output_uri: Optional[str] = None

    # ── Extracted fields ──────────────────────────────────────
    recognized_text: Optional[str]         = None
    vendor:          Optional[str]         = None
    invoice_number:  Optional[str]         = None
    invoice_date:    Optional[str]         = None
    due_date:        Optional[str]         = None
    subtotal:        Optional[Decimal]     = None
    tax:             Optional[Decimal]     = None
    total_amount:    Optional[Decimal]     = None
    currency:        Optional[str]         = "USD"
    line_items:      list[LineItem]        = Field(default_factory=list)

    # ── Validation ────────────────────────────────────────────
    validation: Optional[ValidationResult] = None

    @model_validator(mode="after")
    def line_items_match_total(self) -> "Invoice":
        if not self.line_items or self.total_amount is None:
            return self
        calculated = sum(
            Decimal(str(i.total)) for i in self.line_items
        ).quantize(Decimal("0.01"))
        declared = Decimal(str(self.total_amount)).quantize(Decimal("0.01"))
        if calculated != declared:
            self.validation = ValidationResult(
                flag=ValidationFlag.FAIL,
                score=0.0,
                issues=[
                    f"Line items sum to {calculated}, "
                    f"but total_amount is {declared}. "
                    f"Delta: {abs(declared - calculated)}"
                ],
            )
        return self


# ── API Request / Response shapes ─────────────────────────────

class InvoiceUploadResponse(BaseModel):
    document_id: str
    file_name:   str
    status:      str
    message:     str


class InvoiceStatusResponse(BaseModel):
    document_id: str
    status:      str
    timestamps:  Timestamps
    error:       ErrorMeta


class InvoiceResultResponse(BaseModel):
    document_id:    str
    vendor:         Optional[str]     = None
    invoice_number: Optional[str]     = None
    invoice_date:   Optional[str]     = None
    due_date:       Optional[str]     = None
    subtotal:       Optional[Decimal] = None
    tax:            Optional[Decimal] = None
    total_amount:   Optional[Decimal] = None
    currency:       Optional[str]     = None
    line_items:     list[LineItem]    = Field(default_factory=list)
    validation:     Optional[ValidationResult] = None
    status:         str
