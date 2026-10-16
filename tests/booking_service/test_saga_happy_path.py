"""Successful Saga sequence and controlled boundary-error tests."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from booking_service import clients, database, models


def test_successful_saga_order_state_and_payloads(
    client: TestClient,
    booking_payload,
    downstream,
):
    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 201
    booking = response.json()
    assert downstream.calls == [
        "user_get",
        "room_get",
        "hotel_get",
        "room_hold",
        "payment_create",
        "room_confirm",
        "notification_create",
    ]
    assert downstream.pending_at_hold["id"] == booking["id"]
    assert downstream.pending_at_hold["status"] == "PENDING"
    assert downstream.pending_at_hold["payment_id"] is None
    assert downstream.pending_at_confirm["status"] == "PENDING"
    assert downstream.confirmed_at_notification["status"] == "CONFIRMED"
    assert downstream.confirmed_at_notification["payment_id"] == 55
    assert downstream.payloads["hold"] == {
        "booking_id": booking["id"],
        "room_id": 7,
        "check_in": "2026-09-20",
        "check_out": "2026-09-23",
    }
    assert downstream.payloads["payment"] == {
        "booking_id": booking["id"],
        "user_id": 1,
        "amount": 7500.0,
        "currency": "UAH",
        "method": "CARD",
    }
    assert downstream.payloads["notification"] == {
        "user_id": 1,
        "booking_id": booking["id"],
        "type": "BOOKING_CONFIRMED",
        "channel": "EMAIL",
        "recipient": "maksym@example.com",
        "subject": "Booking confirmed",
        "message": f"Booking #{booking['id']} has been confirmed.",
    }


@pytest.mark.parametrize(
    ("resource", "value", "status_code", "detail", "expected_calls"),
    [
        ("user", None, 404, "User not found", ["user_get"]),
        (
            "user",
            {"id": 1, "email": "x@example.com", "active": False},
            400,
            "User is inactive",
            ["user_get"],
        ),
        ("room", None, 404, "Room not found", ["user_get", "room_get"]),
        (
            "room",
            {"id": 7, "active": False},
            400,
            "Room is inactive",
            ["user_get", "room_get"],
        ),
        (
            "hotel",
            None,
            404,
            "Hotel not found",
            ["user_get", "room_get", "hotel_get"],
        ),
        (
            "hotel",
            {"id": 3, "name": "Hotel", "active": False},
            400,
            "Hotel is inactive",
            ["user_get", "room_get", "hotel_get"],
        ),
    ],
)
def test_resource_validation_happens_before_booking_insert(
    client,
    booking_payload,
    downstream,
    resource,
    value,
    status_code,
    detail,
    expected_calls,
):
    setattr(downstream, resource, value)

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert downstream.calls == expected_calls
    assert models.list_bookings() == []


@pytest.mark.parametrize(
    ("operation", "service", "expected_calls"),
    [
        ("get_user", "User", ["user_get"]),
        ("get_room", "Room", ["user_get", "room_get"]),
        (
            "get_hotel",
            "Hotel",
            ["user_get", "room_get", "hotel_get"],
        ),
    ],
)
def test_pre_side_effect_unavailable_service_returns_controlled_503(
    client,
    booking_payload,
    downstream,
    operation,
    service,
    expected_calls,
):
    downstream.failures[operation] = clients.ServiceUnavailableError(service)

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 503
    assert response.json() == {"detail": f"{service} service is unavailable"}
    assert downstream.calls == expected_calls
    assert models.list_bookings() == []


def test_room_hold_conflict_cleans_up_pending_booking(
    client,
    booking_payload,
    downstream,
):
    downstream.failures["hold_room"] = clients.DownstreamHTTPError(
        409,
        "Room is not available for the requested dates",
    )

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 409
    assert response.json()["detail"] == "Room is not available for the requested dates"
    assert models.list_bookings() == []
    assert downstream.calls[-1] == "room_hold"


def test_payment_unavailable_retries_and_compensates(
    client,
    booking_payload,
    downstream,
):
    downstream.failures["create_payment"] = clients.ServiceUnavailableError(
        "Payment"
    )

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 503
    assert response.json() == {"detail": "Payment service is unavailable"}
    assert "room_confirm" not in downstream.calls
    assert downstream.calls.count("payment_create") == 2
    assert downstream.payment_payloads[0] == downstream.payment_payloads[1]
    assert "room_release" in downstream.calls
    assert models.list_bookings()[0]["status"] == "PAYMENT_FAILED"


def test_non_paid_result_releases_room_and_marks_payment_failed(
    client,
    booking_payload,
    downstream,
):
    downstream.payment_status = "FAILED"

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 201
    assert response.json()["status"] == "PAYMENT_FAILED"
    assert response.json()["payment_id"] == 55
    assert "room_confirm" not in downstream.calls
    assert "room_release" in downstream.calls
    assert downstream.payloads["notification"]["type"] == "PAYMENT_FAILED"
    assert models.list_bookings()[0]["status"] == "PAYMENT_FAILED"


def test_notification_unavailable_does_not_rollback_confirmed_core_state(
    client,
    booking_payload,
    downstream,
):
    downstream.failures["create_notification"] = clients.ServiceUnavailableError(
        "Notification"
    )

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 201
    assert response.json()["status"] == "CONFIRMED"
    stored = models.list_bookings()[0]
    assert stored["status"] == "CONFIRMED"
    assert stored["payment_id"] == 55


def test_local_database_error_is_controlled(
    client,
    monkeypatch,
):
    def fail():
        raise sqlite3.OperationalError("private database detail")

    monkeypatch.setattr(models, "list_bookings", fail)

    response = client.get("/bookings")

    assert response.status_code == 500
    assert response.json() == {"detail": "Booking database error"}


def test_bookings_database_contains_only_owned_table(client):
    with database.get_connection() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            )
        }
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(bookings)"
        ).fetchall()

    assert tables == {"bookings"}
    assert foreign_keys == []
