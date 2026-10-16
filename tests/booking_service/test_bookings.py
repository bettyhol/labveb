"""Booking API, calculation, and snapshot tests."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


def assert_utc(value: str) -> None:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def test_health(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "booking-service",
        "version": "1.0.0",
    }


def test_create_get_and_list_confirmed_booking(
    client: TestClient,
    booking_payload,
):
    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 201
    booking = response.json()
    assert booking["user_id"] == 1
    assert booking["room_id"] == 7
    assert booking["hotel_id"] == 3
    assert booking["hotel_name"] == "Kharkiv Palace"
    assert booking["room_number"] == "301"
    assert booking["room_type"] == "DELUXE"
    assert booking["price_per_night"] == 2500
    assert booking["nights"] == 3
    assert booking["total_amount"] == 7500
    assert booking["status"] == "CONFIRMED"
    assert booking["payment_id"] == 55
    assert_utc(booking["created_at"])
    assert_utc(booking["updated_at"])
    assert client.get(f"/bookings/{booking['id']}").json() == booking
    assert client.get("/bookings").json() == [booking]
    assert client.get("/users/1/bookings").json() == [booking]


def test_one_night_booking_calculation(
    client: TestClient,
    booking_payload,
):
    booking_payload["check_out"] = "2026-09-21"

    booking = client.post("/bookings", json=booking_payload).json()

    assert booking["nights"] == 1
    assert booking["total_amount"] == 2500


@pytest.mark.parametrize(
    ("check_in", "check_out"),
    [
        ("2026-09-20", "2026-09-20"),
        ("2026-09-23", "2026-09-20"),
    ],
)
def test_invalid_date_relation_is_rejected_before_downstream_calls(
    client: TestClient,
    booking_payload,
    downstream,
    check_in,
    check_out,
):
    booking_payload.update({"check_in": check_in, "check_out": check_out})

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 400
    assert response.json() == {"detail": "check_in must be before check_out"}
    assert downstream.calls == []
    assert client.get("/bookings").json() == []


def test_invalid_date_syntax_returns_validation_error(client, booking_payload):
    booking_payload["check_in"] = "20-09-2026"

    assert client.post("/bookings", json=booking_payload).status_code == 422


@pytest.mark.parametrize(
    "field",
    [
        "hotel_id",
        "hotel_name",
        "room_number",
        "room_type",
        "price_per_night",
        "nights",
        "total_amount",
        "status",
        "payment_id",
        "simulate_failure",
        "guests",
    ],
)
def test_server_owned_and_out_of_contract_fields_are_rejected(
    client: TestClient,
    booking_payload,
    field,
):
    booking_payload[field] = 1

    assert client.post("/bookings", json=booking_payload).status_code == 422


def test_unknown_booking_returns_not_found(client: TestClient):
    response = client.get("/bookings/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Booking not found"}


def test_user_without_bookings_returns_empty_list(client: TestClient):
    response = client.get("/users/999/bookings")

    assert response.status_code == 200
    assert response.json() == []


def test_booking_reads_preserved_local_snapshot(
    client: TestClient,
    booking_payload,
    downstream,
):
    created = client.post("/bookings", json=booking_payload).json()
    downstream.hotel["name"] = "Renamed Hotel"
    downstream.room.update(
        {"number": "999", "room_type": "STANDARD", "price_per_night": 1}
    )
    downstream.calls.clear()

    stored = client.get(f"/bookings/{created['id']}").json()

    assert stored["hotel_name"] == "Kharkiv Palace"
    assert stored["room_number"] == "301"
    assert stored["room_type"] == "DELUXE"
    assert stored["price_per_night"] == 2500
    assert downstream.calls == []


def test_list_ordering_is_deterministic(client, booking_payload, downstream):
    first = client.post("/bookings", json=booking_payload).json()
    downstream.room["id"] = 8
    booking_payload["room_id"] = 8
    second = client.post("/bookings", json=booking_payload).json()

    assert client.get("/bookings").json() == [first, second]
    assert client.get("/users/1/bookings").json() == [second, first]
