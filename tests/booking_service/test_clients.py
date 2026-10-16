"""HTTP contract tests for Booking Service downstream clients."""

import json

import httpx
import pytest

from booking_service import clients


def test_client_uses_real_paths_payloads_and_responses(monkeypatch):
    monkeypatch.setattr(clients, "USER_SERVICE_URL", "http://user.test")
    monkeypatch.setattr(clients, "ROOM_SERVICE_URL", "http://room.test")
    monkeypatch.setattr(clients, "HOTEL_SERVICE_URL", "http://hotel.test")
    monkeypatch.setattr(clients, "PAYMENT_SERVICE_URL", "http://payment.test")
    monkeypatch.setattr(
        clients,
        "NOTIFICATION_SERVICE_URL",
        "http://notification.test",
    )
    requests: list[tuple[str, str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        requests.append((request.method, str(request.url), payload))
        path = request.url.path
        if path == "/users/1":
            return httpx.Response(
                200,
                json={"id": 1, "email": "user@example.com", "active": True},
            )
        if path == "/rooms/7":
            return httpx.Response(
                200,
                json={
                    "id": 7,
                    "hotel_id": 3,
                    "number": "301",
                    "room_type": "DELUXE",
                    "price_per_night": 2500,
                    "active": True,
                },
            )
        if path == "/hotels/3":
            return httpx.Response(
                200,
                json={"id": 3, "name": "Hotel", "active": True},
            )
        if path == "/allocations/hold":
            return httpx.Response(201, json={"booking_id": 9, "status": "HELD"})
        if path == "/payments":
            return httpx.Response(
                201,
                json={"id": 55, "booking_id": 9, "status": "PAID"},
            )
        if path == "/allocations/9/confirm":
            return httpx.Response(
                200,
                json={"booking_id": 9, "status": "CONFIRMED"},
            )
        if path == "/allocations/9/release":
            return httpx.Response(
                200,
                json={"booking_id": 9, "status": "RELEASED"},
            )
        if path == "/payments/55/refund":
            return httpx.Response(
                200,
                json={"id": 55, "status": "REFUNDED"},
            )
        return httpx.Response(201, json={"booking_id": 9, "status": "SENT"})

    boundary = clients.BookingServiceClients(httpx.MockTransport(handler))
    hold = {
        "booking_id": 9,
        "room_id": 7,
        "check_in": "2026-09-20",
        "check_out": "2026-09-23",
    }
    payment = {
        "booking_id": 9,
        "user_id": 1,
        "amount": 7500,
        "currency": "UAH",
        "method": "CARD",
    }
    notification = {
        "user_id": 1,
        "booking_id": 9,
        "type": "BOOKING_CONFIRMED",
        "channel": "EMAIL",
        "recipient": "user@example.com",
        "subject": "Booking confirmed",
        "message": "Booking #9 has been confirmed.",
    }

    assert boundary.get_user(1)["active"] is True
    assert boundary.get_room(7)["hotel_id"] == 3
    assert boundary.get_hotel(3)["name"] == "Hotel"
    assert boundary.hold_room(hold)["status"] == "HELD"
    assert boundary.create_payment(payment)["status"] == "PAID"
    assert boundary.confirm_room_allocation(9)["status"] == "CONFIRMED"
    assert boundary.release_room_allocation(9)["status"] == "RELEASED"
    assert boundary.refund_payment(55)["status"] == "REFUNDED"
    assert boundary.create_notification(notification)["status"] == "SENT"
    assert requests == [
        ("GET", "http://user.test/users/1", None),
        ("GET", "http://room.test/rooms/7", None),
        ("GET", "http://hotel.test/hotels/3", None),
        ("POST", "http://room.test/allocations/hold", hold),
        ("POST", "http://payment.test/payments", payment),
        ("POST", "http://room.test/allocations/9/confirm", None),
        ("POST", "http://room.test/allocations/9/release", None),
        ("POST", "http://payment.test/payments/55/refund", None),
        ("POST", "http://notification.test/notifications", notification),
    ]
    assert clients.HTTP_TIMEOUT_SECONDS == 5.0


def test_resource_not_found_returns_none():
    boundary = clients.BookingServiceClients(
        httpx.MockTransport(lambda request: httpx.Response(404))
    )

    assert boundary.get_user(999) is None


def test_downstream_business_error_is_preserved():
    boundary = clients.BookingServiceClients(
        httpx.MockTransport(
            lambda request: httpx.Response(409, json={"detail": "Room conflict"})
        )
    )

    with pytest.raises(clients.DownstreamHTTPError) as captured:
        boundary.hold_room({})

    assert captured.value.status_code == 409
    assert captured.value.detail == "Room conflict"


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500),
        lambda request: httpx.Response(200, content=b"not-json"),
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline")),
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timeout")),
    ],
)
def test_unreliable_downstream_response_is_controlled(handler):
    boundary = clients.BookingServiceClients(httpx.MockTransport(handler))

    with pytest.raises(clients.ServiceUnavailableError) as captured:
        boundary.get_user(1)

    assert str(captured.value) == "User service is unavailable"
