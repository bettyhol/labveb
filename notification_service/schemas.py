"""Pydantic schemas for Notification Service."""

from datetime import datetime
from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationInfo,
    field_validator,
)


def _trim_non_empty(value: object, field_name: str) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


class NotificationType(str, Enum):
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED"
    BOOKING_CANCELLED = "BOOKING_CANCELLED"
    PAYMENT_FAILED = "PAYMENT_FAILED"


class NotificationChannel(str, Enum):
    EMAIL = "EMAIL"


class NotificationStatus(str, Enum):
    SENT = "SENT"


class NotificationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(gt=0)
    booking_id: int | None = Field(default=None, gt=0)
    type: NotificationType
    channel: NotificationChannel
    recipient: EmailStr
    subject: str
    message: str

    @field_validator("type", "channel", mode="before")
    @classmethod
    def normalize_enum_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip().upper()

    @field_validator("recipient", mode="before")
    @classmethod
    def normalize_recipient(cls, value: object) -> object:
        value = _trim_non_empty(value, "Recipient")
        return value.lower() if isinstance(value, str) else value

    @field_validator("subject", "message", mode="before")
    @classmethod
    def validate_text(cls, value: object, info: ValidationInfo) -> object:
        return _trim_non_empty(value, info.field_name.title())


class NotificationResponse(BaseModel):
    id: int
    user_id: int
    booking_id: int | None
    type: NotificationType
    channel: NotificationChannel
    recipient: EmailStr
    subject: str
    message: str
    status: NotificationStatus
    is_read: bool
    created_at: datetime
