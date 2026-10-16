"""HTTPX integrations used by the Booking Saga orchestrator."""

import os
from collections.abc import Collection

import httpx


USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8000")
HOTEL_SERVICE_URL = os.getenv("HOTEL_SERVICE_URL", "http://hotel-service:8000")
ROOM_SERVICE_URL = os.getenv("ROOM_SERVICE_URL", "http://room-service:8000")
PAYMENT_SERVICE_URL = os.getenv(
    "PAYMENT_SERVICE_URL",
    "http://payment-service:8000",
)
NOTIFICATION_SERVICE_URL = os.getenv(
    "NOTIFICATION_SERVICE_URL",
    "http://notification-service:8000",
)
HTTP_TIMEOUT_SECONDS = 5.0


class ServiceUnavailableError(Exception):
    """Raised when a downstream service cannot provide a reliable response."""

    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        super().__init__(f"{service_name} service is unavailable")


class DownstreamHTTPError(Exception):
    """Represent an expected 4xx response from a downstream service."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class BookingServiceClients:
    """Small, injectable client boundary for the five Booking dependencies."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def _request(
        self,
        method: str,
        url: str,
        *,
        service_name: str,
        expected_statuses: Collection[int],
        payload: dict[str, object] | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, object] | None:
        try:
            with httpx.Client(
                timeout=HTTP_TIMEOUT_SECONDS,
                transport=self._transport,
            ) as client:
                response = client.request(method, url, json=payload)
        except (httpx.TimeoutException, httpx.RequestError) as error:
            raise ServiceUnavailableError(service_name) from error

        if allow_not_found and response.status_code == 404:
            return None
        if response.status_code not in expected_statuses:
            if 400 <= response.status_code < 500:
                try:
                    detail = response.json().get("detail")
                except (AttributeError, ValueError):
                    detail = None
                raise DownstreamHTTPError(
                    response.status_code,
                    detail or f"{service_name} request failed",
                )
            raise ServiceUnavailableError(service_name)

        try:
            result = response.json()
        except ValueError as error:
            raise ServiceUnavailableError(service_name) from error
        if not isinstance(result, dict):
            raise ServiceUnavailableError(service_name)
        return result

    @staticmethod
    def _require_fields(
        payload: dict[str, object],
        fields: Collection[str],
        service_name: str,
    ) -> dict[str, object]:
        if any(field not in payload for field in fields):
            raise ServiceUnavailableError(service_name)
        return payload

    def get_user(self, user_id: int) -> dict[str, object] | None:
        result = self._request(
            "GET",
            f"{USER_SERVICE_URL.rstrip('/')}/users/{user_id}",
            service_name="User",
            expected_statuses={200},
            allow_not_found=True,
        )
        if result is None:
            return None
        return self._require_fields(result, {"id", "email", "active"}, "User")

    def get_room(self, room_id: int) -> dict[str, object] | None:
        result = self._request(
            "GET",
            f"{ROOM_SERVICE_URL.rstrip('/')}/rooms/{room_id}",
            service_name="Room",
            expected_statuses={200},
            allow_not_found=True,
        )
        if result is None:
            return None
        return self._require_fields(
            result,
            {
                "id",
                "hotel_id",
                "number",
                "room_type",
                "price_per_night",
                "active",
            },
            "Room",
        )

    def get_hotel(self, hotel_id: int) -> dict[str, object] | None:
        result = self._request(
            "GET",
            f"{HOTEL_SERVICE_URL.rstrip('/')}/hotels/{hotel_id}",
            service_name="Hotel",
            expected_statuses={200},
            allow_not_found=True,
        )
        if result is None:
            return None
        return self._require_fields(result, {"id", "name", "active"}, "Hotel")

    def hold_room(self, payload: dict[str, object]) -> dict[str, object]:
        result = self._request(
            "POST",
            f"{ROOM_SERVICE_URL.rstrip('/')}/allocations/hold",
            service_name="Room",
            expected_statuses={200, 201},
            payload=payload,
        )
        return self._require_fields(result, {"booking_id", "status"}, "Room")

    def create_payment(self, payload: dict[str, object]) -> dict[str, object]:
        result = self._request(
            "POST",
            f"{PAYMENT_SERVICE_URL.rstrip('/')}/payments",
            service_name="Payment",
            expected_statuses={200, 201},
            payload=payload,
        )
        return self._require_fields(result, {"id", "booking_id", "status"}, "Payment")

    def confirm_room_allocation(self, booking_id: int) -> dict[str, object]:
        result = self._request(
            "POST",
            f"{ROOM_SERVICE_URL.rstrip('/')}/allocations/{booking_id}/confirm",
            service_name="Room",
            expected_statuses={200},
        )
        return self._require_fields(result, {"booking_id", "status"}, "Room")

    def release_room_allocation(self, booking_id: int) -> dict[str, object]:
        result = self._request(
            "POST",
            f"{ROOM_SERVICE_URL.rstrip('/')}/allocations/{booking_id}/release",
            service_name="Room",
            expected_statuses={200},
        )
        return self._require_fields(result, {"booking_id", "status"}, "Room")

    def refund_payment(self, payment_id: int) -> dict[str, object]:
        result = self._request(
            "POST",
            f"{PAYMENT_SERVICE_URL.rstrip('/')}/payments/{payment_id}/refund",
            service_name="Payment",
            expected_statuses={200},
        )
        return self._require_fields(result, {"id", "status"}, "Payment")

    def create_notification(self, payload: dict[str, object]) -> dict[str, object]:
        result = self._request(
            "POST",
            f"{NOTIFICATION_SERVICE_URL.rstrip('/')}/notifications",
            service_name="Notification",
            expected_statuses={201},
            payload=payload,
        )
        return self._require_fields(result, {"booking_id", "status"}, "Notification")


def get_booking_clients() -> BookingServiceClients:
    """Provide the production HTTP client through a FastAPI dependency seam."""
    return BookingServiceClients()
