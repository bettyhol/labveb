"""FastAPI application for Room Service."""

import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, NoReturn

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Response, status

from . import models
from .clients import (
    HotelLookup,
    HotelServiceUnavailableError,
    get_hotel_lookup,
)
from .database import initialize_database
from .schemas import (
    AllocationHoldRequest,
    AllocationResponse,
    RoomCreate,
    RoomResponse,
    RoomUpdate,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield


app = FastAPI(
    title="Room Service",
    version="1.0.0",
    lifespan=lifespan,
)


def validate_active_hotel(hotel_id: int, lookup: HotelLookup) -> None:
    try:
        hotel = lookup(hotel_id)
    except HotelServiceUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Hotel service is unavailable",
        ) from error

    if hotel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hotel not found",
        )
    if hotel.get("active") is not True:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hotel is inactive",
        )


def raise_allocation_http_error(error: Exception) -> NoReturn:
    if isinstance(error, models.RoomNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        ) from error
    if isinstance(error, models.RoomInactiveError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Room is inactive",
        ) from error
    if isinstance(error, models.AllocationNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Allocation not found",
        ) from error
    if isinstance(error, models.AllocationConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    if isinstance(error, models.DatabaseBusyError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Room database is busy",
        ) from error
    raise error


@app.get("/health")
def health() -> dict[str, str]:
    """Return the service health status."""
    return {
        "status": "ok",
        "service": "room-service",
        "version": "1.0.0",
    }


@app.post("/rooms", response_model=RoomResponse, status_code=status.HTTP_201_CREATED)
def create_room(
    payload: RoomCreate,
    hotel_lookup: Annotated[HotelLookup, Depends(get_hotel_lookup)],
) -> dict[str, object]:
    validate_active_hotel(payload.hotel_id, hotel_lookup)
    try:
        return models.create_room(
            hotel_id=payload.hotel_id,
            number=payload.number,
            room_type=payload.room_type.value,
            capacity=payload.capacity,
            price_per_night=payload.price_per_night,
        )
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Room number already exists in this hotel",
        ) from error


@app.get("/rooms", response_model=list[RoomResponse])
def list_rooms() -> list[dict[str, object]]:
    return models.list_rooms()


@app.get("/rooms/available", response_model=list[RoomResponse])
def list_available_rooms(
    hotel_id: Annotated[int, Query(gt=0)],
    check_in: date,
    check_out: date,
    guests: Annotated[int, Query(gt=0)],
    hotel_lookup: Annotated[HotelLookup, Depends(get_hotel_lookup)],
) -> list[dict[str, object]]:
    if check_in >= check_out:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="check_in must be before check_out",
        )
    validate_active_hotel(hotel_id, hotel_lookup)
    return models.list_available_rooms(
        hotel_id=hotel_id,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
    )


@app.get("/rooms/{room_id}", response_model=RoomResponse)
def get_room(room_id: int) -> dict[str, object]:
    room = models.get_room(room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )
    return room


@app.patch("/rooms/{room_id}", response_model=RoomResponse)
def update_room(
    room_id: int,
    payload: RoomUpdate,
    hotel_lookup: Annotated[HotelLookup, Depends(get_hotel_lookup)],
) -> dict[str, object]:
    current_room = models.get_room(room_id)
    if current_room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update",
        )
    if "room_type" in changes:
        changes["room_type"] = changes["room_type"].value
    if (
        "hotel_id" in changes
        and changes["hotel_id"] != current_room["hotel_id"]
    ):
        validate_active_hotel(int(changes["hotel_id"]), hotel_lookup)

    try:
        room = models.update_room(room_id, changes)
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Room number already exists in this hotel",
        ) from error
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )
    return room


@app.delete("/rooms/{room_id}", response_model=RoomResponse)
def delete_room(room_id: int) -> dict[str, object]:
    room = models.soft_delete_room(room_id)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Room not found",
        )
    return room


@app.get("/hotels/{hotel_id}/rooms", response_model=list[RoomResponse])
def list_hotel_rooms(hotel_id: int) -> list[dict[str, object]]:
    return models.list_hotel_rooms(hotel_id)


@app.post(
    "/allocations/hold",
    response_model=AllocationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": AllocationResponse}},
)
def hold_allocation(
    payload: AllocationHoldRequest,
    response: Response,
) -> dict[str, object]:
    if payload.check_in >= payload.check_out:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="check_in must be before check_out",
        )

    try:
        allocation, created = models.hold_allocation(
            booking_id=payload.booking_id,
            room_id=payload.room_id,
            check_in=payload.check_in,
            check_out=payload.check_out,
        )
    except Exception as error:
        raise_allocation_http_error(error)

    response.status_code = (
        status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )
    return allocation


@app.get("/allocations/{booking_id}", response_model=AllocationResponse)
def get_allocation(
    booking_id: Annotated[int, Path(gt=0)],
) -> dict[str, object]:
    allocation = models.get_allocation(booking_id)
    if allocation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Allocation not found",
        )
    return allocation


@app.post(
    "/allocations/{booking_id}/confirm",
    response_model=AllocationResponse,
)
def confirm_allocation(
    booking_id: Annotated[int, Path(gt=0)],
) -> dict[str, object]:
    try:
        return models.confirm_allocation(booking_id)
    except Exception as error:
        raise_allocation_http_error(error)


@app.post(
    "/allocations/{booking_id}/release",
    response_model=AllocationResponse,
)
def release_allocation(
    booking_id: Annotated[int, Path(gt=0)],
) -> dict[str, object]:
    try:
        return models.release_allocation(booking_id)
    except Exception as error:
        raise_allocation_http_error(error)
