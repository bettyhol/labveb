"""Run a real end-to-end demonstration against the Docker Compose stack."""

from __future__ import annotations

import os
import sys
import uuid
from decimal import Decimal
from typing import Any

import httpx


USER_URL = os.getenv("USER_URL", "http://localhost:8001").rstrip("/")
HOTEL_URL = os.getenv("HOTEL_URL", "http://localhost:8002").rstrip("/")
ROOM_URL = os.getenv("ROOM_URL", "http://localhost:8003").rstrip("/")
BOOKING_URL = os.getenv("BOOKING_URL", "http://localhost:8004").rstrip("/")
PAYMENT_URL = os.getenv("PAYMENT_URL", "http://localhost:8005").rstrip("/")
NOTIFICATION_URL = os.getenv(
    "NOTIFICATION_URL",
    "http://localhost:8006",
).rstrip("/")

HTTP_TIMEOUT_SECONDS = 10.0
CHECK_IN = "2035-10-20"
CHECK_OUT = "2035-10-23"
OVERLAP_CHECK_IN = "2035-10-21"
OVERLAP_CHECK_OUT = "2035-10-22"
TOTAL_STEPS = 18

SERVICES = (
    ("User Service", USER_URL),
    ("Hotel Service", HOTEL_URL),
    ("Room Service", ROOM_URL),
    ("Booking Service", BOOKING_URL),
    ("Payment Service", PAYMENT_URL),
    ("Notification Service", NOTIFICATION_URL),
)


class DemoFailure(RuntimeError):
    """An expected, clearly reportable demo failure."""


def step(number: int, message: str) -> None:
    print(f"\n[{number}/{TOTAL_STEPS}] {message}")


def ok(message: str) -> None:
    print(f"[OK] {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DemoFailure(message)


def response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or "empty response"
    if isinstance(payload, dict) and "detail" in payload:
        return str(payload["detail"])
    return str(payload)


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    expected_status: int,
    **kwargs: Any,
) -> Any:
    try:
        response = client.request(method, url, **kwargs)
    except httpx.RequestError as error:
        raise DemoFailure(f"Service is unavailable for {method} {url}: {error}") from error
    if response.status_code != expected_status:
        raise DemoFailure(
            f"{method} {url} returned {response.status_code}, expected "
            f"{expected_status}: {response_detail(response)}"
        )
    try:
        return response.json()
    except ValueError as error:
        raise DemoFailure(f"{method} {url} returned invalid JSON") from error


def available_rooms(client: httpx.Client, hotel_id: int) -> list[dict[str, Any]]:
    result = request_json(
        client,
        "GET",
        f"{ROOM_URL}/rooms/available",
        expected_status=200,
        params={
            "hotel_id": hotel_id,
            "check_in": CHECK_IN,
            "check_out": CHECK_OUT,
            "guests": 2,
        },
    )
    require(isinstance(result, list), "Availability response is not a list")
    return result


def find_notification(
    notifications: list[dict[str, Any]],
    booking_id: int,
    notification_type: str,
) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in notifications
            if item.get("booking_id") == booking_id
            and item.get("type") == notification_type
        ),
        None,
    )


