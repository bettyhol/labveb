"""HTTP client for Room Service dependencies."""

import os
from collections.abc import Callable

import httpx


HOTEL_SERVICE_URL = os.getenv(
    "HOTEL_SERVICE_URL",
    "http://hotel-service:8000",
)
HTTP_TIMEOUT_SECONDS = 5.0


class HotelServiceUnavailableError(Exception):
    """Raised when Hotel Service cannot provide a reliable response."""


def get_hotel(
    hotel_id: int,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object] | None:
    """Return a Hotel, None for 404, or raise for downstream failures."""
    url = f"{HOTEL_SERVICE_URL.rstrip('/')}/hotels/{hotel_id}"
    try:
        with httpx.Client(
            timeout=HTTP_TIMEOUT_SECONDS,
            transport=transport,
        ) as client:
            response = client.get(url)
    except (httpx.TimeoutException, httpx.RequestError) as error:
        raise HotelServiceUnavailableError from error

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise HotelServiceUnavailableError

    try:
        payload = response.json()
    except ValueError as error:
        raise HotelServiceUnavailableError from error
    if not isinstance(payload, dict):
        raise HotelServiceUnavailableError
    return payload


HotelLookup = Callable[[int], dict[str, object] | None]


def get_hotel_lookup() -> HotelLookup:
    """FastAPI dependency seam for the Hotel Service lookup."""
    return get_hotel
