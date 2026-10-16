"""Deterministic failure-path tests for the Booking creation Saga."""

import sqlite3

from booking_service import clients, models


def test_ambiguous_hold_failure_releases_and_cleans_pending(
    client,
    booking_payload,
    downstream,
):
    downstream.failures["hold_room"] = clients.ServiceUnavailableError("Room")

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 503
    assert downstream.calls[-2:] == ["room_hold", "room_release"]
    assert "payment_create" not in downstream.calls
    assert models.list_bookings() == []


def test_ambiguous_hold_with_failed_release_keeps_pending_marker(
    client,
    booking_payload,
    downstream,
):
    downstream.failures["hold_room"] = clients.ServiceUnavailableError("Room")
    downstream.failures["release_room_allocation"] = (
        clients.ServiceUnavailableError("Room")
    )

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 503
    assert downstream.calls[-2:] == ["room_hold", "room_release"]
    assert models.list_bookings()[0]["status"] == "PENDING"


def test_business_payment_failure_is_terminal_and_not_retried(
    client,
    booking_payload,
    downstream,
):
    downstream.payment_status = "FAILED"

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 201
    assert response.json()["status"] == "PAYMENT_FAILED"
    assert response.json()["payment_id"] == downstream.payment_id
    assert downstream.calls.count("payment_create") == 1
    assert downstream.calls[-2:] == ["room_release", "notification_create"]
    assert downstream.payloads["notification"]["type"] == "PAYMENT_FAILED"


def test_payment_failure_notification_is_best_effort(
    client,
    booking_payload,
    downstream,
):
    downstream.payment_status = "FAILED"
    downstream.failures["create_notification"] = (
        clients.ServiceUnavailableError("Notification")
    )

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 201
    assert response.json()["status"] == "PAYMENT_FAILED"


def test_payment_transport_retry_uses_identical_payload_and_can_recover(
    client,
    booking_payload,
    downstream,
):
    downstream.failure_sequences["create_payment"] = [
        clients.ServiceUnavailableError("Payment"),
        None,
    ]

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 201
    assert response.json()["status"] == "CONFIRMED"
    assert downstream.calls.count("payment_create") == 2
    assert downstream.payment_payloads[0] == downstream.payment_payloads[1]
    assert "room_release" not in downstream.calls
    assert "payment_refund" not in downstream.calls


def test_exhausted_payment_retry_releases_and_marks_failed(
    client,
    booking_payload,
    downstream,
):
    downstream.failures["create_payment"] = clients.ServiceUnavailableError(
        "Payment"
    )

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 503
    assert downstream.calls.count("payment_create") == 2
    assert downstream.payment_payloads[0] == downstream.payment_payloads[1]
    assert downstream.calls[-2:] == ["room_release", "notification_create"]
    stored = models.list_bookings()[0]
    assert stored["status"] == "PAYMENT_FAILED"
    assert stored["payment_id"] is None


def test_exhausted_payment_retry_with_failed_release_keeps_pending(
    client,
    booking_payload,
    downstream,
):
    downstream.failures["create_payment"] = clients.ServiceUnavailableError(
        "Payment"
    )
    downstream.failures["release_room_allocation"] = (
        clients.ServiceUnavailableError("Room")
    )

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 503
    assert models.list_bookings()[0]["status"] == "PENDING"
    assert "notification_create" not in downstream.calls


def test_payment_http_rejection_is_not_retried_and_is_compensated(
    client,
    booking_payload,
    downstream,
):
    downstream.failures["create_payment"] = clients.DownstreamHTTPError(
        409,
        "Payment rejected",
    )

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 409
    assert downstream.calls.count("payment_create") == 1
    assert models.list_bookings()[0]["status"] == "PAYMENT_FAILED"


def test_confirm_transport_failure_refunds_then_releases(
    client,
    booking_payload,
    downstream,
):
    downstream.failures["confirm_room_allocation"] = (
        clients.ServiceUnavailableError("Room")
    )

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 503
    assert downstream.calls[-3:] == [
        "payment_refund",
        "room_release",
        "notification_create",
    ]
    stored = models.list_bookings()[0]
    assert stored["status"] == "PAYMENT_FAILED"
    assert stored["payment_id"] == downstream.payment_id


def test_confirm_business_failure_is_compensated_without_retry(
    client,
    booking_payload,
    downstream,
):
    downstream.failures["confirm_room_allocation"] = clients.DownstreamHTTPError(
        409,
        "Allocation cannot be confirmed",
    )

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 409
    assert downstream.calls.count("room_confirm") == 1
    assert downstream.calls.index("payment_refund") < downstream.calls.index(
        "room_release"
    )
    assert models.list_bookings()[0]["status"] == "PAYMENT_FAILED"


def test_failed_refund_never_releases_room_and_keeps_pending(
    client,
    booking_payload,
    downstream,
):
    downstream.failures["confirm_room_allocation"] = (
        clients.ServiceUnavailableError("Room")
    )
    downstream.failures["refund_payment"] = clients.ServiceUnavailableError(
        "Payment"
    )

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 503
    assert "room_release" not in downstream.calls
    assert models.list_bookings()[0]["status"] == "PENDING"


def test_release_failure_after_refund_keeps_pending_marker(
    client,
    booking_payload,
    downstream,
):
    downstream.failures["confirm_room_allocation"] = (
        clients.ServiceUnavailableError("Room")
    )
    downstream.failures["release_room_allocation"] = (
        clients.ServiceUnavailableError("Room")
    )

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 503
    assert downstream.calls.index("payment_refund") < downstream.calls.index(
        "room_release"
    )
    assert models.list_bookings()[0]["status"] == "PENDING"


def test_local_confirm_failure_runs_compensation_and_returns_controlled_500(
    client,
    booking_payload,
    downstream,
    monkeypatch,
):
    def fail_confirm(booking_id: int, payment_id: int):
        raise sqlite3.OperationalError("private database detail")

    monkeypatch.setattr(models, "confirm_booking", fail_confirm)

    response = client.post("/bookings", json=booking_payload)

    assert response.status_code == 500
    assert response.json() == {"detail": "Booking database error"}
    assert downstream.calls[-3:] == [
        "payment_refund",
        "room_release",
        "notification_create",
    ]
    assert models.list_bookings()[0]["status"] == "PAYMENT_FAILED"
