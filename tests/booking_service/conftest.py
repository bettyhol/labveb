"""Isolated database and downstream fixtures for Booking Service tests."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from booking_service import clients, database, models
from booking_service.app import app


class FakeBookingClients:
    def __init__(self) -> None:
        self.user = {
            "id": 1,
            "name": "Maksym",
            "email": "maksym@example.com",
            "active": True,
        }
        self.room = {
            "id": 7,
            "hotel_id": 3,
            "number": "301",
            "room_type": "DELUXE",
            "capacity": 2,
            "price_per_night": 2500,
            "active": True,
        }
        self.hotel = {
            "id": 3,
            "name": "Kharkiv Palace",
            "active": True,
        }
        self.payment_id = 55
        self.payment_status = "PAID"
        self.refund_status = "REFUNDED"
        self.refunded_at = "2026-09-13T12:00:00Z"
        self.notification_status = "SENT"
        self.failures: dict[str, Exception] = {}
        self.failure_sequences: dict[str, list[Exception | None]] = {}
        self.calls: list[str] = []
        self.payloads: dict[str, dict[str, object]] = {}
        self.payment_payloads: list[dict[str, object]] = []
        self.notification_payloads: list[dict[str, object]] = []
        self.refunded_payment_ids: list[int] = []
        self.pending_at_hold: dict[str, object] | None = None
        self.pending_at_confirm: dict[str, object] | None = None
        self.confirmed_at_notification: dict[str, object] | None = None

    def _raise_failure(self, operation: str) -> None:
        sequence = self.failure_sequences.get(operation)
        if sequence:
            error = sequence.pop(0)
            if error is not None:
                raise error
        error = self.failures.get(operation)
        if error is not None:
            raise error

    def get_user(self, user_id: int):
        self.calls.append("user_get")
        self._raise_failure("get_user")
        return deepcopy(self.user) if self.user is not None else None

    def get_room(self, room_id: int):
        self.calls.append("room_get")
        self._raise_failure("get_room")
        return deepcopy(self.room) if self.room is not None else None

    def get_hotel(self, hotel_id: int):
        self.calls.append("hotel_get")
        self._raise_failure("get_hotel")
        return deepcopy(self.hotel) if self.hotel is not None else None

    def hold_room(self, payload: dict[str, object]):
        self.calls.append("room_hold")
        self._raise_failure("hold_room")
        self.payloads["hold"] = deepcopy(payload)
        self.pending_at_hold = models.get_booking(int(payload["booking_id"]))
        return {
            "booking_id": payload["booking_id"],
            "status": "HELD",
        }

    def create_payment(self, payload: dict[str, object]):
        self.calls.append("payment_create")
        self.payloads["payment"] = deepcopy(payload)
        self.payment_payloads.append(deepcopy(payload))
        self._raise_failure("create_payment")
        return {
            "id": self.payment_id,
            "booking_id": payload["booking_id"],
            "status": self.payment_status,
        }

    def confirm_room_allocation(self, booking_id: int):
        self.calls.append("room_confirm")
        self._raise_failure("confirm_room_allocation")
        self.pending_at_confirm = models.get_booking(booking_id)
        return {"booking_id": booking_id, "status": "CONFIRMED"}

    def release_room_allocation(self, booking_id: int):
        self.calls.append("room_release")
        self._raise_failure("release_room_allocation")
        return {"booking_id": booking_id, "status": "RELEASED"}

    def refund_payment(self, payment_id: int):
        self.calls.append("payment_refund")
        self.refunded_payment_ids.append(payment_id)
        self._raise_failure("refund_payment")
        return {
            "id": payment_id,
            "status": self.refund_status,
            "refunded_at": self.refunded_at,
        }

    def create_notification(self, payload: dict[str, object]):
        self.calls.append("notification_create")
        self.payloads["notification"] = deepcopy(payload)
        self.notification_payloads.append(deepcopy(payload))
        self._raise_failure("create_notification")
        self.confirmed_at_notification = models.get_booking(
            int(payload["booking_id"])
        )
        return {
            "booking_id": payload["booking_id"],
            "status": self.notification_status,
        }


@pytest.fixture
def downstream() -> FakeBookingClients:
    return FakeBookingClients()


@pytest.fixture
def client(tmp_path, monkeypatch, downstream):
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "bookings.db"))
    app.dependency_overrides[clients.get_booking_clients] = lambda: downstream
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def booking_payload():
    return {
        "user_id": 1,
        "room_id": 7,
        "check_in": "2026-09-20",
        "check_out": "2026-09-23",
    }
