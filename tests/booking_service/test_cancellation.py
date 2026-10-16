"""Booking cancellation Saga, idempotency, and partial-failure tests."""

import sqlite3

from booking_service import clients, database, models


def create_confirmed(client, booking_payload) -> dict[str, object]:
    response = client.post("/bookings", json=booking_payload)
    assert response.status_code == 201
    assert response.json()["status"] == "CONFIRMED"
    return response.json()


def test_cancel_confirmed_booking_runs_refund_release_and_notification(
    client,
    booking_payload,
    downstream,
):
    booking = create_confirmed(client, booking_payload)
    downstream.calls.clear()

    response = client.post(f"/bookings/{booking['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert response.json()["payment_id"] == booking["payment_id"]
    assert downstream.calls == [
        "payment_refund",
        "room_release",
        "user_get",
        "notification_create",
    ]
    assert downstream.refunded_payment_ids == [booking["payment_id"]]
    assert downstream.payloads["notification"]["type"] == "BOOKING_CANCELLED"
    assert models.get_booking(int(booking["id"]))["status"] == "CANCELLED"


def test_repeated_cancel_is_noop_without_duplicate_side_effects(
    client,
    booking_payload,
    downstream,
):
    booking = create_confirmed(client, booking_payload)
    first = client.post(f"/bookings/{booking['id']}/cancel")
    calls_after_first = list(downstream.calls)
    refunded_at_first = downstream.refunded_at

    second = client.post(f"/bookings/{booking['id']}/cancel")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert downstream.calls == calls_after_first
    assert downstream.refunded_at == refunded_at_first
    cancelled_notifications = [
        payload
        for payload in downstream.notification_payloads
        if payload["type"] == "BOOKING_CANCELLED"
    ]
    assert len(cancelled_notifications) == 1


def test_refund_transport_failure_keeps_confirmed_and_never_releases(
    client,
    booking_payload,
    downstream,
):
    booking = create_confirmed(client, booking_payload)
    downstream.calls.clear()
    downstream.failures["refund_payment"] = clients.ServiceUnavailableError(
        "Payment"
    )

    response = client.post(f"/bookings/{booking['id']}/cancel")

    assert response.status_code == 503
    assert downstream.calls == ["payment_refund"]
    assert models.get_booking(int(booking["id"]))["status"] == "CONFIRMED"


def test_refund_business_failure_keeps_confirmed_and_never_releases(
    client,
    booking_payload,
    downstream,
):
    booking = create_confirmed(client, booking_payload)
    downstream.calls.clear()
    downstream.failures["refund_payment"] = clients.DownstreamHTTPError(
        409,
        "Refund rejected",
    )

    response = client.post(f"/bookings/{booking['id']}/cancel")

    assert response.status_code == 409
    assert downstream.calls == ["payment_refund"]
    assert models.get_booking(int(booking["id"]))["status"] == "CONFIRMED"


def test_release_failure_after_refund_keeps_confirmed(
    client,
    booking_payload,
    downstream,
):
    booking = create_confirmed(client, booking_payload)
    downstream.calls.clear()
    downstream.failures["release_room_allocation"] = (
        clients.ServiceUnavailableError("Room")
    )

    response = client.post(f"/bookings/{booking['id']}/cancel")

    assert response.status_code == 503
    assert downstream.calls == ["payment_refund", "room_release"]
    assert models.get_booking(int(booking["id"]))["status"] == "CONFIRMED"


def test_local_cancel_failure_is_controlled_and_keeps_confirmed_marker(
    client,
    booking_payload,
    downstream,
    monkeypatch,
):
    booking = create_confirmed(client, booking_payload)
    downstream.calls.clear()

    def fail_cancel(booking_id: int):
        raise sqlite3.OperationalError("private database detail")

    monkeypatch.setattr(models, "cancel_booking", fail_cancel)

    response = client.post(f"/bookings/{booking['id']}/cancel")

    assert response.status_code == 500
    assert response.json() == {"detail": "Booking database error"}
    assert downstream.calls == ["payment_refund", "room_release"]
    assert models.get_booking(int(booking["id"]))["status"] == "CONFIRMED"


def test_cancel_retry_after_partial_failure_reuses_same_payment(
    client,
    booking_payload,
    downstream,
):
    booking = create_confirmed(client, booking_payload)
    downstream.calls.clear()
    downstream.failure_sequences["release_room_allocation"] = [
        clients.ServiceUnavailableError("Room"),
        None,
    ]

    first = client.post(f"/bookings/{booking['id']}/cancel")
    second = client.post(f"/bookings/{booking['id']}/cancel")

    assert first.status_code == 503
    assert second.status_code == 200
    assert second.json()["status"] == "CANCELLED"
    assert downstream.refunded_payment_ids[-2:] == [
        booking["payment_id"],
        booking["payment_id"],
    ]
    assert downstream.calls[:4] == [
        "payment_refund",
        "room_release",
        "payment_refund",
        "room_release",
    ]


def test_cancellation_notification_failure_does_not_change_success(
    client,
    booking_payload,
    downstream,
):
    booking = create_confirmed(client, booking_payload)
    downstream.failures["create_notification"] = (
        clients.ServiceUnavailableError("Notification")
    )

    response = client.post(f"/bookings/{booking['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_cancellation_recipient_lookup_failure_is_best_effort(
    client,
    booking_payload,
    downstream,
):
    booking = create_confirmed(client, booking_payload)
    downstream.failures["get_user"] = clients.ServiceUnavailableError("User")

    response = client.post(f"/bookings/{booking['id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_pending_booking_cannot_be_cancelled(
    client,
    booking_payload,
    downstream,
):
    booking = create_confirmed(client, booking_payload)
    with database.get_connection() as connection:
        connection.execute(
            "UPDATE bookings SET status = 'PENDING' WHERE id = ?",
            (booking["id"],),
        )
        connection.commit()
    downstream.calls.clear()

    response = client.post(f"/bookings/{booking['id']}/cancel")

    assert response.status_code == 409
    assert downstream.calls == []


def test_payment_failed_booking_cannot_be_cancelled(
    client,
    booking_payload,
    downstream,
):
    downstream.payment_status = "FAILED"
    booking_response = client.post("/bookings", json=booking_payload)
    assert booking_response.status_code == 201
    downstream.calls.clear()

    response = client.post(
        f"/bookings/{booking_response.json()['id']}/cancel"
    )

    assert response.status_code == 409
    assert downstream.calls == []


def test_unknown_booking_cancel_returns_404_without_downstream_calls(
    client,
    downstream,
):
    response = client.post("/bookings/999/cancel")

    assert response.status_code == 404
    assert response.json() == {"detail": "Booking not found"}
    assert downstream.calls == []
