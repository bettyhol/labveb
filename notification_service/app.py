"""FastAPI application for Notification Service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, status

from . import models
from .database import initialize_database
from .schemas import NotificationCreate, NotificationResponse


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield


app = FastAPI(title="Notification Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    """Return the service health status."""
    return {
        "status": "ok",
        "service": "notification-service",
        "version": "1.0.0",
    }


@app.post(
    "/notifications",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_notification(payload: NotificationCreate) -> dict[str, object]:
    notification = models.create_notification(
        user_id=payload.user_id,
        booking_id=payload.booking_id,
        notification_type=payload.type.value,
        channel=payload.channel.value,
        recipient=str(payload.recipient),
        subject=payload.subject,
        message=payload.message,
    )
    models.simulate_email_delivery(notification)
    return notification


@app.get("/notifications", response_model=list[NotificationResponse])
def list_notifications() -> list[dict[str, object]]:
    return models.list_notifications()


@app.get(
    "/notifications/{notification_id}",
    response_model=NotificationResponse,
)
def get_notification(
    notification_id: Annotated[int, Path(gt=0)],
) -> dict[str, object]:
    notification = models.get_notification(notification_id)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    return notification


@app.get(
    "/users/{user_id}/notifications",
    response_model=list[NotificationResponse],
)
def list_user_notifications(
    user_id: Annotated[int, Path(gt=0)],
) -> list[dict[str, object]]:
    return models.list_user_notifications(user_id)


@app.post(
    "/notifications/{notification_id}/read",
    response_model=NotificationResponse,
)
def mark_notification_read(
    notification_id: Annotated[int, Path(gt=0)],
) -> dict[str, object]:
    notification = models.mark_notification_read(notification_id)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    return notification
