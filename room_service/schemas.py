"""Pydantic schemas for Room Service."""

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RoomType(str, Enum):
    STANDARD = "STANDARD"
    DELUXE = "DELUXE"
    SUITE = "SUITE"


def _trim_non_empty(value: object, field_name: str) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


class RoomCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hotel_id: int = Field(gt=0)
    number: str
    room_type: RoomType
    capacity: int = Field(ge=1)
    price_per_night: float = Field(gt=0)

    @field_validator("number", mode="before")
    @classmethod
    def validate_number(cls, value: object) -> object:
        return _trim_non_empty(value, "Number")

    @field_validator("room_type", mode="before")
    @classmethod
    def normalize_room_type(cls, value: object) -> object:
        value = _trim_non_empty(value, "Room type")
        return value.upper() if isinstance(value, str) else value


class RoomUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hotel_id: int | None = Field(default=None, gt=0)
    number: str | None = None
    room_type: RoomType | None = None
    capacity: int | None = Field(default=None, ge=1)
    price_per_night: float | None = Field(default=None, gt=0)

    @field_validator("hotel_id", "capacity", "price_per_night", mode="before")
    @classmethod
    def validate_numbers_not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Updated numeric fields must not be null")
        return value

    @field_validator("number", mode="before")
    @classmethod
    def validate_number(cls, value: object) -> object:
        if value is None:
            raise ValueError("Number must not be null")
        return _trim_non_empty(value, "Number")

    @field_validator("room_type", mode="before")
    @classmethod
    def normalize_room_type(cls, value: object) -> object:
        if value is None:
            raise ValueError("Room type must not be null")
        value = _trim_non_empty(value, "Room type")
        return value.upper() if isinstance(value, str) else value


class RoomResponse(BaseModel):
    id: int
    hotel_id: int
    number: str
    room_type: RoomType
    capacity: int
    price_per_night: float
    active: bool
    created_at: datetime


class AllocationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class AllocationHoldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    booking_id: int = Field(gt=0)
    room_id: int = Field(gt=0)
    check_in: date
    check_out: date


class AllocationResponse(BaseModel):
    id: int
    room_id: int
    booking_id: int
    check_in: date
    check_out: date
    status: AllocationStatus
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
