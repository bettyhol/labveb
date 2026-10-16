"""Pydantic schemas for Hotel Service."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def _trim_non_empty(value: object, field_name: str) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


class HotelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    city: str
    address: str
    description: str | None = None
    rating: int = Field(ge=1, le=5)

    @field_validator("name", "city", "address", mode="before")
    @classmethod
    def validate_required_text(cls, value: object, info: ValidationInfo) -> object:
        field_name = info.field_name.replace("_", " ").title()
        return _trim_non_empty(value, field_name)

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None


class HotelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    city: str | None = None
    address: str | None = None
    description: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)

    @field_validator("name", "city", "address", mode="before")
    @classmethod
    def validate_required_text(cls, value: object, info: ValidationInfo) -> object:
        field_name = info.field_name.replace("_", " ").title()
        if value is None:
            raise ValueError(f"{field_name} must not be null")
        return _trim_non_empty(value, field_name)

    @field_validator("rating", mode="before")
    @classmethod
    def validate_rating_not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Rating must not be null")
        return value

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        return normalized or None


class HotelResponse(BaseModel):
    id: int
    name: str
    city: str
    address: str
    description: str | None
    rating: int
    active: bool
    created_at: datetime