def run_demo() -> None:
    run_id = uuid.uuid4().hex[:8]
    room_a_number = f"D-{run_id}-301"
    room_b_number = f"D-{run_id}-302"

    print("=" * 64)
    print(" HOTEL BOOKING MICROSERVICES - END-TO-END DEMO")
    print("=" * 64)
    print(f"Run ID: {run_id}")

    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        step(1, "Checking all services")
        for service_name, base_url in SERVICES:
            health = request_json(
                client,
                "GET",
                f"{base_url}/health",
                expected_status=200,
            )
            require(
                isinstance(health, dict) and health.get("status") == "ok",
                f"{service_name} returned an invalid health response",
            )
            ok(f"{service_name} healthy")
        ok("6/6 services healthy")

        step(2, "Creating a unique User")
        email = f"demo-{run_id}@example.com"
        user = request_json(
            client,
            "POST",
            f"{USER_URL}/users",
            expected_status=201,
            json={
                "name": f"Demo User {run_id}",
                "email": email,
                "phone": "+380991234567",
            },
        )
        require(user.get("active") is True, "Created User is not active")
        user_id = int(user["id"])
        ok(f"User created: #{user_id} ({email})")

        step(3, "Creating a Hotel")
        hotel_name = f"Demo Hotel {run_id}"
        hotel = request_json(
            client,
            "POST",
            f"{HOTEL_URL}/hotels",
            expected_status=201,
            json={
                "name": hotel_name,
                "city": "Kharkiv",
                "address": "Demo Street, 1",
                "description": "Hotel created by automated microservices demo",
                "rating": 5,
            },
        )
        require(hotel.get("active") is True, "Created Hotel is not active")
        hotel_id = int(hotel["id"])
        ok(f"Hotel created: #{hotel_id}")

        step(4, "Creating two Rooms")
        room_a = request_json(
            client,
            "POST",
            f"{ROOM_URL}/rooms",
            expected_status=201,
            json={
                "hotel_id": hotel_id,
                "number": room_a_number,
                "room_type": "DELUXE",
                "capacity": 2,
                "price_per_night": 2500,
            },
        )
        room_b = request_json(
            client,
            "POST",
            f"{ROOM_URL}/rooms",
            expected_status=201,
            json={
                "hotel_id": hotel_id,
                "number": room_b_number,
                "room_type": "STANDARD",
                "capacity": 2,
                "price_per_night": 1800,
            },
        )
        room_a_id = int(room_a["id"])
        room_b_id = int(room_b["id"])
        ok(f"Rooms created: #{room_a_id} and #{room_b_id}")

        step(5, "Checking initial availability")
        initial_rooms = available_rooms(client, hotel_id)
        initial_ids = {int(room["id"]) for room in initial_rooms}
        require(
            {room_a_id, room_b_id}.issubset(initial_ids),
            "Both newly created Rooms must be initially available",
        )
        ok(f"Available rooms before booking: {len(initial_rooms)}")

        step(6, "Creating a successful Booking")
        booking = request_json(
            client,
            "POST",
            f"{BOOKING_URL}/bookings",
            expected_status=201,
            json={
                "user_id": user_id,
                "room_id": room_a_id,
                "check_in": CHECK_IN,
                "check_out": CHECK_OUT,
            },
        )
        booking_id = int(booking["id"])
        payment_id = int(booking["payment_id"])
        require(booking.get("status") == "CONFIRMED", "Booking is not CONFIRMED")
        require(booking.get("nights") == 3, "Expected exactly 3 nights")
        require(
            Decimal(str(booking.get("price_per_night"))) == Decimal("2500"),
            "Booking price snapshot is incorrect",
        )
        require(
            Decimal(str(booking.get("total_amount"))) == Decimal("7500"),
            "Booking total amount is incorrect",
        )
        ok(f"Booking #{booking_id} CONFIRMED; Payment #{payment_id}")

        step(7, "Inspecting Booking snapshot")
        stored_booking = request_json(
            client,
            "GET",
            f"{BOOKING_URL}/bookings/{booking_id}",
            expected_status=200,
        )
        expected_snapshot = {
            "hotel_id": hotel_id,
            "hotel_name": hotel_name,
            "room_id": room_a_id,
            "room_number": room_a_number,
            "room_type": "DELUXE",
        }
        require(
            all(stored_booking.get(key) == value for key, value in expected_snapshot.items()),
            "Booking snapshot does not match the source resources",
        )
        require(stored_booking.get("status") == "CONFIRMED", "Stored Booking changed state")
        ok(f"Booking snapshot verified: {hotel_name} / {room_a_number}")

        step(8, "Inspecting Room allocation")
        allocation = request_json(
            client,
            "GET",
            f"{ROOM_URL}/allocations/{booking_id}",
            expected_status=200,
        )
        require(allocation.get("status") == "CONFIRMED", "Allocation is not CONFIRMED")
        require(allocation.get("room_id") == room_a_id, "Allocation references another Room")
        ok("Room allocation CONFIRMED")

        step(9, "Inspecting Payment by booking correlation")
        payment = request_json(
            client,
            "GET",
            f"{PAYMENT_URL}/bookings/{booking_id}/payment",
            expected_status=200,
        )
        require(payment.get("id") == payment_id, "Payment ID does not match Booking")
        require(payment.get("status") == "PAID", "Payment is not PAID")
        require(Decimal(str(payment.get("amount"))) == Decimal("7500"), "Payment amount is incorrect")
        require(bool(payment.get("transaction_ref")), "Payment transaction_ref is missing")
        ok(f"Payment #{payment_id} PAID - 7500 UAH")

        step(10, "Inspecting confirmation Notification")
        notifications = request_json(
            client,
            "GET",
            f"{NOTIFICATION_URL}/users/{user_id}/notifications",
            expected_status=200,
        )
        confirmed_notice = find_notification(
            notifications,
            booking_id,
            "BOOKING_CONFIRMED",
        )
        require(confirmed_notice is not None, "BOOKING_CONFIRMED notification was not found")
        require(confirmed_notice.get("status") == "SENT", "Confirmation notification is not SENT")
        ok("BOOKING_CONFIRMED notification SENT")

        step(11, "Verifying the booked Room is unavailable")
        booked_ids = {int(room["id"]) for room in available_rooms(client, hotel_id)}
        require(room_a_id not in booked_ids, "Booked Room is still reported as available")
        require(room_b_id in booked_ids, "Unbooked Room disappeared from availability")
        ok("Booked Room is no longer available; the second Room remains available")

        step(12, "Attempting an overlapping Booking")
        overlap = request_json(
            client,
            "POST",
            f"{BOOKING_URL}/bookings",
            expected_status=409,
            json={
                "user_id": user_id,
                "room_id": room_a_id,
                "check_in": OVERLAP_CHECK_IN,
                "check_out": OVERLAP_CHECK_OUT,
            },
        )
        require("detail" in overlap, "Conflict response has no detail")
        ok("Overlapping Booking correctly rejected with 409")

        step(13, "Verifying conflict caused no change to the original workflow")
        original_booking = request_json(
            client,
            "GET",
            f"{BOOKING_URL}/bookings/{booking_id}",
            expected_status=200,
        )
        original_allocation = request_json(
            client,
            "GET",
            f"{ROOM_URL}/allocations/{booking_id}",
            expected_status=200,
        )
        original_payment = request_json(
            client,
            "GET",
            f"{PAYMENT_URL}/bookings/{booking_id}/payment",
            expected_status=200,
        )
        require(original_booking.get("status") == "CONFIRMED", "Original Booking was changed")
        require(original_allocation.get("status") == "CONFIRMED", "Original allocation was changed")
        require(original_payment.get("status") == "PAID", "Original Payment was changed")
        ok("Original Booking, allocation, and Payment remain valid")

        step(14, "Cancelling the Booking")
        cancelled = request_json(
            client,
            "POST",
            f"{BOOKING_URL}/bookings/{booking_id}/cancel",
            expected_status=200,
        )
        require(cancelled.get("status") == "CANCELLED", "Booking is not CANCELLED")
        ok(f"Booking #{booking_id} CANCELLED")

        step(15, "Verifying Payment refund")
        refunded = request_json(
            client,
            "GET",
            f"{PAYMENT_URL}/bookings/{booking_id}/payment",
            expected_status=200,
        )
        require(refunded.get("status") == "REFUNDED", "Payment is not REFUNDED")
        require(bool(refunded.get("refunded_at")), "Payment refunded_at is missing")
        require(bool(refunded.get("transaction_ref")), "Refunded Payment lost transaction_ref")
        refunded_at = refunded["refunded_at"]
        ok(f"Payment #{payment_id} REFUNDED")

        step(16, "Verifying allocation release and cancellation Notification")
        released = request_json(
            client,
            "GET",
            f"{ROOM_URL}/allocations/{booking_id}",
            expected_status=200,
        )
        require(released.get("status") == "RELEASED", "Allocation is not RELEASED")
        notifications = request_json(
            client,
            "GET",
            f"{NOTIFICATION_URL}/users/{user_id}/notifications",
            expected_status=200,
        )
        cancelled_notices = [
            item
            for item in notifications
            if item.get("booking_id") == booking_id
            and item.get("type") == "BOOKING_CANCELLED"
        ]
        require(len(cancelled_notices) == 1, "Expected one BOOKING_CANCELLED notification")
        require(cancelled_notices[0].get("status") == "SENT", "Cancellation notification is not SENT")
        ok("Room RELEASED and BOOKING_CANCELLED notification SENT")

        step(17, "Checking availability after cancellation")
        released_ids = {int(room["id"]) for room in available_rooms(client, hotel_id)}
        require(
            {room_a_id, room_b_id}.issubset(released_ids),
            "Released Room did not return to availability",
        )
        ok("Released Room is available again")

        step(18, "Repeating cancellation to verify idempotency")
        repeated = request_json(
            client,
            "POST",
            f"{BOOKING_URL}/bookings/{booking_id}/cancel",
            expected_status=200,
        )
        repeated_payment = request_json(
            client,
            "GET",
            f"{PAYMENT_URL}/bookings/{booking_id}/payment",
            expected_status=200,
        )
        repeated_notifications = request_json(
            client,
            "GET",
            f"{NOTIFICATION_URL}/users/{user_id}/notifications",
            expected_status=200,
        )
        repeated_cancelled_count = sum(
            item.get("booking_id") == booking_id
            and item.get("type") == "BOOKING_CANCELLED"
            for item in repeated_notifications
        )
        require(repeated.get("status") == "CANCELLED", "Repeated cancel changed Booking state")
        require(repeated_payment.get("status") == "REFUNDED", "Repeated cancel changed Payment state")
        require(repeated_payment.get("refunded_at") == refunded_at, "Repeated cancel changed refunded_at")
        require(repeated_cancelled_count == 1, "Repeated cancel created a duplicate notification")
        ok("Repeated cancellation is idempotent")

    print("\n" + "=" * 64)
    print(" DEMO COMPLETED SUCCESSFULLY")
    print("=" * 64)
    print(f"User ID: {user_id}")
    print(f"Hotel ID: {hotel_id}")
    print(f"Room IDs: {room_a_id}, {room_b_id}")
    print(f"Booking ID: {booking_id} - CANCELLED")
    print(f"Payment ID: {payment_id} - REFUNDED")
    print("Allocation: RELEASED")
    print("Room available after cancellation: true")


def main() -> int:
    try:
        run_demo()
    except DemoFailure as error:
        print(f"\n[FAIL] {error}", file=sys.stderr)
        return 1
    except (KeyError, TypeError, ValueError) as error:
        print(f"\n[FAIL] Service returned unexpected data: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
