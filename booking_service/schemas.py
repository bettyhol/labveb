"""Pydantic schemas for Booking Service."""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class BookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    CANCELLED = "CANCELLED"


class BookingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(gt=0)
    room_id: int = Field(gt=0)
    check_in: date
    check_out: date


class BookingResponse(BaseModel):
    id: int
    user_id: int
    hotel_id: int
    hotel_name: str
    room_id: int
    room_number: str
    room_type: str
    check_in: date
    check_out: date
    nights: int
    price_per_night: float
    total_amount: float
    status: BookingStatus
    payment_id: int | None
    created_at: datetime
    updated_at: datetime
