"""FastAPI application for Booking Service."""

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Path, status

from . import clients, models, orchestrator
from .database import initialize_database
from .schemas import BookingCreate, BookingResponse

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield


app = FastAPI(title="Booking Service", version="1.0.0", lifespan=lifespan)


def booking_database_error(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Booking database error",
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Return the service health status."""
    return {
        "status": "ok",
        "service": "booking-service",
        "version": "1.0.0",
    }


@app.post(
    "/bookings",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_booking(
    payload: BookingCreate,
    service_clients: Annotated[
        clients.BookingServiceClients,
        Depends(clients.get_booking_clients),
    ],
) -> dict[str, object]:
    try:
        return orchestrator.create_booking(payload, service_clients)
    except orchestrator.BookingSagaError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@app.get("/bookings", response_model=list[BookingResponse])
def list_bookings() -> list[dict[str, object]]:
    try:
        return models.list_bookings()
    except sqlite3.Error as error:
        raise booking_database_error(error) from error


@app.get("/bookings/{booking_id}", response_model=BookingResponse)
def get_booking(
    booking_id: Annotated[int, Path(gt=0)],
) -> dict[str, object]:
    try:
        booking = models.get_booking(booking_id)
    except sqlite3.Error as error:
        raise booking_database_error(error) from error
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )
    return booking


@app.post(
    "/bookings/{booking_id}/cancel",
    response_model=BookingResponse,
)
def cancel_booking(
    booking_id: Annotated[int, Path(gt=0)],
    service_clients: Annotated[
        clients.BookingServiceClients,
        Depends(clients.get_booking_clients),
    ],
) -> dict[str, object]:
    try:
        return orchestrator.cancel_booking(booking_id, service_clients)
    except orchestrator.BookingSagaError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@app.get(
    "/users/{user_id}/bookings",
    response_model=list[BookingResponse],
)
def list_user_bookings(
    user_id: Annotated[int, Path(gt=0)],
) -> list[dict[str, object]]:
    try:
        return models.list_user_bookings(user_id)
    except sqlite3.Error as error:
        raise booking_database_error(error) from error
