"""FastAPI application for Payment Service."""

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Response, status

from . import models
from .database import initialize_database
from .schemas import PaymentCreate, PaymentResponse


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield


app = FastAPI(title="Payment Service", version="1.0.0", lifespan=lifespan)


def database_error(error: sqlite3.Error) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Payment database error",
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Return the service health status."""
    return {
        "status": "ok",
        "service": "payment-service",
        "version": "1.0.0",
    }


@app.post(
    "/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": PaymentResponse}},
)
def create_payment(
    payload: PaymentCreate,
    response: Response,
) -> dict[str, object]:
    try:
        payment, created = models.create_payment(
            booking_id=payload.booking_id,
            user_id=payload.user_id,
            amount=payload.amount,
            currency=payload.currency,
            method=payload.method,
            simulate_failure=payload.simulate_failure,
        )
    except models.PaymentConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except sqlite3.Error as error:
        raise database_error(error) from error

    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    return payment


@app.get("/payments/{payment_id}", response_model=PaymentResponse)
def get_payment(
    payment_id: Annotated[int, Path(gt=0)],
) -> dict[str, object]:
    try:
        payment = models.get_payment(payment_id)
    except sqlite3.Error as error:
        raise database_error(error) from error
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    return payment


@app.get("/bookings/{booking_id}/payment", response_model=PaymentResponse)
def get_payment_by_booking(
    booking_id: Annotated[int, Path(gt=0)],
) -> dict[str, object]:
    try:
        payment = models.get_payment_by_booking(booking_id)
    except sqlite3.Error as error:
        raise database_error(error) from error
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    return payment


@app.post("/payments/{payment_id}/refund", response_model=PaymentResponse)
def refund_payment(
    payment_id: Annotated[int, Path(gt=0)],
) -> dict[str, object]:
    try:
        return models.refund_payment(payment_id)
    except models.PaymentNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        ) from error
    except models.PaymentConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except sqlite3.Error as error:
        raise database_error(error) from error
