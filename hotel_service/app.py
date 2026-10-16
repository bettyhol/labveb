"""FastAPI application for Hotel Service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, status

from . import models
from .database import initialize_database
from .schemas import HotelCreate, HotelResponse, HotelUpdate


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield


app = FastAPI(
    title="Hotel Service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    """Return the service health status."""
    return {
        "status": "ok",
        "service": "hotel-service",
        "version": "1.0.0",
    }


@app.post("/hotels", response_model=HotelResponse, status_code=status.HTTP_201_CREATED)
def create_hotel(payload: HotelCreate) -> dict[str, object]:
    return models.create_hotel(
        name=payload.name,
        city=payload.city,
        address=payload.address,
        description=payload.description,
        rating=payload.rating,
    )


@app.get("/hotels", response_model=list[HotelResponse])
def list_hotels(
    city: str | None = None,
    min_rating: Annotated[int | None, Query(ge=1, le=5)] = None,
) -> list[dict[str, object]]:
    if city is not None:
        city = city.strip()
        if not city:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="City filter must not be empty",
            )
    return models.list_hotels(city=city, min_rating=min_rating)


@app.get("/hotels/{hotel_id}", response_model=HotelResponse)
def get_hotel(hotel_id: int) -> dict[str, object]:
    hotel = models.get_hotel(hotel_id)
    if hotel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hotel not found",
        )
    return hotel


@app.patch("/hotels/{hotel_id}", response_model=HotelResponse)
def update_hotel(hotel_id: int, payload: HotelUpdate) -> dict[str, object]:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update",
        )

    hotel = models.update_hotel(hotel_id, changes)
    if hotel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hotel not found",
        )
    return hotel


@app.delete("/hotels/{hotel_id}", response_model=HotelResponse)
def delete_hotel(hotel_id: int) -> dict[str, object]:
    hotel = models.soft_delete_hotel(hotel_id)
    if hotel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hotel not found",
        )
    return hotel
