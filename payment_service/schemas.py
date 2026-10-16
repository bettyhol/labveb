"""Pydantic schemas for Payment Service."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def _normalize_required_text(value: object, field_name: str) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized.upper()


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    amount: float = Field(gt=0)
    currency: str
    method: str
    simulate_failure: bool = False

    @field_validator("currency", "method", mode="before")
    @classmethod
    def normalize_text(cls, value: object, info: ValidationInfo) -> object:
        return _normalize_required_text(value, info.field_name.title())


class PaymentResponse(BaseModel):
    id: int
    booking_id: int
    user_id: int
    amount: float
    currency: str
    method: str
    status: PaymentStatus
    transaction_ref: str | None
    created_at: datetime
    refunded_at: datetime | None
